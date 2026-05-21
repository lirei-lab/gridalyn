"""
dispatch.py – DSO capacity auction clearing and CLS dispatch.

Implements:
  1. DSO congestion detection (probabilistic constraint check).
  2. Capacity Auction: DSO clears a pay-as-clear local capacity auction
     to procure the required flexibility volume, incorporating a safety
     margin γ to hedge against under-delivery risk.
  3. Stochastic Asset Failure: Models the probability of EVs opting out.
  4. Baseline-free settlement support: cleared offers carry explicit
     contractual caps used later for AMI penalty checks.
"""

from __future__ import annotations

import numpy as np

from gridalyn.operations.market.network_constraints import NetworkConstraintModel


class DSODispatcher:
    """
    DSO-side CLS advanced dispatch logic.

    Parameters
    ----------
    network           : NetworkConstraintModel – defines the physical constraint
                        proxy for IEEE C57.91 transformer thermal limits)
    dt_man_h          : management period duration in hours
    epsilon           : risk tolerance P(exceed) > ε → congestion declared
    stochastic_failure: probability (0 to 1) that an aggregator fails to curtail during dispatch
    """

    def __init__(
        self,
        network: NetworkConstraintModel,
        dt_man_h: float = 5.0 / 60.0,
        epsilon: float = 0.05,
        stochastic_failure_rate: float = 0.05,
    ):
        self.network = network
        self.dt_man_h = dt_man_h
        self.epsilon = epsilon
        self.failure_rate = stochastic_failure_rate
        
        # Calculate the required over-procurement margin (gamma)
        # If 5% fail, we need to procure 1 / 0.95 = ~1.052x the requirement
        self.gamma = (1.0 / (1.0 - self.failure_rate)) - 1.0 if self.failure_rate < 1.0 else 0.0
        self.rng = np.random.default_rng(1337)  # Seeded once per dispatch runner for stable random failure testing

    def detect_congestion_window(self, p_forecast_kw: np.ndarray, p_forecast_std_kw: np.ndarray, ambient_c: np.ndarray, staggered_block_ticks: int = None) -> list:
        # Evaluate expected thermal behavior
        theta_pred = self.network.thermal_model.simulate_profile(p_forecast_kw, ambient_c, dt_min=self.dt_man_h * 60)
        is_congested = theta_pred > self.network.thermal_model.theta_max
        
        n_steps = len(p_forecast_kw)
        
        # 1) Find the "original" continuous congestion windows based only on thermal limit violation
        in_window = False
        start_t = 0
        raw_windows = []
        original_congested_mask = np.zeros(n_steps, dtype=bool)
        
        for t in range(n_steps):
            if is_congested[t] and not in_window:
                in_window = True
                start_t = t
            elif not is_congested[t] and in_window:
                in_window = False
                end_t = t
                raw_windows.append((start_t, end_t))
                original_congested_mask[start_t:end_t] = True
                
        if in_window:
            raw_windows.append((start_t, n_steps))
            original_congested_mask[start_t:n_steps] = True
            
        # 2) Extend Day-Ahead windows for post-congestion soft-landing (rebound management)
        extended_windows = []
        dt_h = self.dt_man_h
        extension_ticks = int(3.0 / dt_h)  # 3 hours extension
        
        for (w_start, w_end) in raw_windows:
            new_end = min(n_steps, w_end + extension_ticks)
            extended_windows.append((w_start, new_end))
            
        # 3) Merge overlapping extended windows
        merged_windows = []
        for w in extended_windows:
            if not merged_windows:
                merged_windows.append(w)
            else:
                last = merged_windows[-1]
                if w[0] <= last[1]:
                    merged_windows[-1] = (last[0], max(last[1], w[1]))
                else:
                    merged_windows.append(w)
        raw_windows = merged_windows
            
        windows = []
        from scipy.stats import norm
        z_score = norm.ppf(1 - self.epsilon)
        p_worst_kw = p_forecast_kw + z_score * p_forecast_std_kw
        
        for (w_start, w_end) in raw_windows:
            blocks = []
            if staggered_block_ticks is not None:
                cur_start = w_start
                while cur_start < w_end:
                    cur_end = min(w_end, cur_start + staggered_block_ticks)
                    blocks.append((cur_start, cur_end))
                    cur_start = cur_end
            else:
                blocks.append((w_start, w_end))
                
            for (b_start, b_end) in blocks:
                mask = original_congested_mask[b_start:b_end]
                
                if np.any(mask):
                    max_idx = b_start + int(np.argmax(p_worst_kw[b_start:b_end] * mask))
                else:
                    max_idx = b_start
                
                d_lo = 0.0
                d_hi = np.max(p_worst_kw[b_start:b_end])
                d_optimal = d_hi
                
                theta_base = self.network.thermal_model.simulate_profile(p_worst_kw, ambient_c, dt_min=self.dt_man_h * 60)
                if np.max(theta_base) <= self.network.thermal_model.theta_max:
                    windows.append((b_start, b_end, 0.0, max_idx))
                    continue
                    
                for _ in range(15):
                    d_mid = (d_lo + d_hi) / 2.0
                    p_test = p_worst_kw.copy()
                    
                    mask = original_congested_mask[b_start:b_end]
                    if np.any(mask):
                        p_test[b_start:b_end] = np.where(mask, p_test[b_start:b_end] - d_mid, p_test[b_start:b_end])
                    else:
                        p_test[b_start:b_end] -= d_mid
                        
                    p_test = np.maximum(0, p_test)
                    
                    theta_test = self.network.thermal_model.simulate_profile(p_test, ambient_c, dt_min=self.dt_man_h * 60)
                    
                    if np.max(theta_test) <= self.network.thermal_model.theta_max:
                        d_hi = d_mid
                        d_optimal = d_mid
                    else:
                        d_lo = d_mid
                        
                windows.append((b_start, b_end, float(d_optimal), max_idx))
                
        return windows

    def auction_clear_capacity(
        self,
        portfolios: list,  # list of BlockFlexPortfolio
        d_required_kw: float,
        t_idx: int = 0,
        clearing_period_h: float = 0.25
    ) -> dict:
        """
        Pay-as-clear local capacity auction.
        Sorts building limitation offers by cost and clears the cheapest Soft CLS.
        If the marginal price exceeds the cost of Hard CLS, Soft CLS procurement stops natively.
        
        Returns {"c_mcp": float, "allocations": dict of block_id -> {res_name: delta_p_soft_kw}}
        plus the explicit contractual cap recorded at clearing.
        delta_p_soft_kw = max(0, p_ref_kw - p_cap_kw) is the cleared limitation volume.
        """
        c_hard = 10.0  # Hard-CLS ceiling price ($/(kW*h) over the clearing interval)
        target_curtailment = d_required_kw * (1.0 + self.gamma)
        
        # Collect all voluntary limitation offers for the specific period
        all_offers = []
        for port in portfolios:
            port_offers = port.generate_limitation_offers(t_idx, clearing_period_h=clearing_period_h)
            for res_name, offer in port_offers.items():
                if "p_ref_kw" not in offer or "p_cap_kw" not in offer:
                    raise ValueError(
                        "limitation offers must define p_ref_kw and p_cap_kw"
                    )
                p_ref = float(offer["p_ref_kw"])
                p_cap = float(offer["p_cap_kw"])
                # Admissibility screen from the paper: only binding caps can
                # receive positive-cost settlement capacity.
                if p_cap >= p_ref:
                    continue
                p_flex = float(offer.get("delta_p_kw", max(0.0, p_ref - p_cap)))

                if p_flex <= 0:
                    continue

                all_offers.append({
                    "cost": offer["c_limit_per_kw_h"],
                    "volume": p_flex,
                    "p_ref_kw": p_ref,
                    "p_cap_kw": p_cap,
                    "block_id": port.block_id,
                    "res_name": res_name
                })
        cleared_volume = 0.0
        c_mcp = 0.0
        allocations = {port.block_id: {} for port in portfolios}
        contract_caps = {port.block_id: None for port in portfolios}
        contract_refs = {port.block_id: None for port in portfolios}
        
        # Group offers by exact cost to implement Pro-Rata clearing for ties
        from collections import defaultdict
        cost_tiers = defaultdict(list)
        for offer in all_offers:
            cost_tiers[offer["cost"]].append(offer)
            
        sorted_costs = sorted(cost_tiers.keys())
        
        for cost in sorted_costs:
            if cost > c_hard:
                break
                
            tier_offers = cost_tiers[cost]
            tier_volume = sum(o["volume"] for o in tier_offers)
            needed = target_curtailment - cleared_volume
            
            if needed <= 0:
                break
                
            c_mcp = max(c_mcp, cost)
            
            if tier_volume <= needed:
                # Clear entire tier sequentially
                for offer in tier_offers:
                    allocations[offer["block_id"]][offer["res_name"]] = offer["volume"]
                    contract_refs[offer["block_id"]] = offer["p_ref_kw"]
                    accepted_kw = sum(allocations[offer["block_id"]].values())
                    contract_caps[offer["block_id"]] = offer["p_ref_kw"] - accepted_kw
                cleared_volume += tier_volume
            else:
                # Pro-Rata marginal clearing to ensure equitable distribution
                pro_rata_factor = needed / tier_volume
                for offer in tier_offers:
                    allocated_vol = offer["volume"] * pro_rata_factor
                    allocations[offer["block_id"]][offer["res_name"]] = allocated_vol
                    contract_refs[offer["block_id"]] = offer["p_ref_kw"]
                    accepted_kw = sum(allocations[offer["block_id"]].values())
                    contract_caps[offer["block_id"]] = offer["p_ref_kw"] - accepted_kw
                cleared_volume += needed
                break
                
        return {
            "c_mcp": c_mcp,
            "allocations": allocations,
            "contract_caps": contract_caps,
            "contract_refs": contract_refs,
        }

    def dispatch(
        self,
        d_required_kw: float,
        dt_man_h: float,
        portfolios: list,
        t_idx: int = 0,
        firm_allocations: dict = None,
        firm_c_mcp: float = None,
        firm_peak_t: int = None,
        firm_contract_caps: dict = None,
        clearing_period_h: float = 0.25
    ) -> dict:
        """
        Calculates required response and executes the sequence of fallback dispatches.
        """
        res = {
            "c_soft_price": 0.0,
            "soft_cls_kw": 0.0,
            "shortfall_kw": 0.0,
            "allocations": {}
        }
        
        if d_required_kw <= 0 and firm_allocations is None:
            return res
            
        # 1. Clear Soft CLS auction natively at period t_idx or use assigned firm block contract
        if firm_allocations is not None and firm_c_mcp is not None:
             c_soft_star = firm_c_mcp
             optimal_curtailments = firm_allocations
             contract_caps = firm_contract_caps or {}
        elif firm_c_mcp is not None:
             # Profiled Block: Dynamic allocation based on current d_required_kw, but locked-in block price
             auction_res = self.auction_clear_capacity(portfolios, d_required_kw, t_idx, clearing_period_h)
             c_soft_star = firm_c_mcp
             optimal_curtailments = auction_res["allocations"]
             contract_caps = auction_res.get("contract_caps", {})
        else:
             auction_res = self.auction_clear_capacity(portfolios, d_required_kw, t_idx, clearing_period_h)
             c_soft_star = auction_res["c_mcp"]
             optimal_curtailments = auction_res["allocations"]
             contract_caps = auction_res.get("contract_caps", {})

        allocation = []
        
        for port in portfolios:
            # Structurally retrieve optimal cleared allocations
            bids = optimal_curtailments[port.block_id]
            
            # Identify the correct native trace reference based on aggregator type
            if hasattr(port, "get_capacity_bounds"):
                expected_native_load = port.get_capacity_bounds(t_idx)[0]
            elif hasattr(port, "p_req_kw"):
                expected_native_load = port.p_req_kw
            else:
                expected_native_load = sum(r.available_kw for r in port.resources)
                
            # Simulate True Physical Delivery
            # Rather than fake stochastic dice rolls, we pass the true physical trace
            # for the aggregated baseline load organically.
            delivered = port.simulate_delivery(
                self.rng, 
                bids, 
                actual_load_kw=expected_native_load,
                t=t_idx,
                firm_peak_t=firm_peak_t
            )
            
            # Use the explicit contractual cap recorded at clearing for AMI settlement.
            p_cap_limit_kw = contract_caps.get(port.block_id)
            if p_cap_limit_kw is None and bids:
                raise RuntimeError(
                    f"Missing contractual cap for cleared portfolio {port.block_id}."
                )

            allocation.append({
                "block_id": port.block_id,
                "bids_kw": bids,
                "delivered_kw": delivered,
                "expected_native_load_kw": expected_native_load,
                "p_cap_limit_kw": p_cap_limit_kw
            })

        # Sum delivered curtailment by resource type
        total_delivered_kw = 0.0
        delivered_by_resource = {}
        for a in allocation:
            for res_name, val in a["delivered_kw"].items():
                delivered_by_resource[res_name] = delivered_by_resource.get(res_name, 0.0) + val
                total_delivered_kw += val

        # Calculate Two-Stage Contributions
        # If the delivered Soft CLS falls short of the physical requirement (d_kw),
        # the DSO must trigger deterministic Interrupted CLS (Hard shedding)
        shortfall_kw = max(0.0, d_required_kw - total_delivered_kw)
        soft_cls_kw = min(total_delivered_kw, d_required_kw)  # Effective Soft CLS covering the requirement
        over_procured_kw = max(0.0, total_delivered_kw - d_required_kw) # Wasted flexibility

        return {
            "congested": True,
            "d_required_kw": d_required_kw,
            "d_target_with_margin_kw": d_required_kw * (1.0 + self.gamma),
            "total_curtailment_delivered_kw": total_delivered_kw,
            "delivered_by_resource_kw": delivered_by_resource,
            "soft_cls_kw": soft_cls_kw,
            "over_procured_kw": over_procured_kw,
            "shortfall_kw": shortfall_kw,
            "c_soft_price": c_soft_star,
            "dt_man_h": dt_man_h,
            "allocation": allocation,
        }

    def compute_hard_cls(self, unenrolled_ev_load_kw: float, shortfall_kw: float) -> dict:
        """
        If Soft CLS falls short, the DSO triggers deterministic Hard CLS
        by physically disconnecting EV chargers in non-participating blocks.
        """
        if shortfall_kw <= 0:
            return {"hard_cls_kw": 0.0, "residual_overload_kw": 0.0}
            
        # We can only disconnect what is actually drawing power
        hard_cls_available = unenrolled_ev_load_kw
        hard_cls_used = min(hard_cls_available, shortfall_kw)
        residual = max(0.0, shortfall_kw - hard_cls_used)
        
        return {
            "hard_cls_kw": hard_cls_used,
            "residual_overload_kw": residual,
        }

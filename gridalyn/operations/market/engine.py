"""
engine.py - Time-Domain Market Simulation Engine

This module abstracts the time-series execution of the localized flexibility market.
It manages probabilistic congestion detection, dynamic portfolio formulation,
and sequential market clearing over a full simulation horizon.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm

from gridalyn.operations.market.dso_dispatch import DSODispatcher
from gridalyn.operations.market.aggregator import generate_residential_portfolios
from gridalyn.operations.market.network_constraints import NetworkConstraintModel
from gridalyn.operations.market.settlement import calculate_period_settlement


class MarketSimulationEngine:
    """
    Time-Domain Simulation Engine for the Two-Stage Capacity Limitation Service (CLS).
    
    This engine abstracts the iterative time-loop, handling probabilistic constraint
    checks at each timestep, dynamically generating the participating aggregators,
    and dispatching both Soft-CLS (voluntary) and Hard-CLS (mandatory).
    """
    def __init__(self, network: NetworkConstraintModel, dispatcher: DSODispatcher):
        self.network = network
        self.dispatcher = dispatcher

    def run(
        self,
        p_base_kw_mean: np.ndarray,
        p_base_kw_std: np.ndarray,
        p_ev_kw_mean: np.ndarray,
        p_ev_kw_std: np.ndarray,
        t_out_trace_c: np.ndarray,
        dt_man_h: float = 5.0 / 60.0,
        n_total_blocks: int = 160,
        participation_rate: float = 0.30,
        epsilon: float = 0.05,
        is_profiled: bool = False,
        p_tot_kw_realized: np.ndarray = None,
        p_ev_kw_realized: np.ndarray = None,
        market_resolution_h: float = 0.5,
        non_delivery_penalty: float = 10.0,
        min_aggregator_cost: float = 3.0,
        max_aggregator_cost: float = 8.0,
        pay_full_block: bool = False,
    ) -> pd.DataFrame:
        """
        Executes the flexibility market simulation over the provided time horizon.
        
        Parameters
        ----------
        p_base_kw_mean : np.ndarray
            Mean native baseline load (e.g., heating, background apps) in kW.
        p_base_kw_std : np.ndarray
            Standard deviation of the baseline load.
        p_ev_kw_mean : np.ndarray
            Mean unmanaged Electric Vehicle load in kW.
        p_ev_kw_std : np.ndarray
            Standard deviation of the EV load.
        t_out_trace_c : np.ndarray
            Ambient outdoor temperature trace in Celsius.
        dt_man_h : float
            Timestep duration in hours (default 5/60 for the case-study 5-minute traces).
        n_total_blocks : int
            Total physical feeder blocks supplied by the substation node.
        participation_rate : float
            Fraction of total blocks offering voluntary thermal modulation (Soft CLS).
        epsilon : float
            Probabilistic risk tolerance for thermal breaches (e.g., 0.05 for 95% confidence).
            
        Returns
        -------
        pd.DataFrame
            Structured time-series results detailing unmanaged load, targets,
            auction clearing prices, and Soft/Hard CLS dispatch volumes.
        """
        n_steps = len(t_out_trace_c)
        self.dispatcher.dt_man_h = dt_man_h
        steps_per_clearing = max(1, int(round(market_resolution_h / dt_man_h)))
        
        p_tot_kw_mean = p_base_kw_mean + p_ev_kw_mean
        p_tot_kw_std = np.sqrt(p_base_kw_std**2 + p_ev_kw_std**2)
        z_score = norm.ppf(1 - epsilon)
        security_load_kw = (
            p_tot_kw_realized
            if p_tot_kw_realized is not None
            else p_tot_kw_mean + z_score * p_tot_kw_std
        )
        thermal_limit_kw = np.zeros(n_steps)
        
        # 1. Detect contiguous congestion windows. The paper case partitions long
        # congestion envelopes into 2-hour profiled blocks.
        staggered_block_ticks = max(1, int(round(2.0 / dt_man_h)))
        windows = self.dispatcher.detect_congestion_window(
            p_forecast_kw=p_tot_kw_mean,
            p_forecast_std_kw=p_tot_kw_std,
            ambient_c=t_out_trace_c,
            staggered_block_ticks=staggered_block_ticks
        )
        
        # 2. Persistently instantiate the building supply curve (OOP Aggregators)
        # Adding heterogeneous cost bounds ensures the clearing optimization sequentially picks
        # the cheapest participants rather than defaulting to mass Pro-Rata synchronicity.
        portfolios = generate_residential_portfolios(
            p_native_aggregate_kw_trace=p_base_kw_mean,
            n_total_blocks=n_total_blocks,
            participation_rate=participation_rate,
            min_cost=min_aggregator_cost,
            max_cost=max_aggregator_cost,
            time_step_h=dt_man_h
        )
        
        res_d_soft_kw = np.zeros(n_steps)
        res_d_hard_kw = np.zeros(n_steps)
        res_prices = np.zeros(n_steps)
        res_soft_payments = np.zeros(n_steps)
        res_soft_penalties = np.zeros(n_steps)
        res_targets = np.zeros(n_steps)
        res_contracted_soft_kw = np.zeros(n_steps)
        
        res_allocations = {port.block_id: np.zeros(n_steps) for port in portfolios}
        res_deficits = {port.block_id: np.zeros(n_steps) for port in portfolios}
        res_marginal_costs = {port.block_id: np.zeros(n_steps) for port in portfolios}
        res_rebound_kw = np.zeros(n_steps)
        
        # 2.5 FIRST STAGE (Here-and-Now): Stochastic capacity dimensioning
        # Pre-clear firm block capacity contracts for identified congestion windows.
        # This contracts Soft-CLS before uncertainty is realized using the
        # chance-constrained target and delivery margin.
        window_contracts = {}
        for w in windows:
            start_t, end_t, max_def, peak_t = w
            if max_def > 0:
                # Clear the Day-Ahead (DA) auction for the expected max target
                auction_res = self.dispatcher.auction_clear_capacity(portfolios, max_def, t_idx=peak_t)
                window_contracts[(start_t, end_t)] = (auction_res, max_def, peak_t)
                
        # Pre-calculate target deficits for all t, independent of dynamic state
        res_targets_raw = np.zeros(n_steps)
        for t in range(n_steps):
            in_window = False
            active_contract = None
            for w in windows:
                if w[0] <= t < w[1]:
                    in_window = True
                    active_contract = window_contracts.get((w[0], w[1]))
                    break
                    
            if in_window:
                if p_tot_kw_realized is not None:
                    s_limit_kw = self.network.p_limit_kw
                    if self.network.thermal_model is not None:
                        s_limit_kw = self.network.thermal_model.max_load_for_temp(t_out_trace_c[t])
                    actual_deficit = max(0.0, p_tot_kw_realized[t] - s_limit_kw)
                    if active_contract is not None:
                        _, max_def, _ = active_contract
                        res_targets_raw[t] = min(max_def, actual_deficit)
                    else:
                        res_targets_raw[t] = actual_deficit
                else:
                    check = self.network.probabilistic_constraint_check(
                        p_tot_kw_mean[t], p_tot_kw_std[t], ambient_c=t_out_trace_c[t], epsilon=epsilon
                    )
                    if active_contract is not None:
                        _, max_def, _ = active_contract
                        res_targets_raw[t] = min(max_def, check["congestion_relief_kw"])
                    else:
                        res_targets_raw[t] = check["congestion_relief_kw"]
            else:
                if p_tot_kw_realized is not None:
                    s_limit_kw = self.network.p_limit_kw
                    if self.network.thermal_model is not None:
                        s_limit_kw = self.network.thermal_model.max_load_for_temp(t_out_trace_c[t])
                    res_targets_raw[t] = max(0.0, p_tot_kw_realized[t] - s_limit_kw)
                else:
                    check = self.network.probabilistic_constraint_check(
                        p_tot_kw_mean[t], p_tot_kw_std[t], ambient_c=t_out_trace_c[t], epsilon=epsilon
                    )
                    res_targets_raw[t] = check["congestion_relief_kw"]

        # 3. SECOND STAGE (Real-Time Recourse): Dynamic Dispatch and Penalty Activation
        # Sweep through time. Uncertainty (load/temp) is realized dynamically per timestep.
        
        block_allocations = None
        block_c_mcp = None
        block_peak_t = None
        block_contract_caps = None
        block_cleared_kw = 0.0

        for t in range(n_steps):
            offer = {}  # Initialize empty offer for this timestep
            
            # 1. Compute attempted rebound dynamically from building thermal deficit (Soft-CLS only).
            # NOTE: Hard-CLS (EVs) produce NO electrical rebound — EV chargers are constant-power
            # devices that resume at their normal baseline rate upon reconnection.
            # The rebound estimate is used ONLY for thermal margin clamping at the end of the timestep,
            # NOT for congestion deficit calculation (to avoid circular feedback).
            
            # 2. Re-evaluate real-time physical load and deficit
            # Congestion is evaluated against the RAW unmanaged load only.
            # Rebound is handled separately and clamped to available margin post-dispatch.
            s_limit_kw = self.network.p_limit_kw
            if self.network.thermal_model is not None:
                s_limit_kw = self.network.thermal_model.max_load_for_temp(t_out_trace_c[t])
            thermal_limit_kw[t] = s_limit_kw
                
            if p_tot_kw_realized is not None:
                current_p_tot = p_tot_kw_realized[t]
                rt_deficit = max(0.0, current_p_tot - s_limit_kw)
            else:
                current_p_tot = p_tot_kw_mean[t]
                check = self.network.probabilistic_constraint_check(
                    current_p_tot, p_tot_kw_std[t], ambient_c=t_out_trace_c[t], epsilon=epsilon
                )
                rt_deficit = check["congestion_relief_kw"]
                
            # Find if we are currently inside a DA window
            in_window = False
            active_contract = None
            for w in windows:
                if w[0] <= t < w[1]:
                    in_window = True
                    active_contract = window_contracts.get((w[0], w[1]))
                    break
                    
            if in_window and active_contract is not None:
                _, max_def, _ = active_contract
                if is_profiled:
                    # Scheduled Profile: The contract RESERVES capacity up to max_def,
                    # but the DSO dispatches only the real-time physical deficit.
                    # Buildings are released as soon as congestion resolves, enabling
                    # immediate thermal rebound rather than waiting for contract expiry.
                    target_deficit = min(max_def, rt_deficit)
                else:
                    # Capacity Option: DSO only dispatches what is physically needed up to the contract limit
                    target_deficit = min(max_def, rt_deficit)
            else:
                target_deficit = rt_deficit
                
            res_targets[t] = target_deficit

            if is_profiled and t % steps_per_clearing == 0:
                end_lookahead = min(n_steps, t + steps_per_clearing)
                block_targets = res_targets_raw[t:end_lookahead]
                block_max_def = float(np.max(block_targets))
                
                if block_max_def > 0:
                    block_peak_t = t + int(np.argmax(block_targets))
                    auction_res = self.dispatcher.auction_clear_capacity(
                        portfolios, block_max_def, t_idx=block_peak_t, clearing_period_h=market_resolution_h
                    )
                    block_allocations = auction_res["allocations"]
                    block_c_mcp = auction_res["c_mcp"]
                    block_contract_caps = auction_res.get("contract_caps", {})
                    # Total cleared Soft-CLS capacity reserved for this block.
                    # The aggregators commit this capacity for the full block
                    # duration, so it is the basis of the availability payment.
                    block_cleared_kw = float(
                        sum(sum(bids.values()) for bids in block_allocations.values())
                    )
                else:
                    block_allocations = None
                    block_c_mcp = None
                    block_peak_t = None
                    block_contract_caps = None
                    block_cleared_kw = 0.0
            
            if target_deficit > 0:
                # Execute Dispatcher for specific physical period t
                # In profiled scenarios, the active 30-minute market block is the
                # binding firm contract. Non-profiled runs keep the window-level
                # day-ahead capacity option.
                if is_profiled and block_allocations is not None and block_c_mcp is not None:
                    firm_allocs = block_allocations
                    firm_c_mcp = block_c_mcp
                    firm_peak_t = block_peak_t
                    firm_contract_caps = block_contract_caps
                else:
                    firm_allocs = active_contract[0]["allocations"] if active_contract else None
                    firm_c_mcp = active_contract[0]["c_mcp"] if active_contract else None
                    firm_peak_t = active_contract[2] if active_contract else None
                    firm_contract_caps = active_contract[0].get("contract_caps", {}) if active_contract else None
                    
                offer = self.dispatcher.dispatch(
                    d_required_kw=target_deficit,
                    dt_man_h=dt_man_h,
                    portfolios=portfolios,
                    t_idx=t,
                    firm_allocations=firm_allocs,
                    firm_c_mcp=firm_c_mcp,
                    firm_peak_t=firm_peak_t,
                    firm_contract_caps=firm_contract_caps,
                    clearing_period_h=market_resolution_h
                )
                
                res_d_soft_kw[t] = offer["soft_cls_kw"]
                res_prices[t] = offer["c_soft_price"]
                
                # Evaluate structural residual overload (Interrupted Hard-CLS)
                # Hard-CLS is ONLY activated if the raw PHYSICAL load (unmanaged - soft_cls)
                # still breaches the thermal limit. Rebound is NOT included here because:
                # (a) Rebound is clamped to available thermal margin in update_state
                # (b) Including it would cause circular false-positive breaches
                actual_unmanaged_load = security_load_kw[t]
                true_physical_load = actual_unmanaged_load - offer["soft_cls_kw"]
                actual_physical_shortfall = max(0.0, true_physical_load - s_limit_kw)
                
                if actual_physical_shortfall > 0:
                    ev_avail = p_ev_kw_realized[t] if p_ev_kw_realized is not None else p_ev_kw_mean[t]
                    hard_res = self.dispatcher.compute_hard_cls(
                        unenrolled_ev_load_kw=ev_avail,
                        shortfall_kw=actual_physical_shortfall
                    )
                    res_d_hard_kw[t] = hard_res["hard_cls_kw"]
                    
                # Deterministic Financial Settlement
                period_net_profit = 0.0
                period_penalty = 0.0
                period_contracted_kw = 0.0
                for a in offer.get("allocation", []):
                    expected_unmanaged = a.get("expected_native_load_kw", 0.0)
                    delivered_bids = a.get("delivered_kw", {})
                    bids = a.get("bids_kw", {})
                    
                    period_contracted_kw += sum(bids.values())
                    res_allocations[a["block_id"]][t] = sum(bids.values())
                    
                    # Actual modeled meter reading drawn
                    actual_meter = expected_unmanaged - sum(delivered_bids.values())
                    
                    receipt = calculate_period_settlement(
                        allocations_kw=a.get("bids_kw", {}),
                        c_mcp_lambda=offer["c_soft_price"],
                        actual_p_meter_kw=actual_meter,
                        dt_h=dt_man_h,
                        lambda_pen_penalty=non_delivery_penalty,
                        p_cap_limit_kw=a.get("p_cap_limit_kw")
                    )
                    period_net_profit += receipt.net_profit
                    period_penalty += receipt.penalty_deduction
                    
                res_soft_payments[t] = period_net_profit
                res_soft_penalties[t] = period_penalty
                res_contracted_soft_kw[t] = period_contracted_kw

            elif pay_full_block and block_allocations is not None and block_c_mcp:
                # Capacity-availability payment (paper Eq. 17): a cleared block
                # reserves capacity for its full duration, so the aggregators are
                # paid the reservation at every timestep of the block — not only
                # the timesteps with an active real-time deficit. The building is
                # released here (no curtailment), so its meter stays at native
                # load below the contracted cap and accrues no breach penalty.
                res_soft_payments[t] = block_cleared_kw * block_c_mcp * dt_man_h
                res_contracted_soft_kw[t] = block_cleared_kw

            # --- Stateful thermal update (UNCONDITIONAL per timestep) ---
            # Building thermal recovery (rebound) must be processed every timestep.
            # Each building recovers independently when its own curtailed_kw = 0.
            # The total rebound is then clamped to the available thermal margin to
            # prevent the recovery itself from breaching the transformer limit.
            alloc_dict = {}
            if offer:
                for a in offer.get("allocation", []):
                    alloc_dict[a.get("block_id")] = sum(a.get("delivered_kw", {}).values())

            # Compute available thermal margin for rebound clamping
            actual_load_now = security_load_kw[t]
            managed_load_now = actual_load_now - res_d_soft_kw[t] - res_d_hard_kw[t]
            available_margin_kw = max(0.0, s_limit_kw - managed_load_now)

            # Phase 1: Compute unclamped rebound from each building
            unclamped_rebound_tot = 0.0
            building_rebounds = {}
            for port in portfolios:
                if hasattr(port, "update_state"):
                    curtailed_kw = alloc_dict.get(port.block_id, 0.0)
                    p_req = port.get_capacity_bounds(t)[0]
                    rb = port.update_state(curtailed_kw, dt_man_h, p_req)
                    building_rebounds[port.block_id] = rb
                    unclamped_rebound_tot += rb

            # Phase 2: Clamp total rebound to available thermal margin
            if unclamped_rebound_tot > available_margin_kw and unclamped_rebound_tot > 0:
                scale = available_margin_kw / unclamped_rebound_tot
                actual_rebound_tot = available_margin_kw
                # Return un-recovered energy back to each building's deficit
                for port in portfolios:
                    if port.block_id in building_rebounds and building_rebounds[port.block_id] > 0:
                        excess = building_rebounds[port.block_id] * (1.0 - scale)
                        port.accumulated_deficit_kwh += excess * dt_man_h
            else:
                actual_rebound_tot = unclamped_rebound_tot

            for port in portfolios:
                if hasattr(port, "accumulated_deficit_kwh"):
                    res_deficits[port.block_id][t] = port.accumulated_deficit_kwh
                if hasattr(port, "calculate_period_cost"):
                    res_marginal_costs[port.block_id][t] = port.calculate_period_cost(t)

            res_rebound_kw[t] = actual_rebound_tot
                        
        res_dict = {
            "p_tot_mean_kw": p_tot_kw_mean,
            "p_tot_std_kw": p_tot_kw_std,
            "target_deficit_kw": res_targets,
            "clearing_price": res_prices,
            "soft_cls_kw": res_d_soft_kw,
            "contracted_soft_kw": res_contracted_soft_kw,
            "hard_cls_kw": res_d_hard_kw,
            "rebound_kw": res_rebound_kw,
            "managed_load_kw": (p_tot_kw_realized if p_tot_kw_realized is not None else p_tot_kw_mean) + res_rebound_kw - res_d_soft_kw - res_d_hard_kw,
            "security_load_kw": security_load_kw,
            "thermal_limit_kw": thermal_limit_kw,
            "managed_worst_kw": security_load_kw + res_rebound_kw - res_d_soft_kw - res_d_hard_kw,
            "market_settlement_cost": res_soft_payments,
            "market_penalties": res_soft_penalties
        }
        
        for block_id, trace in res_allocations.items():
            res_dict[f"alloc_{block_id}"] = trace
        for block_id, trace in res_deficits.items():
            res_dict[f"deficit_{block_id}"] = trace
        for block_id, trace in res_marginal_costs.items():
            res_dict[f"marginal_cost_{block_id}"] = trace
            
        df_results = pd.DataFrame(res_dict)
        return df_results

"""Two-stage Soft/Hard CLS engine MODE — the baseline-authoring path.

This mode bundles the two-stage Capacity Limitation Service engine path
unchanged in behavior (CLEAR-01/02: it survives as a named mode, it is NOT
deleted — deleting it would re-baseline every committed number, D-01):

* ``DSODispatcher`` — DSO-side capacity-auction clearing and CLS dispatch
  (from ``market/dso_dispatch.py``);
* ``MarketSimulationEngine`` — time-domain two-stage simulation loop (from
  ``market/engine.py``);
* the residential aggregator physical model ``BuildingAggregator`` and the
  ``generate_residential_portfolios`` factory (from ``market/aggregator.py``;
  DOM-04 relocation of generation to ``assets/datagen`` stays DEFERRED — it
  crosses the operations->assets boundary);
* ``run_cls_capacity_allocation`` / ``CLSCapacityAllocationResult`` /
  ``scenario_label`` — the EV-scenario sweep wrapper (from
  ``flexibility/cls_market.py``).

CLEAR-03 determinism is LOCKED, not invented: the shared
``np.random.default_rng(1337)`` draw site, the ``sorted(cost_tiers.keys())``
merit order, the insertion-ordered offer/allocation dicts, and the ordered
``portfolios`` list are all moved verbatim — no draw site is reordered.

The ``NetworkConstraintModel`` Protocol now lives in its canonical home
:mod:`gridalyn.operations.constraints` (D-02); this module imports it downward
from there. ``calculate_period_settlement`` is now imported
from its canonical home :mod:`gridalyn.operations.settlement` (the baseline
source, §4), reached as the engine-path settlement collaborator.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.assets.modeling.thermal import ThermalForecast, thermal_forecast_metadata
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from gridalyn.operations.constraints import NetworkConstraintModel
from gridalyn.operations.settlement import calculate_period_settlement

# ---------------------------------------------------------------------------
# Residential aggregator physical models (from market/aggregator.py)
# ---------------------------------------------------------------------------


# ``FlexResource`` and ``BlockFlexPortfolio`` were removed here: neither had a
# single reference in ``gridalyn/``, ``tests/`` or ``projects/``, and
# ``BlockFlexPortfolio.simulate_delivery`` did not accept the ``t`` /
# ``firm_peak_t`` keywords that ``DSODispatcher.dispatch`` passes
# unconditionally -- so a portfolio of that type would have raised ``TypeError``
# rather than clearing. ``BuildingAggregator`` below is the only portfolio type
# the engine has ever run.


@dataclass
class BuildingAggregator:
    """Smart building acting as a pure Soft CLS Provider via DOEs.

    Instead of complex individual HVAC/Water Heater modeling, this provides an
    aggregate structural limitation curve for the whole building block.
    """

    block_id: int
    p_baseline_trace_kw: np.ndarray  # Expected native unconstrained load trace
    base_marginal_cost: float  # Base cost ($/(kW*h)) demanded for limitation
    min_load_fraction: float = 0.70  # Minimum operational load bound (70%)
    reliability: float = 0.99  # Probability they adhere to the allocated DOE
    time_step_h: float = 5.0 / 60.0  # Native resolution of p_baseline_trace_kw
    accumulated_deficit_kwh: float = 0.0  # Tracks un-recovered thermal deficit
    discomfort_depth_alpha: float = 20.0  # Quadratic depth penalty coefficient
    discomfort_deficit_beta: float = 5.0  # Thermal-deficit penalty coefficient

    def calculate_period_cost(
        self, t: int, volume_depth_kw: float = 0.0, clearing_period_h: float = 0.25
    ) -> float:
        """Calculate the dynamic discomfort cost factor for period ``t``.

        Reflects time-of-use pricing and the scaling penalty of deeper thermal
        curtailment. The penalties are normalized relative to the building's
        baseline load to ensure scale-invariance.
        """
        hour_of_day = (t * self.time_step_h) % 24
        p_req = float(self.p_baseline_trace_kw[t])

        if p_req < 1.0:
            return self.base_marginal_cost

        # 1. Depth fraction: what % of the building's load is being curtailed?
        curtailment_fraction = volume_depth_kw / p_req

        # Quadratic penalty based on the FRACTION curtailed
        depth_penalty = self.discomfort_depth_alpha * (curtailment_fraction**2)

        # 2. State-based penalty (thermal deficit normalized by load capacity)
        projected_deficit = self.accumulated_deficit_kwh + (
            volume_depth_kw * clearing_period_h
        )

        # Normalized deficit: "equivalent hours of full blackout"
        deficit_hours = projected_deficit / p_req

        # Linear penalty on equivalent missing hours. In well-insulated
        # buildings, temperature drops slower, so discomfort accumulates slower
        state_penalty = self.discomfort_deficit_beta * deficit_hours

        base_period_cost = self.base_marginal_cost + state_penalty

        # Add 25% premium discomfort cost during evening peak (17:00 to 21:00)
        if 17.0 <= hour_of_day <= 21.0:
            base_period_cost *= 1.25

        return base_period_cost + depth_penalty

    def get_capacity_bounds(self, t: int) -> tuple[float, float]:
        """Calculate physical native load and limitation bounds at period t."""
        p_req = float(self.p_baseline_trace_kw[t])
        p_min = p_req * self.min_load_fraction

        # State-based capacity restriction. For a well-insulated building, 1 kWh
        # of deficit per kW of capacity equates to ~1 hour of HVAC off.
        # Temperature drops ~0.5 to 1.0 C per hour. Comfort bounds are usually
        # 2 C. Thus, it takes ~4-5 hours to hit the physical limit. 0.5 kW rise
        # per 1 kWh deficit translates to ~2 hours of curtailment before
        # exhaustion.
        p_min_effective = p_min + (self.accumulated_deficit_kwh * 0.5)
        p_min_effective = min(p_req, p_min_effective)

        return p_req, p_min_effective

    def generate_limitation_offers(
        self, t: int = 0, clearing_period_h: float = 0.25
    ) -> dict[str, dict]:
        """Submit an explicit physical-envelope + discomfort-price curve at t."""
        p_req, p_min = self.get_capacity_bounds(t)
        soft_capacity = max(0.0, p_req - p_min)

        if soft_capacity <= 0:
            return {}

        # Discretize the continuous thermal flexibility curve into 3 blocks
        n_blocks = 3
        block_size = soft_capacity / n_blocks
        offers = {}

        for i in range(n_blocks):
            # Calculate average depth of curtailment for this block for cost
            start_depth = i * block_size
            end_depth = (i + 1) * block_size
            mid_depth = (start_depth + end_depth) / 2.0
            p_cap = p_req - end_depth

            block_cost = self.calculate_period_cost(
                t, volume_depth_kw=mid_depth, clearing_period_h=clearing_period_h
            )

            offers[f"building_hvac_b{i+1}"] = {
                # Explicit cap-cost representation used for DSO admissibility.
                "p_ref_kw": p_req,
                "p_cap_kw": p_cap,
                "delta_p_kw": block_size,
                "cumulative_delta_p_kw": end_depth,
                "c_limit_per_kw_h": block_cost,
            }

        return offers

    def simulate_delivery(
        self,
        rng: np.random.Generator,
        allocations: dict[str, float],
        actual_load_kw: float | None = None,
        t: int = 0,
        firm_peak_t: int | None = None,
    ) -> dict[str, float]:
        """Simulate adherence to the Dynamic Operating Envelope constraint."""
        assigned_volume = sum(
            v for k, v in allocations.items() if k.startswith("building_hvac")
        )

        # 1.5 Calculate capacity bounds for the time step
        p_req, p_min = self.get_capacity_bounds(t)

        # 2. EMS calculates its absolute dynamic operating envelope (P_cap)
        if firm_peak_t is not None:
            p_req_peak, _ = self.get_capacity_bounds(firm_peak_t)
            p_cap = p_req_peak - assigned_volume
        else:
            p_cap = p_req - assigned_volume

        # 3. Native real-time physical load at time 't'. In a real environment,
        # actual_load_kw is the building's current native physical parquet load.
        native_load = actual_load_kw if actual_load_kw is not None else p_req

        # 4. Did the building successfully engage its EMS to stay under the
        # limit? (Stochastic fault)
        if rng.random() > self.reliability:
            # Complete failure to respond (breach the DOE envelope); outputs
            # unmodified native load
            return {"building_hvac": 0.0}

        # 5. True CLS Clamping: The EMS throttles consumption specifically to fit
        # under P_cap! Subject to the strict physical bound that it cannot drop
        # below P_min survival loads.
        clamped_load = max(p_min, min(native_load, p_cap))

        # 6. Translate the clamped load back to a simple grid-delta for the
        # summing engine
        physical_curtailment_volume = max(0.0, native_load - clamped_load)

        return {"building_hvac": physical_curtailment_volume}

    # --- Proportional controller parameters for thermal recovery ---
    # K_p: Proportional gain [kW / kWh_deficit]. Converts accumulated thermal
    #       deficit into additional heating power demand. With K_p=2.0, buildings
    #       saturate at max heating headroom immediately upon release, then decay
    #       exponentially (tau ~= 1/K_p = 0.5h). 95% recovery in ~3.5h for a
    #       typical 3-hour curtailment event on R2000-insulated buildings.
    #       Physical basis: dT ~= deficit / C_th, P_recovery = K_p x deficit.
    K_P_REBOUND: float = 2.0

    # Heating oversizing factor: typical heat pumps are sized 1.2-1.4x the
    # design-day load. This sets the ceiling for total building power draw
    # during recovery (p_heating_max = p_baseline x HEATING_OVERSIZE).
    HEATING_OVERSIZE: float = 1.30

    def update_state(self, curtailed_kw: float, dt_man_h: float, p_req: float) -> float:
        """Update the thermal state of the building following dispatch.

        Uses a proportional controller (P-control) to model HVAC recovery: the
        recovery power is proportional to the accumulated thermal deficit,
        bounded by the building's physical heating capacity.

        Args:
            curtailed_kw: Power curtailed in this period (0 when released).
            dt_man_h: Timestep duration in hours.
            p_req: Baseline (unconstrained) load of the building at this step.

        Returns:
            Actual rebound power drawn ABOVE p_req (kW) in this period.
        """
        # 1. Accumulate thermal deficit from curtailment
        self.accumulated_deficit_kwh += curtailed_kw * dt_man_h

        actual_rebound_kw = 0.0

        # 2. Proportional recovery when building is NOT being curtailed
        if curtailed_kw == 0 and self.accumulated_deficit_kwh > 0:
            # P-controller: recovery drive proportional to deficit magnitude
            p_drive_kw = self.K_P_REBOUND * self.accumulated_deficit_kwh

            # Physical ceiling: cannot exceed the spare heating capacity
            # (p_heating_max - p_baseline = headroom above normal operation)
            p_heating_max = p_req * self.HEATING_OVERSIZE
            p_headroom_kw = max(0.0, p_heating_max - p_req)

            # Clamp the drive signal to available headroom
            actual_rebound_kw = min(p_drive_kw, p_headroom_kw)

            # Also clamp so we don't drain more than the remaining deficit
            max_drain_kw = self.accumulated_deficit_kwh / dt_man_h
            actual_rebound_kw = min(actual_rebound_kw, max_drain_kw)

            # Drain the deficit by the recovered energy
            self.accumulated_deficit_kwh = max(
                0.0, self.accumulated_deficit_kwh - actual_rebound_kw * dt_man_h
            )

        return actual_rebound_kw


def generate_residential_portfolios(
    p_native_aggregate_kw_trace: np.ndarray,
    n_total_blocks: int = 160,
    participation_rate: float = 0.30,
    min_load_fraction: float = 0.70,
    min_cost: float = 0.0,
    max_cost: float = 0.0,
    reliability: float = 0.99,
    time_step_h: float = 5.0 / 60.0,
) -> list[BuildingAggregator]:
    """Generate a heterogeneous supply curve of residential building aggregators.

    Args:
        p_native_aggregate_kw_trace: Total native baseline load trace across the
            entire region for the full simulation season.
        n_total_blocks: Total physical feeder blocks in the regional model.
        participation_rate: Fraction of blocks actively participating.
        min_load_fraction: The absolute floor to which buildings can be
            throttled (e.g. 0.40 means providing 60% flexibility).
        min_cost: Marginal cost ($/(kW*h)) of the most flexible participant.
        max_cost: Marginal cost ($/(kW*h)) of the least flexible participant.
        reliability: Baseline stochastic reliability of the EMS systems.
        time_step_h: Native resolution of the aggregate load trace in hours.

    Returns:
        The constructed supply curve ready for DSO sweeping.
    """
    blocks = []
    participating_blocks = int(round(n_total_blocks * participation_rate))

    block_native_load_trace = p_native_aggregate_kw_trace / n_total_blocks

    for b_idx in range(participating_blocks):
        # Linearly interpolate base limit cost ladder across participants
        cost_range = max_cost - min_cost
        c_limit_base = min_cost + b_idx * (cost_range / participating_blocks)

        blocks.append(
            BuildingAggregator(
                block_id=b_idx,
                p_baseline_trace_kw=block_native_load_trace,
                base_marginal_cost=c_limit_base,
                min_load_fraction=min_load_fraction,
                reliability=reliability,
                time_step_h=time_step_h,
            )
        )

    return blocks


# ---------------------------------------------------------------------------
# DSO capacity-auction clearing and CLS dispatch (from market/dso_dispatch.py)
# ---------------------------------------------------------------------------


class DSODispatcher:
    """DSO-side CLS advanced dispatch logic.

    Implements:
      1. DSO congestion detection (probabilistic constraint check).
      2. Capacity Auction: DSO clears a pay-as-clear local capacity auction to
         procure the required flexibility volume, incorporating a safety margin
         gamma to hedge against under-delivery risk.
      3. Stochastic Asset Failure: Models the probability of EVs opting out.
      4. Baseline-free settlement support: cleared offers carry explicit
         contractual caps used later for AMI penalty checks.
    """

    def __init__(
        self,
        network: NetworkConstraintModel,
        dt_man_h: float = 5.0 / 60.0,
        epsilon: float = 0.05,
        stochastic_failure_rate: float = 0.05,
        hard_cls_price: float = 10.0,
    ) -> None:
        """Initialize the dispatcher with its network proxy and risk settings."""
        self.network = network
        self.dt_man_h = dt_man_h
        self.epsilon = epsilon
        self.failure_rate = stochastic_failure_rate
        # Hard-CLS ceiling price ($/(kW*h)): the Soft auction clears merit-order
        # offers only up to this anchor; pricier blocks are left for the
        # mandatory Hard-CLS backstop instead.
        self.hard_cls_price = hard_cls_price

        # Calculate the required over-procurement margin (gamma)
        # If 5% fail, we need to procure 1 / 0.95 = ~1.052x the requirement
        self.gamma = (
            (1.0 / (1.0 - self.failure_rate)) - 1.0 if self.failure_rate < 1.0 else 0.0
        )
        # Seeded once per dispatch runner for stable random failure testing
        self.rng = np.random.default_rng(1337)

    def detect_congestion_window(
        self,
        p_forecast_kw: np.ndarray,
        p_forecast_std_kw: np.ndarray,
        ambient_c: np.ndarray,
        staggered_block_ticks: int | None = None,
    ) -> list:
        """Detect, extend, merge, and dimension congestion windows."""
        # Evaluate expected thermal behavior
        theta_pred = self.network.thermal_model.simulate_profile(
            p_forecast_kw, ambient_c, dt_min=self.dt_man_h * 60
        )
        is_congested = theta_pred > self.network.thermal_model.theta_max

        n_steps = len(p_forecast_kw)

        # 1) Find the "original" continuous congestion windows based only on
        # thermal limit violation
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

        # 2) Extend Day-Ahead windows for post-congestion soft-landing (rebound)
        extended_windows = []
        dt_h = self.dt_man_h
        extension_ticks = int(3.0 / dt_h)  # 3 hours extension

        for w_start, w_end in raw_windows:
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
        z_score = norm.ppf(1 - self.epsilon)
        p_worst_kw = p_forecast_kw + z_score * p_forecast_std_kw

        for w_start, w_end in raw_windows:
            blocks = []
            if staggered_block_ticks is not None:
                cur_start = w_start
                while cur_start < w_end:
                    cur_end = min(w_end, cur_start + staggered_block_ticks)
                    blocks.append((cur_start, cur_end))
                    cur_start = cur_end
            else:
                blocks.append((w_start, w_end))

            for b_start, b_end in blocks:
                mask = original_congested_mask[b_start:b_end]

                if np.any(mask):
                    max_idx = b_start + int(np.argmax(p_worst_kw[b_start:b_end] * mask))
                else:
                    max_idx = b_start

                d_lo = 0.0
                d_hi = np.max(p_worst_kw[b_start:b_end])
                d_optimal = d_hi

                theta_base = self.network.thermal_model.simulate_profile(
                    p_worst_kw, ambient_c, dt_min=self.dt_man_h * 60
                )
                if np.max(theta_base) <= self.network.thermal_model.theta_max:
                    windows.append((b_start, b_end, 0.0, max_idx))
                    continue

                for _ in range(15):
                    d_mid = (d_lo + d_hi) / 2.0
                    p_test = p_worst_kw.copy()

                    mask = original_congested_mask[b_start:b_end]
                    if np.any(mask):
                        p_test[b_start:b_end] = np.where(
                            mask,
                            p_test[b_start:b_end] - d_mid,
                            p_test[b_start:b_end],
                        )
                    else:
                        p_test[b_start:b_end] -= d_mid

                    p_test = np.maximum(0, p_test)

                    theta_test = self.network.thermal_model.simulate_profile(
                        p_test, ambient_c, dt_min=self.dt_man_h * 60
                    )

                    if np.max(theta_test) <= self.network.thermal_model.theta_max:
                        d_hi = d_mid
                        d_optimal = d_mid
                    else:
                        d_lo = d_mid

                windows.append((b_start, b_end, float(d_optimal), max_idx))

        return windows

    def auction_clear_capacity(
        self,
        portfolios: list,  # list of BuildingAggregator
        d_required_kw: float,
        t_idx: int = 0,
        clearing_period_h: float = 0.25,
    ) -> dict:
        """Clear a pay-as-clear local capacity auction.

        Sorts building limitation offers by cost and clears the cheapest Soft
        CLS. If the marginal price exceeds the cost of Hard CLS, Soft CLS
        procurement stops natively.

        Returns ``{"c_mcp": float, "allocations": dict of block_id ->
        {res_name: delta_p_soft_kw}}`` plus the explicit contractual cap
        recorded at clearing. ``delta_p_soft_kw = max(0, p_ref_kw - p_cap_kw)``
        is the cleared limitation volume.
        """
        # Hard-CLS ceiling price ($/(kW*h) over the clearing interval)
        c_hard = self.hard_cls_price
        target_curtailment = d_required_kw * (1.0 + self.gamma)

        # Collect all voluntary limitation offers for the specific period
        all_offers = []
        for port in portfolios:
            port_offers = port.generate_limitation_offers(
                t_idx, clearing_period_h=clearing_period_h
            )
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

                all_offers.append(
                    {
                        "cost": offer["c_limit_per_kw_h"],
                        "volume": p_flex,
                        "p_ref_kw": p_ref,
                        "p_cap_kw": p_cap,
                        "block_id": port.block_id,
                        "res_name": res_name,
                    }
                )
        cleared_volume = 0.0
        c_mcp = 0.0
        allocations = {port.block_id: {} for port in portfolios}
        contract_caps = {port.block_id: None for port in portfolios}
        contract_refs = {port.block_id: None for port in portfolios}

        # Group offers by exact cost to implement Pro-Rata clearing for ties
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
        firm_allocations: dict | None = None,
        firm_c_mcp: float | None = None,
        firm_peak_t: int | None = None,
        firm_contract_caps: dict | None = None,
        clearing_period_h: float = 0.25,
    ) -> dict:
        """Calculate required response and execute the fallback dispatch sequence."""
        res = {
            "c_soft_price": 0.0,
            "soft_cls_kw": 0.0,
            "shortfall_kw": 0.0,
            "allocations": {},
        }

        if d_required_kw <= 0 and firm_allocations is None:
            return res

        # 1. Clear Soft CLS auction natively at period t_idx or use assigned
        # firm block contract
        if firm_allocations is not None and firm_c_mcp is not None:
            c_soft_star = firm_c_mcp
            optimal_curtailments = firm_allocations
            contract_caps = firm_contract_caps or {}
        elif firm_c_mcp is not None:
            # Profiled Block: Dynamic allocation based on current d_required_kw,
            # but locked-in block price
            auction_res = self.auction_clear_capacity(
                portfolios, d_required_kw, t_idx, clearing_period_h
            )
            c_soft_star = firm_c_mcp
            optimal_curtailments = auction_res["allocations"]
            contract_caps = auction_res.get("contract_caps", {})
        else:
            auction_res = self.auction_clear_capacity(
                portfolios, d_required_kw, t_idx, clearing_period_h
            )
            c_soft_star = auction_res["c_mcp"]
            optimal_curtailments = auction_res["allocations"]
            contract_caps = auction_res.get("contract_caps", {})

        allocation = []

        for port in portfolios:
            # Structurally retrieve optimal cleared allocations
            bids = optimal_curtailments[port.block_id]

            # ``portfolios`` is produced solely by
            # ``generate_residential_portfolios``, which returns
            # ``list[BuildingAggregator]``, so the native trace is always read
            # through ``get_capacity_bounds``. The former ``hasattr`` chain also
            # covered ``p_req_kw`` (defined nowhere) and ``resources`` (defined
            # only on the removed ``BlockFlexPortfolio``); both were unreachable,
            # and the second branch masked the fact that only this first one
            # survived the ``simulate_delivery(..., t=...)`` call below.
            expected_native_load = port.get_capacity_bounds(t_idx)[0]

            # Simulate True Physical Delivery. Rather than fake stochastic dice
            # rolls, we pass the true physical trace for the aggregated baseline
            # load organically.
            delivered = port.simulate_delivery(
                self.rng,
                bids,
                actual_load_kw=expected_native_load,
                t=t_idx,
                firm_peak_t=firm_peak_t,
            )

            # Use the explicit contractual cap recorded at clearing for AMI
            # settlement.
            p_cap_limit_kw = contract_caps.get(port.block_id)
            if p_cap_limit_kw is None and bids:
                raise RuntimeError(
                    f"Missing contractual cap for cleared portfolio {port.block_id}."
                )

            allocation.append(
                {
                    "block_id": port.block_id,
                    "bids_kw": bids,
                    "delivered_kw": delivered,
                    "expected_native_load_kw": expected_native_load,
                    "p_cap_limit_kw": p_cap_limit_kw,
                }
            )

        # Sum delivered curtailment by resource type
        total_delivered_kw = 0.0
        delivered_by_resource = {}
        for a in allocation:
            for res_name, val in a["delivered_kw"].items():
                delivered_by_resource[res_name] = (
                    delivered_by_resource.get(res_name, 0.0) + val
                )
                total_delivered_kw += val

        # Calculate Two-Stage Contributions. If the delivered Soft CLS falls
        # short of the physical requirement (d_kw), the DSO must trigger
        # deterministic Interrupted CLS (Hard shedding)
        shortfall_kw = max(0.0, d_required_kw - total_delivered_kw)
        # Effective Soft CLS covering the requirement
        soft_cls_kw = min(total_delivered_kw, d_required_kw)
        # Wasted flexibility
        over_procured_kw = max(0.0, total_delivered_kw - d_required_kw)

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

    def compute_hard_cls(
        self, unenrolled_ev_load_kw: float, shortfall_kw: float
    ) -> dict:
        """Trigger deterministic Hard CLS when Soft CLS falls short.

        Physically disconnects EV chargers in non-participating blocks.
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


# ---------------------------------------------------------------------------
# Time-domain market simulation engine (from market/engine.py)
# ---------------------------------------------------------------------------


class MarketSimulationEngine:
    """Time-Domain Simulation Engine for the two-stage CLS.

    This engine abstracts the iterative time-loop, handling probabilistic
    constraint checks at each timestep, dynamically generating the participating
    aggregators, and dispatching both Soft-CLS (voluntary) and Hard-CLS
    (mandatory).
    """

    def __init__(
        self, network: NetworkConstraintModel, dispatcher: DSODispatcher
    ) -> None:
        """Bind the engine to its network proxy and DSO dispatcher."""
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
        p_tot_kw_realized: np.ndarray | None = None,
        p_ev_kw_realized: np.ndarray | None = None,
        market_resolution_h: float = 0.5,
        non_delivery_penalty: float = 10.0,
        min_aggregator_cost: float = 3.0,
        max_aggregator_cost: float = 8.0,
        pay_full_block: bool = False,
    ) -> pd.DataFrame:
        """Execute the flexibility market simulation over the time horizon.

        Args:
            p_base_kw_mean: Mean native baseline load (heating, background) kW.
            p_base_kw_std: Standard deviation of the baseline load.
            p_ev_kw_mean: Mean unmanaged Electric Vehicle load in kW.
            p_ev_kw_std: Standard deviation of the EV load.
            t_out_trace_c: Ambient outdoor temperature trace in Celsius.
            dt_man_h: Timestep duration in hours (default 5/60 for 5-minute
                case-study traces).
            n_total_blocks: Total physical feeder blocks supplied by the node.
            participation_rate: Fraction of blocks offering voluntary thermal
                modulation (Soft CLS).
            epsilon: Probabilistic risk tolerance for thermal breaches (e.g.
                0.05 for 95% confidence).

        Returns:
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

        # 1. Detect contiguous congestion windows. The paper case partitions
        # long congestion envelopes into 2-hour profiled blocks.
        staggered_block_ticks = max(1, int(round(2.0 / dt_man_h)))
        windows = self.dispatcher.detect_congestion_window(
            p_forecast_kw=p_tot_kw_mean,
            p_forecast_std_kw=p_tot_kw_std,
            ambient_c=t_out_trace_c,
            staggered_block_ticks=staggered_block_ticks,
        )

        # 2. Persistently instantiate the building supply curve (OOP
        # Aggregators). Adding heterogeneous cost bounds ensures the clearing
        # optimization sequentially picks the cheapest participants rather than
        # defaulting to mass Pro-Rata synchronicity.
        portfolios = generate_residential_portfolios(
            p_native_aggregate_kw_trace=p_base_kw_mean,
            n_total_blocks=n_total_blocks,
            participation_rate=participation_rate,
            min_cost=min_aggregator_cost,
            max_cost=max_aggregator_cost,
            time_step_h=dt_man_h,
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

        # 2.5 FIRST STAGE (Here-and-Now): Stochastic capacity dimensioning.
        # Pre-clear firm block capacity contracts for identified congestion
        # windows. This contracts Soft-CLS before uncertainty is realized using
        # the chance-constrained target and delivery margin.
        window_contracts = {}
        for w in windows:
            start_t, end_t, max_def, peak_t = w
            if max_def > 0:
                # Clear the Day-Ahead (DA) auction for the expected max target
                auction_res = self.dispatcher.auction_clear_capacity(
                    portfolios, max_def, t_idx=peak_t
                )
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
                        s_limit_kw = self.network.thermal_model.max_load_for_temp(
                            t_out_trace_c[t]
                        )
                    actual_deficit = max(0.0, p_tot_kw_realized[t] - s_limit_kw)
                    if active_contract is not None:
                        _, max_def, _ = active_contract
                        res_targets_raw[t] = min(max_def, actual_deficit)
                    else:
                        res_targets_raw[t] = actual_deficit
                else:
                    check = self.network.probabilistic_constraint_check(
                        p_tot_kw_mean[t],
                        p_tot_kw_std[t],
                        ambient_c=t_out_trace_c[t],
                        epsilon=epsilon,
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
                        s_limit_kw = self.network.thermal_model.max_load_for_temp(
                            t_out_trace_c[t]
                        )
                    res_targets_raw[t] = max(0.0, p_tot_kw_realized[t] - s_limit_kw)
                else:
                    check = self.network.probabilistic_constraint_check(
                        p_tot_kw_mean[t],
                        p_tot_kw_std[t],
                        ambient_c=t_out_trace_c[t],
                        epsilon=epsilon,
                    )
                    res_targets_raw[t] = check["congestion_relief_kw"]

        # 3. SECOND STAGE (Real-Time Recourse): Dynamic Dispatch and Penalty
        # Activation. Sweep through time. Uncertainty (load/temp) is realized
        # dynamically per timestep.

        block_allocations = None
        block_c_mcp = None
        block_peak_t = None
        block_contract_caps = None
        block_cleared_kw = 0.0

        for t in range(n_steps):
            offer = {}  # Initialize empty offer for this timestep

            # 1. Compute attempted rebound dynamically from building thermal
            # deficit (Soft-CLS only). NOTE: Hard-CLS (EVs) produce NO electrical
            # rebound — EV chargers are constant-power devices that resume at
            # their normal baseline rate upon reconnection. The rebound estimate
            # is used ONLY for thermal margin clamping at the end of the
            # timestep, NOT for congestion deficit calculation (to avoid circular
            # feedback).

            # 2. Re-evaluate real-time physical load and deficit. Congestion is
            # evaluated against the RAW unmanaged load only. Rebound is handled
            # separately and clamped to available margin post-dispatch.
            s_limit_kw = self.network.p_limit_kw
            if self.network.thermal_model is not None:
                s_limit_kw = self.network.thermal_model.max_load_for_temp(
                    t_out_trace_c[t]
                )
            thermal_limit_kw[t] = s_limit_kw

            if p_tot_kw_realized is not None:
                current_p_tot = p_tot_kw_realized[t]
                rt_deficit = max(0.0, current_p_tot - s_limit_kw)
            else:
                current_p_tot = p_tot_kw_mean[t]
                check = self.network.probabilistic_constraint_check(
                    current_p_tot,
                    p_tot_kw_std[t],
                    ambient_c=t_out_trace_c[t],
                    epsilon=epsilon,
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
                # Both contract shapes cap dispatch the same way, so this is one
                # branch rather than two. Scheduled Profile RESERVES capacity up
                # to ``max_def`` while the Capacity Option merely permits it, but
                # in each case the DSO dispatches only the real-time physical
                # deficit, so buildings are released as soon as congestion
                # resolves rather than at contract expiry. The two arms here were
                # byte-identical and are collapsed; ``is_profiled`` still
                # separates the two designs where they genuinely differ, at the
                # re-auction cadence below and in the settlement rule.
                _, max_def, _ = active_contract
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
                        portfolios,
                        block_max_def,
                        t_idx=block_peak_t,
                        clearing_period_h=market_resolution_h,
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
                # Execute Dispatcher for specific physical period t. In profiled
                # scenarios, the active 30-minute market block is the binding
                # firm contract. Non-profiled runs keep the window-level
                # day-ahead capacity option.
                if (
                    is_profiled
                    and block_allocations is not None
                    and block_c_mcp is not None
                ):
                    firm_allocs = block_allocations
                    firm_c_mcp = block_c_mcp
                    firm_peak_t = block_peak_t
                    firm_contract_caps = block_contract_caps
                else:
                    firm_allocs = (
                        active_contract[0]["allocations"] if active_contract else None
                    )
                    firm_c_mcp = (
                        active_contract[0]["c_mcp"] if active_contract else None
                    )
                    firm_peak_t = active_contract[2] if active_contract else None
                    firm_contract_caps = (
                        active_contract[0].get("contract_caps", {})
                        if active_contract
                        else None
                    )

                offer = self.dispatcher.dispatch(
                    d_required_kw=target_deficit,
                    dt_man_h=dt_man_h,
                    portfolios=portfolios,
                    t_idx=t,
                    firm_allocations=firm_allocs,
                    firm_c_mcp=firm_c_mcp,
                    firm_peak_t=firm_peak_t,
                    firm_contract_caps=firm_contract_caps,
                    clearing_period_h=market_resolution_h,
                )

                res_d_soft_kw[t] = offer["soft_cls_kw"]
                res_prices[t] = offer["c_soft_price"]

                # Evaluate structural residual overload (Interrupted Hard-CLS).
                # Hard-CLS is ONLY activated if the raw PHYSICAL load (unmanaged
                # - soft_cls) still breaches the thermal limit. Rebound is NOT
                # included here because: (a) Rebound is clamped to available
                # thermal margin in update_state (b) Including it would cause
                # circular false-positive breaches
                actual_unmanaged_load = security_load_kw[t]
                true_physical_load = actual_unmanaged_load - offer["soft_cls_kw"]
                actual_physical_shortfall = max(0.0, true_physical_load - s_limit_kw)

                if actual_physical_shortfall > 0:
                    ev_avail = (
                        p_ev_kw_realized[t]
                        if p_ev_kw_realized is not None
                        else p_ev_kw_mean[t]
                    )
                    hard_res = self.dispatcher.compute_hard_cls(
                        unenrolled_ev_load_kw=ev_avail,
                        shortfall_kw=actual_physical_shortfall,
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
                        p_cap_limit_kw=a.get("p_cap_limit_kw"),
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
            # Building thermal recovery (rebound) must be processed every
            # timestep. Each building recovers independently when its own
            # curtailed_kw = 0. The total rebound is then clamped to the
            # available thermal margin to prevent the recovery itself from
            # breaching the transformer limit.
            alloc_dict = {}
            if offer:
                for a in offer.get("allocation", []):
                    alloc_dict[a.get("block_id")] = sum(
                        a.get("delivered_kw", {}).values()
                    )

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
            if (
                unclamped_rebound_tot > available_margin_kw
                and unclamped_rebound_tot > 0
            ):
                scale = available_margin_kw / unclamped_rebound_tot
                actual_rebound_tot = available_margin_kw
                # Return un-recovered energy back to each building's deficit
                for port in portfolios:
                    if (
                        port.block_id in building_rebounds
                        and building_rebounds[port.block_id] > 0
                    ):
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
            "managed_load_kw": (
                p_tot_kw_realized if p_tot_kw_realized is not None else p_tot_kw_mean
            )
            + res_rebound_kw
            - res_d_soft_kw
            - res_d_hard_kw,
            "security_load_kw": security_load_kw,
            "thermal_limit_kw": thermal_limit_kw,
            "managed_worst_kw": security_load_kw
            + res_rebound_kw
            - res_d_soft_kw
            - res_d_hard_kw,
            "market_settlement_cost": res_soft_payments,
            "market_penalties": res_soft_penalties,
        }

        for block_id, trace in res_allocations.items():
            res_dict[f"alloc_{block_id}"] = trace
        for block_id, trace in res_deficits.items():
            res_dict[f"deficit_{block_id}"] = trace
        for block_id, trace in res_marginal_costs.items():
            res_dict[f"marginal_cost_{block_id}"] = trace

        df_results = pd.DataFrame(res_dict)
        return df_results


# ---------------------------------------------------------------------------
# EV-scenario sweep wrapper (from flexibility/cls_market.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CLSCapacityAllocationResult:
    """Scenario-sweep output for CLS market allocation."""

    summary: dict[str, object]
    dispatch_timeseries: pd.DataFrame


def run_cls_capacity_allocation(
    *,
    baseline_mw: pd.DataFrame,
    ev_capability_mw: pd.DataFrame,
    ev_percentages: Sequence[int],
    thermal_forecast: ThermalForecast,
    n_buildings: int,
    n_feeder_blocks: int,
    participation_rate: float,
    resolution_minutes: int,
    s_rated_kva: float,
    p_limit_kw: float,
    theta_max: float,
    market_clearing_interval_h: float,
    dispatch_ev_percent: int = 40,
    reference_price_ev_percent: int = 20,
    ev_capability_reference_percent: float = 30.0,
    epsilon: float = 0.05,
    stochastic_failure_rate: float = 0.05,
    hard_cls_price: float = 10.0,
    non_delivery_penalty: float = 10.0,
    min_aggregator_cost: float = 3.0,
    max_aggregator_cost: float = 8.0,
    pay_full_block: bool = False,
) -> CLSCapacityAllocationResult:
    """Run a Soft/Hard CLS market allocation over declared EV scenarios."""
    if baseline_mw.empty or ev_capability_mw.empty:
        raise ValueError("baseline_mw and ev_capability_mw must contain traces.")
    if baseline_mw.shape != ev_capability_mw.shape:
        raise ValueError("baseline_mw and ev_capability_mw must have the same shape.")
    if dispatch_ev_percent not in ev_percentages:
        raise ValueError("dispatch_ev_percent must be one of ev_percentages.")

    p_base_kw_mean = baseline_mw.mean(axis=1).values * 1000.0
    p_base_kw_std = baseline_mw.std(axis=1).values * 1000.0
    p_base_kw_p5 = baseline_mw.quantile(0.05, axis=1).values * 1000.0
    p_base_kw_p95 = baseline_mw.quantile(0.95, axis=1).values * 1000.0

    p_ev_kw_mean = ev_capability_mw.mean(axis=1).values * 1000.0
    p_ev_kw_std = ev_capability_mw.std(axis=1).values * 1000.0

    dt_h = resolution_minutes / 60.0
    t_out_trace = np.asarray(thermal_forecast.ambient_c, dtype=float)
    thermal_model = TransformerThermalModel(
        theta_max=theta_max,
        s_rated_kva=s_rated_kva,
    )
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=p_limit_kw)
    dispatcher = DSODispatcher(
        network=network,
        dt_man_h=dt_h,
        epsilon=epsilon,
        stochastic_failure_rate=stochastic_failure_rate,
        hard_cls_price=hard_cls_price,
    )
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    p_limit_trace_kw = np.array(
        [thermal_model.max_load_for_temp(temp_c) for temp_c in t_out_trace],
        dtype=float,
    )

    summary_results: dict[str, object] = {}
    reference_clearing_price = None
    dispatch_payload: dict[str, np.ndarray] | None = None
    dispatch_df_res: pd.DataFrame | None = None

    for scenario_index, ev_pct in enumerate(ev_percentages):
        scale = _ev_scale(ev_pct, ev_capability_reference_percent)
        p_ev_kw_mean_sc = (
            p_ev_kw_mean * scale if ev_pct > 0 else np.zeros_like(p_ev_kw_mean)
        )
        p_ev_kw_std_sc = (
            p_ev_kw_std * scale if ev_pct > 0 else np.zeros_like(p_ev_kw_std)
        )
        n_evs_total = int(round(n_buildings * (float(ev_pct) / 100.0)))

        df_res = market_engine.run(
            p_base_kw_mean=p_base_kw_mean,
            p_base_kw_std=p_base_kw_std,
            p_ev_kw_mean=p_ev_kw_mean_sc,
            p_ev_kw_std=p_ev_kw_std_sc,
            t_out_trace_c=t_out_trace,
            dt_man_h=dt_h,
            n_total_blocks=n_feeder_blocks,
            participation_rate=participation_rate,
            epsilon=epsilon,
            is_profiled=True,
            market_resolution_h=market_clearing_interval_h,
            non_delivery_penalty=non_delivery_penalty,
            min_aggregator_cost=min_aggregator_cost,
            max_aggregator_cost=max_aggregator_cost,
            pay_full_block=pay_full_block,
        )

        d_soft_cls_kw = df_res["soft_cls_kw"].values
        d_contracted_kw = df_res["contracted_soft_kw"].values
        d_hard_cls_kw = df_res["hard_cls_kw"].values
        prices = df_res["clearing_price"].values
        p_tot_kw_mean_sc = df_res["p_tot_mean_kw"].values
        managed_load_kw = df_res["managed_load_kw"].values
        market_settlement_cost = df_res["market_settlement_cost"].values
        market_penalties = df_res["market_penalties"].values
        rebound_kw = (
            df_res["rebound_kw"].values
            if "rebound_kw" in df_res.columns
            else np.zeros_like(d_soft_cls_kw)
        )

        max_price = float(np.max(prices)) if np.max(prices) > 0 else 0.0
        scenario_key = scenario_label(scenario_index, ev_pct)
        summary_results[scenario_key] = {
            "n_ev": n_evs_total,
            "unmanaged_peak_mw": float(np.max(p_tot_kw_mean_sc) / 1000.0),
            "managed_peak_mw": float(np.max(managed_load_kw) / 1000.0),
            "soft_cls_mw": float(np.max(d_soft_cls_kw) / 1000.0),
            "hard_cls_mw": float(np.max(d_hard_cls_kw) / 1000.0),
            "total_soft_cls_mwh": float(np.sum(d_soft_cls_kw) * dt_h / 1000.0),
            "total_hard_cls_mwh": float(np.sum(d_hard_cls_kw) * dt_h / 1000.0),
            "total_rebound_mwh": float(np.sum(rebound_kw) * dt_h / 1000.0),
            "max_auction_clearing_price": max_price,
            "total_market_settlement_usd": float(np.sum(market_settlement_cost)),
            "total_market_penalties_usd": float(np.sum(market_penalties)),
        }

        if ev_pct == reference_price_ev_percent:
            reference_clearing_price = max_price
        if ev_pct == dispatch_ev_percent:
            dispatch_df_res = df_res
            dispatch_payload = {
                "p_ev_mean_mw": p_ev_kw_mean_sc / 1000.0,
                "p_soft_cls_mw": d_soft_cls_kw / 1000.0,
                "p_contracted_soft_cls_mw": d_contracted_kw / 1000.0,
                "p_hard_cls_mw": d_hard_cls_kw / 1000.0,
                "p_rebound_mw": rebound_kw / 1000.0,
            }
            dispatch_clearing_price = max_price

    if dispatch_payload is None or dispatch_df_res is None:
        raise ValueError("No dispatch scenario was generated.")

    summary_results["p_rated_mw"] = p_limit_kw / 1000.0
    peak_idx = int(np.argmax(dispatch_df_res["p_tot_mean_kw"].values))
    peak_label = "s4" if dispatch_ev_percent == 40 else f"s{dispatch_ev_percent}"
    summary_results.update(
        thermal_forecast_metadata(
            thermal_forecast,
            peak_idx=peak_idx,
            peak_label=peak_label,
        )
    )
    summary_results["p_limit_dynamic_mw"] = summary_results["dynamic_limit_max_mw"]
    summary_results[f"s{reference_price_ev_percent}_clearing_price"] = float(
        reference_clearing_price or 0.0
    )
    summary_results[f"s{dispatch_ev_percent}_clearing_price"] = float(
        dispatch_clearing_price
    )
    if reference_price_ev_percent == 20:
        summary_results["s2_clearing_price"] = float(reference_clearing_price or 0.0)
    if dispatch_ev_percent == 40:
        summary_results["s4_clearing_price"] = float(dispatch_clearing_price)

    t_hours = np.arange(len(baseline_mw.index)) * resolution_minutes / 60.0
    dispatch_timeseries = pd.DataFrame(
        {
            "t_hours": t_hours,
            "p_baseline_mean_mw": p_base_kw_mean / 1000.0,
            "p_baseline_p5_mw": p_base_kw_p5 / 1000.0,
            "p_baseline_p95_mw": p_base_kw_p95 / 1000.0,
            "p_ev_mean_mw": dispatch_payload["p_ev_mean_mw"],
            "p_tot_std_mw": _column_or_zeros(
                dispatch_df_res, "p_tot_std_kw", len(t_hours)
            )
            / 1000.0,
            "p_soft_cls_mw": dispatch_payload["p_soft_cls_mw"],
            "p_contracted_soft_cls_mw": dispatch_payload["p_contracted_soft_cls_mw"],
            "p_hard_cls_mw": dispatch_payload["p_hard_cls_mw"],
            "p_rebound_mw": dispatch_payload["p_rebound_mw"],
            "p_limit_trace_mw": p_limit_trace_kw / 1000.0,
            "p_security_mw": _column_or_zeros(
                dispatch_df_res, "security_load_kw", len(t_hours)
            )
            / 1000.0,
            "p_managed_worst_mw": _column_or_zeros(
                dispatch_df_res, "managed_worst_kw", len(t_hours)
            )
            / 1000.0,
        }
    )
    return CLSCapacityAllocationResult(
        summary=summary_results,
        dispatch_timeseries=dispatch_timeseries,
    )


def scenario_label(index: int, ev_percent: int) -> str:
    """Return the canonical EV scenario label used by study reports."""
    return f"S{int(index)}_{int(ev_percent)}pct"


def _ev_scale(ev_percent: int, reference_percent: float) -> float:
    return float(ev_percent) / float(reference_percent) if ev_percent > 0 else 0.0


def _column_or_zeros(frame: pd.DataFrame, column: str, length: int) -> np.ndarray:
    if column not in frame.columns:
        return np.zeros(length)
    return frame[column].values

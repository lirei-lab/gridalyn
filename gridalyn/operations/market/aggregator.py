"""
flexibility.py – Multi-resource flexibility portfolio models.

Models the aggregation of different Flexible Energy Resources (FERs)
at the block level. Instead of just EVs, aggregators manage portfolios
of EVs, water heaters, and thermostat setbacks, each with different
availability, reliability, and risk profiles.
"""

from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from scipy.stats import norm

@dataclass
class FlexResource:
    """
    Defines one type of flexible load in a residential block.
    """
    name: str               # e.g., "ev_charger", "water_heater"
    n_units: int            # number of enrolled units in this block
    p_unit_kw: float        # rated power per unit
    coincidence: float      # average fraction actively drawing power at any time (0-1)
    reliability: float      # probability of successful response when curtailed (0-1)
    max_duration_h: float   # maximum continuous curtailment duration before constraint hit
    is_binary: bool         # True = on/off only, False = continuous modulation
    marginal_cost: float = 0.50 # Voluntary cost ($/(kW*h)) demanded to accept a power limitation over time

    @property
    def total_rated_kw(self) -> float:
        return self.n_units * self.p_unit_kw

    @property
    def available_kw(self) -> float:
        """Expected available curtailment capacity."""
        return self.total_rated_kw * self.coincidence


@dataclass
class BlockFlexPortfolio:
    """
    Block-level aggregator managing multiple FlexResources.
    Submits aggregate bids to the DSO auction.
    """
    block_id: int
    resources: list[FlexResource]

    @property
    def soft_capacity_kw(self) -> float:
        """Expected available soft CLS capacity across the portfolio."""
        return sum(r.available_kw for r in self.resources)

    def generate_limitation_offers(self) -> dict[str, dict]:
        """
        Generate voluntary capacity limitation offers.
        Instead of guessing prices, the building submits its desired load (p_req),
        its absolute minimum survival load (p_min), and its capacity-duration cost of limitation.
        """
        offers = {}
        for res in self.resources:
            p_req = res.available_kw
            if p_req <= 0:
                continue
                
            # For EVs, they can technically be curtailed to 0. 
            # Submitting a heterogeneous cost adds merit-order depth.
            offers[res.name] = {
                "p_req_kw": p_req,
                "p_min_kw": 0.0,
                "p_ref_kw": p_req,
                "p_cap_kw": 0.0,
                "delta_p_kw": p_req,
                "cumulative_delta_p_kw": p_req,
                "c_limit_per_kw_h": res.marginal_cost
            }
        return offers

    def simulate_delivery(self, rng: np.random.Generator, allocations: dict[str, float], actual_load_kw: float | None = None) -> dict[str, float]:
        """
        Simulate real-time stochastic delivery for each resource.
        Returns delivered kW per resource.
        """
        delivered = {}
        for res in self.resources:
            assigned = allocations.get(res.name, 0.0)
            if assigned <= 0:
                delivered[res.name] = 0.0
                continue
                
            if actual_load_kw is not None:
                # True physical mapping: we can't curtail more than what is actually plugged in!
                # We cap structural delivery strictly at the physical parquet bound.
                delivered[res.name] = min(assigned, actual_load_kw * res.reliability)
            else:
                # Fallback to noise roll if no physical trace is provided
                success_rate = rng.beta(a=res.reliability*20, b=(1-res.reliability)*20)
                delivered[res.name] = assigned * success_rate
            
        return delivered


@dataclass
class BuildingAggregator:
    """
    Simulates a smart building acting as a pure Soft CLS Provider via DOEs.
    Instead of complex individual HVAC/Water Heater modeling, this provides
    an aggregate structural limitation curve for the whole building block inherently.
    """
    block_id: int
    p_baseline_trace_kw: np.ndarray  # Expected native unconstrained load of the building over the season
    base_marginal_cost: float        # Base cost ($/(kW*h)) demanded for power limitation over time
    min_load_fraction: float = 0.70  # Minimum operational load bound (default 70% of baseline)
    reliability: float = 0.99        # Probability they actually adhere to the allocated DOE
    time_step_h: float = 5.0 / 60.0  # Native resolution of p_baseline_trace_kw
    accumulated_deficit_kwh: float = 0.0  # Tracks un-recovered thermal energy deficit
    discomfort_depth_alpha: float = 20.0  # Quadratic depth penalty coefficient
    discomfort_deficit_beta: float = 5.0  # Thermal-deficit penalty coefficient

    def calculate_period_cost(self, t: int, volume_depth_kw: float = 0.0, clearing_period_h: float = 0.25) -> float:
        """
        Dynamically calculates the discomfort cost factor reflecting time-of-use pricing
        and the scaling penalty of deeper thermal curtailment. The penalties are normalized
        relative to the building's baseline load to ensure scale-invariance.
        """
        hour_of_day = (t * self.time_step_h) % 24
        p_req = float(self.p_baseline_trace_kw[t])
        
        if p_req < 1.0:
            return self.base_marginal_cost
            
        # 1. Depth fraction: what % of the building's load is being curtailed?
        curtailment_fraction = volume_depth_kw / p_req
        
        # Quadratic penalty based on the FRACTION curtailed
        depth_penalty = self.discomfort_depth_alpha * (curtailment_fraction ** 2)
        
        # 2. State-based penalty (thermal deficit normalized by load capacity)
        projected_deficit = self.accumulated_deficit_kwh + (volume_depth_kw * clearing_period_h)
        
        # Normalized deficit: "equivalent hours of full blackout"
        deficit_hours = projected_deficit / p_req
        
        # Linear penalty on equivalent missing hours
        # In well-insulated buildings, temperature drops slower, so discomfort accumulates slower
        state_penalty = self.discomfort_deficit_beta * deficit_hours
        
        base_period_cost = self.base_marginal_cost + state_penalty
        
        # Add 25% premium discomfort cost if during evening peak hours (17:00 to 21:00)
        if 17.0 <= hour_of_day <= 21.0:
            base_period_cost *= 1.25
            
        return base_period_cost + depth_penalty

    def get_capacity_bounds(self, t: int) -> tuple[float, float]:
        """Calculates physical native load and limitation bounds at period t."""
        p_req = float(self.p_baseline_trace_kw[t])
        p_min = p_req * self.min_load_fraction
        
        # State-based capacity restriction
        # For a well-insulated building, 1 kWh of deficit per kW of capacity equates to ~1 hour of HVAC off.
        # Temperature drops ~0.5 to 1.0 C per hour. Comfort bounds are usually 2 C.
        # Thus, it takes ~4-5 hours to hit the physical limit.
        # 0.5 kW rise per 1 kWh deficit translates to ~2 hours of maximum curtailment before exhaustion.
        p_min_effective = p_min + (self.accumulated_deficit_kwh * 0.5)
        p_min_effective = min(p_req, p_min_effective)
        
        return p_req, p_min_effective
        
    def generate_limitation_offers(self, t: int = 0, clearing_period_h: float = 0.25) -> dict[str, dict]:
        """
        Building submits an explicit curve representing its physical envelope limits
        and discomfort pricing specifically for period t.
        """
        p_req, p_min = self.get_capacity_bounds(t)
        soft_capacity = max(0.0, p_req - p_min)
        
        if soft_capacity <= 0:
            return {}
            
        # Discretize the continuous thermal flexibility curve into 3 bidding blocks
        n_blocks = 3
        block_size = soft_capacity / n_blocks
        offers = {}
        
        for i in range(n_blocks):
            # Calculate average depth of curtailment for this block to set the cost
            start_depth = i * block_size
            end_depth = (i + 1) * block_size
            mid_depth = (start_depth + end_depth) / 2.0
            p_cap = p_req - end_depth
            
            block_cost = self.calculate_period_cost(t, volume_depth_kw=mid_depth, clearing_period_h=clearing_period_h)
            
            offers[f"building_hvac_b{i+1}"] = {
                # Explicit cap-cost representation used for DSO admissibility.
                "p_ref_kw": p_req,
                "p_cap_kw": p_cap,
                "delta_p_kw": block_size,
                "cumulative_delta_p_kw": end_depth,
                # Backward-compatible fields for older portfolio consumers.
                "p_req_kw": block_size,
                "p_min_kw": 0.0,
                "c_limit_per_kw_h": block_cost
            }
            
        return offers

    def simulate_delivery(self, rng: np.random.Generator, allocations: dict[str, float], actual_load_kw: float | None = None, t: int = 0, firm_peak_t: int = None) -> dict[str, float]:
        """
        Simulate adherence to the Dynamic Operating Envelope constraint natively.
        """
        assigned_volume = sum(v for k, v in allocations.items() if k.startswith("building_hvac"))
        
        # 1.5 Calculate capacity bounds for the time step
        p_req, p_min = self.get_capacity_bounds(t)
        
        # 2. EMS calculates its absolute dynamic operating envelope (P_cap)
        if firm_peak_t is not None:
             p_req_peak, _ = self.get_capacity_bounds(firm_peak_t)
             p_cap = p_req_peak - assigned_volume
        else:
             p_cap = p_req - assigned_volume
        
        # 3. Native real-time physical load at time 't'
        # In a real environment, actual_load_kw is the building's current native physical parquet load.
        native_load = actual_load_kw if actual_load_kw is not None else p_req
        
        # 4. Did the building successfully engage its EMS to stay under the limit? (Stochastic fault)
        if rng.random() > self.reliability:
            # Complete failure to respond (breach the DOE envelope); outputs unmodified native load
            return {"building_hvac": 0.0}
            
        # 5. True CLS Clamping: The EMS throttles consumption specifically to fit under P_cap!
        # Subject to the strict physical bound that it cannot drop below P_min survival loads.
        clamped_load = max(p_min, min(native_load, p_cap))
        
        # 6. Translate the clamped load back to a simple grid-delta for the summing engine
        physical_curtailment_volume = max(0.0, native_load - clamped_load)
        
        return {"building_hvac": physical_curtailment_volume}

    # --- Proportional controller parameters for thermal recovery ---
    # K_p: Proportional gain [kW / kWh_deficit]. Converts accumulated thermal
    #       deficit into additional heating power demand. With K_p=2.0, buildings
    #       saturate at max heating headroom immediately upon release, then decay
    #       exponentially (τ ≈ 1/K_p = 0.5h). 95% recovery in ~3.5h for a
    #       typical 3-hour curtailment event on R2000-insulated buildings.
    #       Physical basis: ΔT ≈ deficit / C_th, and P_recovery = K_p × deficit.
    K_P_REBOUND: float = 2.0
    
    # Heating oversizing factor: typical heat pumps are sized 1.2–1.4× the
    # design-day load. This sets the ceiling for total building power draw
    # during recovery (p_heating_max = p_baseline × HEATING_OVERSIZE).
    HEATING_OVERSIZE: float = 1.30
    
    def update_state(self, curtailed_kw: float, dt_man_h: float, p_req: float) -> float:
        """
        Updates the thermal state of the building following dispatch.
        
        Uses a proportional controller (P-control) to model HVAC recovery:
        the recovery power is proportional to the accumulated thermal deficit,
        bounded by the building's physical heating capacity.
        
        Parameters
        ----------
        curtailed_kw : float
            Power curtailed in this period (0 when building is released).
        dt_man_h : float
            Timestep duration in hours.
        p_req : float
            Baseline (unconstrained) load of the building at this timestep.
        
        Returns
        -------
        float
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
                0.0,
                self.accumulated_deficit_kwh - actual_rebound_kw * dt_man_h
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
    time_step_h: float = 5.0 / 60.0
) -> list[BuildingAggregator]:
    """
    Factory method to generate a heterogeneous supply curve of residential building aggregators.
    
    Parameters
    ----------
    p_native_aggregate_kw_trace : np.ndarray
        Total native baseline load trace across the entire region for the full simulation season.
    n_total_blocks : int
        Total physical feeder blocks in the regional model.
    participation_rate : float
        Fraction of blocks actively participating in the flexibility market.
    min_load_fraction : float
        The absolute floor to which buildings can be throttled (e.g. 0.40 means providing 60% flexibility).
    min_cost : float
        The marginal cost ($/(kW*h)) of the most flexible/tolerant participant.
    max_cost : float
        The marginal cost ($/(kW*h)) of the least flexible/tolerant participant.
    reliability : float
        Baseline stochastic reliability of the EMS systems.
    time_step_h : float
        Native resolution of the aggregate load trace in hours.
        
    Returns
    -------
    list[BuildingAggregator]
        The constructed supply curve ready for DSO sweeping.
    """
    blocks = []
    participating_blocks = int(round(n_total_blocks * participation_rate))
    
    block_native_load_trace = p_native_aggregate_kw_trace / n_total_blocks
    
    for b_idx in range(participating_blocks):
        # Linearly interpolate base limit cost ladder across participants
        cost_range = max_cost - min_cost
        c_limit_base = min_cost + b_idx * (cost_range / participating_blocks)
        
        blocks.append(BuildingAggregator(
            block_id=b_idx,
            p_baseline_trace_kw=block_native_load_trace,
            base_marginal_cost=c_limit_base,
            min_load_fraction=min_load_fraction,
            reliability=reliability,
            time_step_h=time_step_h
        ))
        
    return blocks

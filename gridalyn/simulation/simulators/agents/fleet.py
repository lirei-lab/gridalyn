import pandas as pd
import numpy as np

from gridalyn.simulation.simulators.agents.buildings import Building

def make_buildings(n: int, seed: int = 0) -> list[Building]:
    """Construct n Building objects with reproducible diversity."""
    rngs = [np.random.default_rng(seed + i) for i in range(n)]
    return [Building(unit_id=i, rng=rngs[i]) for i in range(n)]

def simulate_buildings(
    buildings: list[Building],
    t_out_series: pd.Series,
    caps: dict[int, pd.Series] | None = None,
    burnin_hours: int = 6,
    random_seed: int | None = 4242,
) -> pd.DataFrame:
    """
    Simulate all buildings over the provided outdoor-temperature timeseries.

    Parameters
    ----------
    buildings    : list of Building objects
    t_out_series : pd.Series with 1-min temperature values (indexed by datetime)
    caps         : optional dict {unit_id: pd.Series} of power caps (kW/min)
    burnin_hours : number of hours to simulate BEFORE t=0 (warm-up, not recorded).
                   During burn-in each building reaches its own independent stochastic
                   steady-state, eliminating cold-start correlation between realizations.
                   Temperature during burn-in = first t_out value (constant).
    random_seed  : seed for reproducible ARX non-HVAC background loads.

    Returns
    -------
    dict {unit_id: pd.DataFrame}
    """
    if caps is None:
        caps = {}
        
    n_houses = len(buildings)
    
    # Pre-generate High-Fidelity Parametric ARX Appliance Backgrounds strictly using exact target frequency
    from gridalyn.simulation.simulators.agents.unmanaged_loads import ParametricArxGenerator
    gen = ParametricArxGenerator(random_seed=random_seed)
    gen.load()
    _, bg_matrix_kw = gen.generate(temp_out_series=t_out_series, n_houses=n_houses)

    # ── Burn-in: run burnin_hours × 60 steps BEFORE recording to decorrelate states
    if burnin_hours > 0:
        t_burn = float(t_out_series.iloc[0])   # use first outdoor temp for warm-up
        burnin_steps = burnin_hours * 60
        # Burn-in starts at the same local time minus burnin_hours
        start_minute = (
            t_out_series.index[0].hour * 60 + t_out_series.index[0].minute
        )
        for step_k in range(burnin_steps):
            min_of_day = (start_minute - burnin_steps + step_k) % 1440
            # For burn-in, use a cyclic background loop or simply the first hour expectation
            bg_burn_slice = bg_matrix_kw[step_k % len(bg_matrix_kw), :]
            for i, b in enumerate(buildings):
                b.step(t_out=t_burn, minute_of_day=min_of_day, p_bg_kw=bg_burn_slice[i], p_cap_kw=None)

    # ── Main simulation (recorded)
    # Calculate dt_min based on the input timeseries frequency
    if len(t_out_series) > 1:
        dt_min = (t_out_series.index[1] - t_out_series.index[0]).total_seconds() / 60.0
    else:
        dt_min = 1.0

    results = {b.unit_id: [] for b in buildings}
    for k, (ts, t_out) in enumerate(t_out_series.items()):
        minute_of_day = ts.hour * 60 + ts.minute
        bg_slice = bg_matrix_kw[k, :]
        for i, b in enumerate(buildings):
            cap = caps.get(b.unit_id)
            cap_val = float(cap.iloc[k]) if cap is not None else None
            row = b.step(
                t_out=t_out, 
                minute_of_day=minute_of_day, 
                p_bg_kw=bg_slice[i],
                p_cap_kw=cap_val, 
                dt_min=dt_min
            )
            results[b.unit_id].append(row)

    dfs = {}
    for b in buildings:
        dfs[b.unit_id] = pd.DataFrame(results[b.unit_id], index=t_out_series.index)

    return dfs

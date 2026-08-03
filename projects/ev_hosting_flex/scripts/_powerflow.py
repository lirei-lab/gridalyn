"""AC power-flow kernel for the annual validation stage.

Runs the cached pandapower twin hour by hour per scenario (24-h day profiles),
extracts the study feeder's subtree for the cold-day Monte-Carlo sampling, and
counts CSA C235 voltage / thermal violations. Pure functions over numpy/pandas;
the governed wiring (annual artifacts, scenario matrix, report) lives in
``pipeline/validate_powerflow.py``.

GUARD-02: no module-scope ``import pandapower`` — the solver import is deferred
inside the runners so cache-free unit tests of the violation helpers never pull
the heavy dependency.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    CHARGER_MIX,
    CLUSTER_MAX_RATE,
    DTYPE,
    POWER_FACTOR,
    SLACK_VM_PU,
    TRANSFORMER_KVA_LADDER,
    VOLTAGE_LIMITS_PU,
)

N_DESIGN_HOURS = 24
"""Hourly step count of the per-day validation profiles."""


def standard_kva_for_load(
    design_load_kw: float,
    *,
    power_factor: float = POWER_FACTOR,
    ladder: tuple[float, ...] = TRANSFORMER_KVA_LADDER,
) -> float:
    """Return the smallest standard kVA whose usable kW covers a design load.

    HQ-style load-matched sizing (2026-07-07): pick the smallest ladder rung
    with ``kVA × power_factor ≥ design_load_kw``; loads above the top rung take
    the top rung (a real feeder would parallel units — surfaced, not silently
    clipped, by the ``> top`` return being the ceiling).

    Args:
        design_load_kw: The transformer's design-cold aggregate load in kW.
        power_factor: Usable-power factor mapping kVA → kW.
        ladder: Ascending standard kVA sizes.

    Returns:
        The chosen standard kVA rating.
    """
    for kva in ladder:
        if kva * float(power_factor) >= float(design_load_kw):
            return float(kva)
    return float(ladder[-1])


def gini(values: np.ndarray) -> float:
    """Gini coefficient of a non-negative 1-D array (0 = perfectly uniform).

    Args:
        values: Non-negative quantities (e.g., per-transformer adoption or
            curtailment burden).

    Returns:
        Gini coefficient in [0, 1); 0.0 for a uniform or zero-sum vector.
    """
    v = np.sort(np.asarray(values, dtype=float))
    n = v.size
    total = float(v.sum())
    if n == 0 or total <= 0.0:
        return 0.0
    idx = np.arange(1, n + 1, dtype=float)
    return float((2.0 * np.sum(idx * v)) / (n * total) - (n + 1.0) / n)


def vuf(vm_a: float, vm_b: float, vm_c: float) -> float:
    """Voltage unbalance factor (%): max phase deviation from the 3-phase mean,
    over the mean. A simple, monotone unbalance proxy (0 = balanced)."""
    v = np.array([float(vm_a), float(vm_b), float(vm_c)])
    mean = float(v.mean())
    if mean <= 0.0:
        return 0.0
    return float(np.abs(v - mean).max() / mean * 100.0)


def annual_performance_metrics(
    load_kw: np.ndarray, rating_kw: float
) -> dict[str, float]:
    """Performance-state metrics of one element from its annual load series.

    Args:
        load_kw: ``(H,)`` annual load in kW.
        rating_kw: Element usable rating in kW.

    Returns:
        Dict of ``peak_utilization_pct`` (peak / rating), ``load_factor``
        (mean / peak), ``hours_over_90`` / ``hours_over_100`` (steps strictly
        above 90 % / 100 % of the rating), ``min_headroom_kw`` (rating − peak;
        negative if overloaded), and ``growth_margin_pct`` ((rating/peak − 1) ×
        100 — how much the load can grow before the peak reaches the rating;
        ``inf`` if the element carries no load).
    """
    load = np.asarray(load_kw, dtype=float)
    rating = float(rating_kw)
    peak = float(load.max())
    return {
        "peak_utilization_pct": peak / rating * 100.0,
        "load_factor": float(load.mean()) / peak if peak > 0 else 0.0,
        "hours_over_90": int(np.count_nonzero(load > 0.90 * rating)),
        "hours_over_100": int(np.count_nonzero(load > rating)),
        "min_headroom_kw": rating - peak,
        "growth_margin_pct": (rating / peak - 1.0) * 100.0 if peak > 0 else float("inf"),
    }


def flexible_share(base_at_peak: float, ev_at_peak: float) -> float:
    """EV (flexible) fraction of the coincident peak = the ceiling on the value
    of EV flexibility (it can only touch the EV part of the peak)."""
    total = float(base_at_peak) + float(ev_at_peak)
    return float(ev_at_peak) / total if total > 0.0 else 0.0


def congestion_stats(peaks_kw: np.ndarray, rating_kw: float) -> dict[str, float]:
    """Congestion frequency + peak-severity tail from a population of peaks.

    Args:
        peaks_kw: population of coincident peaks (kW) — one per
            (base realization × EV draw × cold day).
        rating_kw: element usable rating (kW).

    Returns:
        ``{"p_cong"`` (fraction of peaks over the rating), ``"peak_p50"``,
        ``"peak_p95"``, ``"peak_p99"``, ``"peak_max"}`` — the percentiles in
        PERCENT of the rating.
    """
    p = np.asarray(peaks_kw, dtype=float) / float(rating_kw) * 100.0
    if p.size == 0:
        return {"p_cong": 0.0, "peak_p50": 0.0, "peak_p95": 0.0,
                "peak_p99": 0.0, "peak_max": 0.0}
    return {
        "p_cong": float(np.count_nonzero(p > 100.0)) / p.size,
        "peak_p50": float(np.percentile(p, 50)),
        "peak_p95": float(np.percentile(p, 95)),
        "peak_p99": float(np.percentile(p, 99)),
        "peak_max": float(p.max()),
    }


def _cold_day_peaks(
    load_15min: np.ndarray, cold_mask: np.ndarray, steps_per_day: int
) -> np.ndarray:
    """Per-cold-day coincident maximum of a 15-min annual load series.

    Args:
        load_15min: ``(n_days*steps_per_day,)`` load (kW).
        cold_mask: ``(n_days,)`` boolean — the cold days to keep.
        steps_per_day: intraday step count (e.g. 96 at 15 min).

    Returns:
        ``(n_cold_days,)`` the daily coincident peak (kW) on the cold days.
    """
    n_days = int(np.asarray(cold_mask).size)
    daily = np.asarray(load_15min, dtype=float)[: n_days * steps_per_day].reshape(
        n_days, steps_per_day
    )
    return daily[np.asarray(cold_mask, dtype=bool)].max(axis=1)


def draw_clustered_adoption(
    n_homes_by_trafo: np.ndarray,
    mean_rate: float,
    dispersion: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw a per-transformer EV adoption vector at a FIXED total fleet.

    Per transformer the adoption rate is ``mean_rate`` times a unit-mean
    lognormal multiplier (``exp(sigma*z - sigma^2/2)``). The vector is then
    water-filled so that BOTH invariants hold exactly: the home-weighted mean
    equals ``mean_rate`` (the total fleet ``sum(a_t * homes_t)`` is invariant to
    ``dispersion``) AND no transformer exceeds ``CLUSTER_MAX_RATE`` — transformers
    that would exceed the cap are pinned to it and their clipped excess is
    redistributed (home-weighted) onto the not-yet-capped transformers, iterating
    to a fixed point. ``dispersion == 0`` returns a uniform vector.

    Args:
        n_homes_by_trafo: ``(T,)`` homes served by each transformer.
        mean_rate: Mean adoption (EV/home) = fixed fleet / total homes. Must be
            below ``CLUSTER_MAX_RATE`` (else the fleet cannot fit under the cap).
        dispersion: Lognormal sigma (>= 0); 0 = uniform, higher = clustered.
        rng: Seeded numpy Generator (determinism).

    Returns:
        ``(T,)`` adoption rate (EV/home) per transformer: fleet-preserving,
        non-negative, and <= ``CLUSTER_MAX_RATE`` for every transformer.
    """
    homes = np.asarray(n_homes_by_trafo, dtype=float)
    n = homes.shape[0]
    if float(dispersion) <= 0.0:
        return np.full(n, float(mean_rate), dtype=float)
    z = rng.standard_normal(n)
    a = float(mean_rate) * np.exp(float(dispersion) * z - 0.5 * float(dispersion) ** 2)
    fleet = float(mean_rate) * float(homes.sum())
    # Water-fill: repeatedly scale the not-yet-capped transformers to carry the
    # residual fleet, then pin any that crossed the cap. Terminates in <= n
    # steps (each step pins at least one more, or converges with no new caps).
    capped = np.zeros(n, dtype=bool)
    for _ in range(n + 1):
        free = ~capped
        free_fleet = float(np.sum(a[free] * homes[free]))
        residual = fleet - float(np.sum(a[capped] * homes[capped]))
        if free_fleet <= 0.0 or residual <= 0.0:
            break
        a[free] *= residual / free_fleet
        newly = free & (a > CLUSTER_MAX_RATE)
        if not newly.any():
            break
        a[newly] = CLUSTER_MAX_RATE
        capped |= newly
    return np.minimum(a, CLUSTER_MAX_RATE).astype(float)


def apply_local_curtailment(
    base_kw: np.ndarray,
    ev_kw: np.ndarray,
    rating_kw: float,
) -> tuple[np.ndarray, float]:
    """Per-transformer curtailment cap on the design day (static-rating gate).

    Sheds enough EV kW each hour to keep ``base + ev <= rating`` (never shifts
    energy — there is no overnight valley to shift into; see the value-map
    spec). The static kW rating is the governed gate, consistent with the
    firm/flex chain; the AC re-solve then measures the recovered loading.

    Args:
        base_kw: ``(H,)`` design-day hourly base at the transformer (kW).
        ev_kw: ``(H,)`` design-day hourly EV overlay at the transformer (kW).
        rating_kw: Transformer usable rating (kW); scalar, or a per-hour
            array when the rating follows the ambient.

    Returns:
        ``(served_ev_kw (H,), curtailed_kwh)``: the post-curtailment EV draw and
        the shed energy (kWh; hourly steps => kW == kWh).
    """
    base = np.asarray(base_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    headroom = np.maximum(np.asarray(rating_kw, dtype=float) - base, 0.0)
    served = np.minimum(ev, headroom)
    curtailed_kwh = float(np.sum(ev - served))
    return served, curtailed_kwh


def flex_deferral_curves(
    base_perhome_day: np.ndarray,
    ev_perhome_day: np.ndarray,
    n_homes: int,
    rating_kw: float,
    adoption_grid: np.ndarray,
) -> dict[str, np.ndarray]:
    """Per-adoption curves for one transformer size on the cold design day.

    For each adoption ``a`` in ``adoption_grid`` (EV/home): the feeder base is
    ``n_homes * base_perhome_day``; the coincident EV overlay is
    ``round(a*n_homes) * ev_perhome_day``. Returns:

    - ``peak_noflex``: coincident-peak loading (% of rating), no flexibility.
    - ``curtailed_frac``: EV-energy fraction curtailed after valley-fill shift +
      a local-curtailment backstop that holds ``base + ev <= rating``.
    - ``curtailed_kwh``: absolute daily curtailed energy (kWh) for the contract.

    A0 = first adoption where ``peak_noflex`` > 100; A1 (derived in the stage) is
    the first where ``curtailed_frac`` exceeds the tolerance OR the flex contract
    outcosts reinforcement — flexibility never physically overloads (curtailment
    always caps), so A1 is a viability bound, not a physical crossing.

    Args:
        base_perhome_day: ``(H,)`` per-home design-day base profile (kW).
        ev_perhome_day: ``(H,)`` per-EV design-day charging profile (kW).
        n_homes: Homes on this transformer size.
        rating_kw: Transformer usable rating (kW); scalar, or a per-hour
            array when the rating follows the ambient.
        adoption_grid: ``(G,)`` adoption levels (EV/home) to evaluate.

    Returns:
        ``dict`` with ``peak_noflex`` / ``curtailed_frac`` / ``curtailed_kwh``,
        each a ``(G,)`` float array aligned with ``adoption_grid``.
    """
    from projects.ev_hosting_flex.scripts._annual import valley_fill_shift

    base_day = (int(n_homes) * np.asarray(base_perhome_day, dtype=DTYPE)).astype(DTYPE)
    ev_day_unit = np.asarray(ev_perhome_day, dtype=DTYPE)
    ev_daily_kwh = float(ev_day_unit.sum())  # per-EV daily energy (hourly steps)
    charger = float(
        sum(kw * w for kw, w in CHARGER_MIX.items()) / sum(CHARGER_MIX.values())
    )
    peak_noflex, curtailed_frac, curtailed_kwh = [], [], []
    for a in np.asarray(adoption_grid, dtype=DTYPE):
        n_evs = int(round(float(a) * int(n_homes)))
        ev_day = float(n_evs) * ev_day_unit
        peak_noflex.append(float((base_day + ev_day).max()) / float(rating_kw) * 100.0)
        if n_evs <= 0 or ev_daily_kwh <= 0.0:
            curtailed_frac.append(0.0)
            curtailed_kwh.append(0.0)
            continue
        ev_energy = np.full(n_evs, ev_daily_kwh, dtype=DTYPE)
        chargers = np.full(n_evs, charger, dtype=DTYPE)
        # valley_fill_shift returns the shifted EV overlay (kW), not net load.
        shifted_ev = np.asarray(
            valley_fill_shift(base_day, ev_energy, float(rating_kw), chargers),
            dtype=DTYPE,
        )
        _served, ckwh = apply_local_curtailment(base_day, shifted_ev, float(rating_kw))
        total_ev = ev_daily_kwh * float(n_evs)
        curtailed_kwh.append(float(ckwh))
        curtailed_frac.append(float(ckwh) / total_ev if total_ev > 0.0 else 0.0)
    return {
        "peak_noflex": np.array(peak_noflex, dtype=DTYPE),
        "curtailed_frac": np.array(curtailed_frac, dtype=DTYPE),
        "curtailed_kwh": np.array(curtailed_kwh, dtype=DTYPE),
    }


def feeder_min_voltage(
    subnet: Any, p_kw_by_load: np.ndarray, *, slack_vm_pu: float,
    power_factor: float = POWER_FACTOR,
) -> float:
    """Solve one balanced AC snapshot and return the minimum LV bus voltage (pu).

    Args:
        subnet: feeder subnet (mutated: load p/q, ext_grid vm).
        p_kw_by_load: ``(n_load,)`` per-load active power (kW) for the snapshot.
        slack_vm_pu: substation LTC setpoint.
        power_factor: constant lagging PF for the Q injection.

    Returns:
        The minimum voltage (pu) over the LV buses (``vn_kv < 1.0``) — the MV /
        slack bus is excluded.
    """
    import pandapower as pp

    p_kw = np.asarray(p_kw_by_load, dtype=DTYPE)
    q_factor = float(np.tan(np.arccos(float(power_factor))))
    subnet.ext_grid["vm_pu"] = float(slack_vm_pu)
    subnet.load["p_mw"] = p_kw / 1000.0
    subnet.load["q_mvar"] = subnet.load["p_mw"] * q_factor
    pp.runpp(subnet, numba=True)
    lv_buses = subnet.bus.index[subnet.bus["vn_kv"] < 1.0]
    return float(subnet.res_bus.loc[lv_buses, "vm_pu"].min())


def network_min_voltage(
    net: Any,
    p_kw_by_load: np.ndarray,
    *,
    use_lightsim: bool = True,
    slack_vm_pu: float = SLACK_VM_PU,
    power_factor: float = POWER_FACTOR,
) -> float:
    """Solve the full sized network once and return the minimum LV bus voltage.

    The full-net analogue of :func:`feeder_min_voltage`: it keeps the whole 25 kV
    feeder + N-1 substation + LV clusters, so the recorded minimum carries the
    cumulative MV + transformer + LV drop that the isolated feeder subnet omits.

    Args:
        net: Full sized pandapower net (mutated in place: load p/q, ext_grid vm).
            Reuse the SAME object across calls so the lightsim backend stays warm.
        p_kw_by_load: ``(n_load,)`` per-load active power (kW) in ``net.load`` row
            order.
        use_lightsim: Solve with lightsim2grid when available (warm ~45 ms); on
            any failure or when ``False``, fall back to the numba solver.
        slack_vm_pu: substation LTC setpoint.
        power_factor: constant lagging PF for the Q injection.

    Returns:
        The minimum voltage (pu) over the LV buses (``vn_kv < 1.0``) — the MV /
        slack bus is excluded.
    """
    import pandapower as pp

    p_kw = np.asarray(p_kw_by_load, dtype=DTYPE)
    q_factor = float(np.tan(np.arccos(float(power_factor))))
    net.ext_grid["vm_pu"] = float(slack_vm_pu)
    net.load["p_mw"] = p_kw / 1000.0
    net.load["q_mvar"] = net.load["p_mw"] * q_factor
    solved = False
    if use_lightsim:
        try:
            pp.runpp(net, lightsim2grid=True)
            solved = True
        except Exception:  # noqa: BLE001 — any lightsim failure -> numba fallback
            solved = False
    if not solved:
        pp.runpp(net, numba=True)
    lv_buses = net.bus.index[net.bus["vn_kv"] < 1.0]
    return float(net.res_bus.loc[lv_buses, "vm_pu"].min())


def run_design_day_powerflow(
    net: Any,
    p_kw_by_load: np.ndarray,
    *,
    slack_vm_pu: float = SLACK_VM_PU,
    power_factor: float = POWER_FACTOR,
) -> dict[str, pd.DataFrame]:
    """Run 24 hourly AC power flows and return the raw result tables.

    Args:
        net: Loaded pandapower net (mutated in place: load p/q, ext_grid vm).
        p_kw_by_load: ``(n_load, 24)`` float64 per-load active power in kW.
        slack_vm_pu: Slack (substation LTC) setpoint (D: ``SLACK_VM_PU``).
        power_factor: Constant lagging power factor for the Q injection.

    Returns:
        Dict of long-format DataFrames keyed ``bus_voltage`` (hour, bus,
        vm_pu), ``line_loading`` (hour, line, loading_percent) and
        ``trafo_loading`` (hour, trafo, loading_percent).

    Raises:
        ValueError: If the profile shape does not match the net's load table.
    """
    import pandapower as pp

    p_kw = np.asarray(p_kw_by_load, dtype=DTYPE)
    if p_kw.shape != (len(net.load), N_DESIGN_HOURS):
        raise ValueError(
            f"run_design_day_powerflow received p_kw_by_load {p_kw.shape}, "
            f"expected ({len(net.load)}, {N_DESIGN_HOURS}) for this net. "
            "Remediation: build one row per net.load in hour columns."
        )

    q_factor = float(np.tan(np.arccos(float(power_factor))))
    net.ext_grid["vm_pu"] = float(slack_vm_pu)

    frames: dict[str, list[pd.DataFrame]] = {
        "bus_voltage": [],
        "line_loading": [],
        "trafo_loading": [],
    }
    for hour in range(N_DESIGN_HOURS):
        net.load["p_mw"] = p_kw[:, hour] / 1000.0
        net.load["q_mvar"] = net.load["p_mw"] * q_factor
        pp.runpp(net, numba=True)
        frames["bus_voltage"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "bus": net.res_bus.index.to_numpy(),
                    "vm_pu": net.res_bus["vm_pu"].to_numpy(dtype=DTYPE),
                }
            )
        )
        frames["line_loading"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "line": net.res_line.index.to_numpy(),
                    "loading_percent": net.res_line["loading_percent"].to_numpy(
                        dtype=DTYPE
                    ),
                }
            )
        )
        frames["trafo_loading"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "trafo": net.res_trafo.index.to_numpy(),
                    "loading_percent": net.res_trafo["loading_percent"].to_numpy(
                        dtype=DTYPE
                    ),
                }
            )
        )
    return {key: pd.concat(parts, ignore_index=True) for key, parts in frames.items()}


def extract_feeder_subnet(
    net: Any, feeder_idx: int, downstream_buses: list[int]
) -> tuple[Any, list[int], int]:
    """Extract the study feeder's subtree as a standalone pandapower net.

    Copies the feeder transformer, every LV line whose two ends live inside
    the downstream set, and the home loads into a fresh small net with an
    external grid at the transformer's MV bus. This is the Monte-Carlo AC
    workhorse: the ensemble only varies the FEEDER load, so the K×24-hour
    sampling runs on this ~10-bus net in seconds instead of ~half an hour on
    the 4000-bus twin, while the upstream boundary voltage is imposed from the
    full-net solve.

    Args:
        net: Loaded full pandapower net (read-only).
        feeder_idx: Study feeder transformer index in ``net.trafo``.
        downstream_buses: LV bus ids downstream of the feeder transformer.

    Returns:
        A tuple ``(subnet, load_bus_order, n_homes)``: the new net, the ORIGINAL
        bus id of each subnet load row (in subnet load order), and the home
        count.

    Raises:
        ValueError: If the feeder has no downstream loads to sample.
    """
    import pandapower as pp

    trafo = net.trafo.loc[feeder_idx]
    downstream = {int(b) for b in downstream_buses}

    subnet = pp.create_empty_network()
    bus_map: dict[int, int] = {}
    for old in [int(trafo.hv_bus)] + sorted(downstream):
        bus_map[old] = pp.create_bus(subnet, vn_kv=float(net.bus.loc[old, "vn_kv"]))

    pp.create_ext_grid(subnet, bus=bus_map[int(trafo.hv_bus)], vm_pu=1.0)
    pp.create_transformer_from_parameters(
        subnet,
        hv_bus=bus_map[int(trafo.hv_bus)],
        lv_bus=bus_map[int(trafo.lv_bus)],
        sn_mva=float(trafo.sn_mva),
        vn_hv_kv=float(trafo.vn_hv_kv),
        vn_lv_kv=float(trafo.vn_lv_kv),
        vk_percent=float(trafo.vk_percent),
        vkr_percent=float(trafo.vkr_percent),
        pfe_kw=float(trafo.pfe_kw),
        i0_percent=float(trafo.i0_percent),
        shift_degree=float(trafo.shift_degree),
    )
    subtree_lines = net.line[
        net.line["from_bus"].isin(downstream) & net.line["to_bus"].isin(downstream)
    ]
    for _, row in subtree_lines.iterrows():
        pp.create_line_from_parameters(
            subnet,
            from_bus=bus_map[int(row.from_bus)],
            to_bus=bus_map[int(row.to_bus)],
            length_km=float(row.length_km),
            r_ohm_per_km=float(row.r_ohm_per_km),
            x_ohm_per_km=float(row.x_ohm_per_km),
            c_nf_per_km=float(row.c_nf_per_km),
            max_i_ka=float(row.max_i_ka),
        )
    home_loads = net.load[net.load["bus"].isin(downstream)]
    if home_loads.empty:
        raise ValueError(
            f"extract_feeder_subnet found no loads downstream of transformer:"
            f"{feeder_idx}. Remediation: regenerate the topology cache so the "
            "downstream map matches the net."
        )
    load_bus_order: list[int] = []
    for _, row in home_loads.sort_index().iterrows():
        pp.create_load(subnet, bus=bus_map[int(row.bus)], p_mw=0.0)
        load_bus_order.append(int(row.bus))
    return subnet, load_bus_order, len(load_bus_order)


def run_feeder_mc(
    subnet: Any,
    agg_kw_by_variant: Mapping[str, np.ndarray],
    mv_vm_pu_hourly: np.ndarray,
    *,
    power_factor: float = POWER_FACTOR,
) -> pd.DataFrame:
    """Run the Monte-Carlo AC sampling on the feeder subnet.

    For every variant and every ensemble realization the (K, 24) AGGREGATE
    feeder profile is split equally across the home loads and solved hour by
    hour; the upstream boundary is the hourly MV voltage imposed via the
    external grid (frozen from the full-net pre-EV solve — the feeder's own
    load does not move its 25 kV bus materially).

    Args:
        subnet: Output net of :func:`extract_feeder_subnet`.
        agg_kw_by_variant: Variant name → ``(K, 24)`` aggregate kW profiles.
        mv_vm_pu_hourly: ``(24,)`` boundary voltage profile in pu.
        power_factor: Constant lagging power factor for the Q injection.

    Returns:
        A long DataFrame with one row per (variant, realization, hour):
        ``trafo_loading_percent``, ``max_line_loading_percent`` (the worst LV
        line in the feeder subtree — the line-overload channel) and
        ``min_home_vm_pu`` (the voltage-drop channel).
    """
    import pandapower as pp

    mv_vm = np.asarray(mv_vm_pu_hourly, dtype=DTYPE)
    if mv_vm.shape != (N_DESIGN_HOURS,):
        raise ValueError(
            f"run_feeder_mc received mv_vm_pu_hourly {mv_vm.shape}, expected "
            f"({N_DESIGN_HOURS},) — one boundary voltage per design-day hour."
        )
    n_homes = len(subnet.load)
    q_factor = float(np.tan(np.arccos(float(power_factor))))
    load_bus_ids = subnet.load["bus"].to_numpy()
    has_lines = len(subnet.line) > 0

    records: list[dict[str, Any]] = []
    for variant, agg_kw in agg_kw_by_variant.items():
        agg = np.asarray(agg_kw, dtype=DTYPE)
        if agg.ndim != 2 or agg.shape[1] != N_DESIGN_HOURS:
            raise ValueError(
                f"run_feeder_mc variant {variant!r} has shape {agg.shape}, "
                f"expected (K, {N_DESIGN_HOURS}) aggregate kW profiles."
            )
        for realization in range(agg.shape[0]):
            per_home_mw = agg[realization] / float(n_homes) / 1000.0
            for hour in range(N_DESIGN_HOURS):
                subnet.ext_grid["vm_pu"] = float(mv_vm[hour])
                subnet.load["p_mw"] = per_home_mw[hour]
                subnet.load["q_mvar"] = per_home_mw[hour] * q_factor
                pp.runpp(subnet, numba=True)
                records.append(
                    {
                        "variant": variant,
                        "realization": realization,
                        "hour": hour,
                        "trafo_loading_percent": float(
                            subnet.res_trafo["loading_percent"].iloc[0]
                        ),
                        "max_line_loading_percent": (
                            float(subnet.res_line["loading_percent"].max())
                            if has_lines
                            else 0.0
                        ),
                        "min_home_vm_pu": float(
                            subnet.res_bus.loc[load_bus_ids, "vm_pu"].min()
                        ),
                    }
                )
    return pd.DataFrame.from_records(records)


def _add_3ph_params_mini(net: Any, *, r0_mult: float, x0_mult: float) -> None:
    """Stamp runpp_3ph parameters onto an existing net in place: sequenced
    ext_grid, zero-sequence line params, Dyn transformers with zero-sequence."""
    for gi in net.ext_grid.index:
        net.ext_grid.at[gi, "s_sc_max_mva"] = 5000.0
        net.ext_grid.at[gi, "rx_max"] = 0.1
        net.ext_grid.at[gi, "x0x_max"] = 1.0
        net.ext_grid.at[gi, "r0x0_max"] = 0.1
    net.line["r0_ohm_per_km"] = net.line["r_ohm_per_km"] * float(r0_mult)
    net.line["x0_ohm_per_km"] = net.line["x_ohm_per_km"] * float(x0_mult)
    net.line["c0_nf_per_km"] = 0.0
    for ti in net.trafo.index:
        net.trafo.at[ti, "vector_group"] = "Dyn"
        net.trafo.at[ti, "vk0_percent"] = float(net.trafo.at[ti, "vk_percent"])
        net.trafo.at[ti, "vkr0_percent"] = float(net.trafo.at[ti, "vkr_percent"])
        net.trafo.at[ti, "mag0_percent"] = 100.0
        net.trafo.at[ti, "mag0_rx"] = 0.0
        net.trafo.at[ti, "si0_hv_partial"] = 0.9


def to_three_phase_mv(
    net: Any, *, r0_mult: float, x0_mult: float
) -> tuple[Any, dict[int, int]]:
    """Rebuild the cached twin as an MV-level 3-phase net for runpp_3ph.

    Copies the MV (25 kV) + 120 kV buses, MV line segments (with zero-sequence),
    the substation transformers (as Dyn 3-phase), and a sequenced ext_grid. The
    single-phase pole transformers are NOT added — the caller places each as a
    single-phase asymmetric_load on its MV bus.

    Args:
        net: Loaded full pandapower net (read-only).
        r0_mult: Zero-sequence resistance multiplier for MV line segments.
        x0_mult: Zero-sequence reactance multiplier for MV line segments.

    Returns:
        ``(mv_net, {pole_trafo_idx: mv_bus})`` — the 3-phase net and the map from
        each LV pole transformer to its 25 kV bus.
    """
    import pandapower as pp

    mv = pp.create_empty_network(sn_mva=1.0)
    keep = net.bus[net.bus["vn_kv"] > 1.0]
    for bi in keep.index:
        pp.create_bus(mv, vn_kv=float(net.bus.at[bi, "vn_kv"]), index=int(bi))
    eg_bus = int(net.ext_grid["bus"].iloc[0])
    pp.create_ext_grid(mv, bus=eg_bus, vm_pu=float(net.ext_grid["vm_pu"].iloc[0]))
    keep_set = set(keep.index)
    for li in net.line.index:
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        if fb in keep_set and tb in keep_set:
            pp.create_line_from_parameters(
                mv, from_bus=fb, to_bus=tb,
                length_km=float(net.line.at[li, "length_km"]),
                r_ohm_per_km=float(net.line.at[li, "r_ohm_per_km"]),
                x_ohm_per_km=float(net.line.at[li, "x_ohm_per_km"]),
                c_nf_per_km=0.0, max_i_ka=float(net.line.at[li, "max_i_ka"]),
            )
    for t in net.trafo[net.trafo["vn_lv_kv"] >= 1.0].index:
        tr = net.trafo.loc[t]
        pp.create_transformer_from_parameters(
            mv, hv_bus=int(tr.hv_bus), lv_bus=int(tr.lv_bus), sn_mva=float(tr.sn_mva),
            vn_hv_kv=float(tr.vn_hv_kv), vn_lv_kv=float(tr.vn_lv_kv),
            vk_percent=float(tr.vk_percent), vkr_percent=float(tr.vkr_percent),
            pfe_kw=float(tr.pfe_kw), i0_percent=float(tr.i0_percent), shift_degree=0,
        )
    _add_3ph_params_mini(mv, r0_mult=r0_mult, x0_mult=x0_mult)
    pole_to_mv = {
        int(t): int(net.trafo.at[t, "hv_bus"])
        for t in net.trafo[net.trafo["vn_lv_kv"] < 1.0].index
    }
    return mv, pole_to_mv


def count_violations(
    results: Mapping[str, pd.DataFrame],
    lv_bus_ids: np.ndarray,
    *,
    limits: Mapping[str, float] = VOLTAGE_LIMITS_PU,
    dynamic_k: float = 1.0,
) -> dict[str, Any]:
    """Classify a scenario's power-flow results against CSA + thermal limits.

    Voltage bands apply to LV buses only (the CSA C235 service-entrance bands
    on the 120 V base); thermal counts are network-wide. "n_*" counters count
    distinct ELEMENTS violating in at least one hour (a bus dipping low for
    three hours is one violating bus, not three). ``loading_percent`` is
    against each transformer's OWN (load-matched) nameplate; the STATIC count
    flags > 100 % (over nameplate) and the DYNAMIC count flags
    > ``100 × dynamic_k`` (over the cold-ambient IEEE C57.91 thermal limit).

    Args:
        results: Output of :func:`run_design_day_powerflow`.
        lv_bus_ids: Bus indices of the LV (240 V) level.
        limits: Voltage bands in pu (default: ``VOLTAGE_LIMITS_PU``).
        dynamic_k: Cold-ambient dynamic rating factor (1.0 disables the
            dynamic count = static).

    Returns:
        A flat dict of scenario violation metrics (floats/ints).
    """
    volt = results["bus_voltage"]
    lv = volt[volt["bus"].isin(np.asarray(lv_bus_ids))]
    lines = results["line_loading"]
    trafos = results["trafo_loading"]

    def _n_elements(frame: pd.DataFrame, key: str, mask: pd.Series) -> int:
        return int(frame.loc[mask, key].nunique())

    return {
        "min_lv_vm_pu": float(lv["vm_pu"].min()),
        "p05_lv_vm_pu": float(lv["vm_pu"].quantile(0.05)),
        "n_lv_buses_below_normal": _n_elements(
            lv, "bus", lv["vm_pu"] < float(limits["normal_low"])
        ),
        "n_lv_buses_below_extreme": _n_elements(
            lv, "bus", lv["vm_pu"] < float(limits["extreme_low"])
        ),
        "n_lv_buses_above_normal": _n_elements(
            lv, "bus", lv["vm_pu"] > float(limits["normal_high"])
        ),
        "max_line_loading_percent": float(lines["loading_percent"].max()),
        "n_lines_over_100": _n_elements(
            lines, "line", lines["loading_percent"] > 100.0
        ),
        "max_trafo_loading_percent": float(trafos["loading_percent"].max()),
        "n_trafos_over_static": _n_elements(
            trafos, "trafo", trafos["loading_percent"] > 100.0
        ),
        "n_trafos_over_dynamic": _n_elements(
            trafos, "trafo", trafos["loading_percent"] > 100.0 * float(dynamic_k)
        ),
    }

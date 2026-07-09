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
        rating_kw: Transformer usable static rating (kW).

    Returns:
        ``(served_ev_kw (H,), curtailed_kwh)``: the post-curtailment EV draw and
        the shed energy (kWh; hourly steps => kW == kWh).
    """
    base = np.asarray(base_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    headroom = np.maximum(float(rating_kw) - base, 0.0)
    served = np.minimum(ev, headroom)
    curtailed_kwh = float(np.sum(ev - served))
    return served, curtailed_kwh


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

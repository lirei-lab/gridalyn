"""AC power-flow validation of the twin before and after adding EVs (stage 7).

Two honest before/after-EV pictures on the study-B annual artifacts:

* ``network_pen_*`` — the SYSTEM picture on the design (coldest) day, with each
  of the 540 LV transformers sized to ITS OWN downstream load on the HQ
  standard kVA ladder (``standard_kva_for_load``) and each of its homes carrying
  the SDK per-home base of that transformer's home count. This replaces the
  earlier uniform-75 kVA broadcast, which left 213/540 transformers overloaded
  at design cold with ZERO EVs — an under-sizing artifact of the geographic
  KMeans clustering, not physics. Overload is reported against BOTH the static
  nameplate and the cold-ambient IEEE C57.91 dynamic rating
  (``LV_DYNAMIC_RATING_K``); the network is loaded-but-healthy before EVs and
  the uniform adoption sweep pushes it into real congestion.
* ``mc_*`` — the governed STUDY UNIT: every cold day of the year solved in AC
  on the extracted 6-home / 75 kVA feeder subtree per variant (base / firm /
  unmanaged / curtailed), recording transformer loading, the worst LV line, and
  the min home voltage. ``p_overload_ac`` = fraction of cold days whose AC peak
  loading exceeds the (conservative, static) feeder rating.

GUARD-02: no module-scope ``import pandapower`` — the net is read via pickle
and the solver import is deferred inside the kernel.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path
from typing import Any

# Pitfall 2 (SEAL-01): cap the BLAS thread pool at module top, BEFORE any import
# that pulls numpy transitively, so the power-flow chain stays deterministic.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    aggregate_to_hourly,
    design_day_base_per_home,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    N_DESIGN_HOURS,
    count_violations,
    extract_feeder_subnet,
    run_design_day_powerflow,
    run_feeder_mc,
    standard_kva_for_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    COLD_DAY_TMEAN_C,
    DTYPE,
    LV_DYNAMIC_RATING_K,
    LV_LINE_UTIL_TARGET,
    LV_LINE_VDROP_BUDGET_PU,
    NETWORK_PENETRATION_SCENARIOS,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SLACK_VM_PU,
    SUBSTATION_EMERGENCY_FACTOR,
    SUBSTATION_MVA_LADDER,
    SUBSTATION_N1_CONTINGENCY_TARGET,
    SUBSTATION_N_TRANSFORMERS,
    TRANSFORMER_KVA,
    VOLTAGE_LIMITS_PU,
)

_FEEDER_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def _load_net(cache_dir: Path) -> Any:
    """Load the cached pandapower net as an attribute-bag (GUARD-02)."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        return pickle.load(handle)


def size_network_to_load(
    net: Any,
    cache_dir: Path,
    temp_hourly: Any,
    design_day_idx: int,
    feeder_idx: int,
) -> dict[str, Any]:
    """Size the LV transformers AND secondary conductors to their design load.

    HQ-style sizing (2026-07-07): each LV transformer's downstream homes carry
    the SDK per-home design-cold base of THEIR cluster's home count; the
    transformer takes the smallest standard kVA covering that aggregate load,
    and each LV line is upsized so its design-cold current sits at
    ``LV_LINE_UTIL_TARGET`` of the (re-sized) conductor ampacity — a thicker
    conductor raises ampacity AND lowers impedance, recovering both the thermal
    margin and the LV voltage (the network verification found the SDK
    load_aware LV lines undersized for the winter peak). Mutates
    ``net.trafo.sn_mva`` and the LV ``net.line`` impedance/ampacity in place
    (physical AC). The GOVERNED study feeder transformer is pinned at
    ``TRANSFORMER_KVA``.

    Args:
        net: Loaded pandapower net (mutated in place).
        cache_dir: Topology cache directory (downstream map).
        temp_hourly: Committed annual TMY series.
        design_day_idx: Day-of-year index of the coldest design day.
        feeder_idx: Study feeder transformer index (kept at TRANSFORMER_KVA).

    Returns:
        Dict with the per-home design-day base per size, the size→bus map, the
        assigned kVA per size, and the LV-line upsizing count.
    """
    downstream_map = json.loads((cache_dir / "downstream_bus_map.json").read_text())
    homes_by_bus = net.load.groupby("bus").size()
    lv_trafos = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]

    size_by_trafo: dict[int, int] = {}
    size_by_loadbus: dict[int, int] = {}
    for idx in lv_trafos:
        downstream = [int(b) for b in downstream_map.get(f"transformer:{int(idx)}", [])]
        n = int(homes_by_bus.reindex(downstream).fillna(0).sum())
        size_by_trafo[int(idx)] = n
        for bus in downstream:
            if bus in homes_by_bus.index:
                size_by_loadbus[bus] = n

    sizes = sorted({n for n in size_by_trafo.values() if n > 0})
    base_by_size = {
        n: design_day_base_per_home(temp_hourly, n, SEED, design_day_idx)
        for n in sizes
    }
    kva_by_size = {
        n: standard_kva_for_load(float(n) * float(base_by_size[n].max()))
        for n in sizes
    }
    for idx in lv_trafos:
        n = size_by_trafo[int(idx)]
        if int(idx) == int(feeder_idx) or n == 0:
            kva = float(TRANSFORMER_KVA)
        else:
            kva = kva_by_size[n]
        net.trafo.at[idx, "sn_mva"] = kva / 1000.0

    # ── LV secondary conductors sized to design-cold current + voltage drop ─
    # Each LV line's design current follows from the homes downstream of it
    # (all on one transformer -> one cluster size). Real LV design sizes for
    # BOTH thermal ampacity AND voltage drop; the binding scale is the max.
    # A thicker conductor (scale s) raises ampacity xs and lowers impedance /s,
    # so both the thermal margin and the per-line voltage drop improve by s.
    pf = float(POWER_FACTOR)
    sinphi = float(np.sqrt(1.0 - pf * pf))
    n_lines_upsized = 0
    vn_by_bus = net.bus["vn_kv"]
    for line_idx in net.line.index:
        from_bus = int(net.line.at[line_idx, "from_bus"])
        if float(vn_by_bus.loc[from_bus]) >= 1.0:  # LV lines only
            continue
        downstream = downstream_map.get(f"line:{int(line_idx)}", [])
        down_buses = [int(b) for b in downstream if int(b) in homes_by_bus.index]
        if not down_buses:
            continue
        n_down_homes = int(homes_by_bus.reindex(down_buses).fillna(0).sum())
        cluster_size = size_by_loadbus[down_buses[0]]
        per_home_peak = float(base_by_size[cluster_size].max())
        design_load_mw = n_down_homes * per_home_peak / 1000.0
        vn_kv = float(vn_by_bus.loc[from_bus])
        design_i_ka = design_load_mw / (np.sqrt(3.0) * vn_kv * pf)
        r = float(net.line.at[line_idx, "r_ohm_per_km"])
        x = float(net.line.at[line_idx, "x_ohm_per_km"])
        length_km = float(net.line.at[line_idx, "length_km"])
        current_i_ka = float(net.line.at[line_idx, "max_i_ka"])
        thermal_scale = design_i_ka / (float(LV_LINE_UTIL_TARGET) * current_i_ka)
        vdrop_pu = (
            np.sqrt(3.0) * design_i_ka * (r * pf + x * sinphi) * length_km / vn_kv
        )
        voltage_scale = vdrop_pu / float(LV_LINE_VDROP_BUDGET_PU)
        scale = max(1.0, thermal_scale, voltage_scale)
        if scale > 1.0:
            net.line.at[line_idx, "max_i_ka"] = current_i_ka * scale
            net.line.at[line_idx, "r_ohm_per_km"] = r / scale
            net.line.at[line_idx, "x_ohm_per_km"] = x / scale
            n_lines_upsized += 1

    substation = configure_substation_n1(
        net, homes_by_bus, base_by_size, size_by_loadbus, pf
    )

    return {
        "base_by_size": base_by_size,
        "size_by_loadbus": size_by_loadbus,
        "kva_by_size": kva_by_size,
        "size_by_trafo": size_by_trafo,
        "n_lv_lines_upsized": n_lines_upsized,
        "substation": substation,
    }


def configure_substation_n1(
    net: Any,
    homes_by_bus: Any,
    base_by_size: dict[int, np.ndarray],
    size_by_loadbus: dict[int, int],
    pf: float,
) -> dict[str, Any]:
    """Reconfigure the substation into an HQ-realistic N-1 transformer bank.

    Ties the existing substation transformers' MV (25 kV) buses onto a common
    bus (a near-zero-impedance coupler — the normal closed-tie operating state),
    adds transformers until the bank has ``SUBSTATION_N_TRANSFORMERS`` units, and
    sizes every unit to the smallest ``SUBSTATION_MVA_LADDER`` rung whose usable
    MW ``× (N−1) × SUBSTATION_N1_CONTINGENCY_TARGET`` covers the total area
    design-cold load — so on a single-unit contingency the ``N−1`` remaining
    units carry the full load at ≈ the N-1 contingency-loading target (~120 %,
    well within the ``SUBSTATION_EMERGENCY_FACTOR`` capability). For N = 2 that is
    the standard HQ two-identical-parallel-unit redundant substation. Diversity
    is ~0 at design cold, so the area load is the hourly max of the summed
    per-home base of every home. Mutates the net in place.

    Returns:
        Dict with the per-unit MVA, unit count, total area load, and the N-1 firm
        capacity at the normal and emergency ratings (MW).
    """
    import pandapower as pp

    # Total area design-cold load (coincident; MV diversity ~0 at design cold).
    day_profile = np.zeros(24, dtype=DTYPE)
    for bus, size in size_by_loadbus.items():
        day_profile = day_profile + int(homes_by_bus.loc[bus]) * base_by_size[size]
    total_load_mw = float(day_profile.max()) / 1000.0
    total_load_mva = total_load_mw / float(pf)

    n = int(SUBSTATION_N_TRANSFORMERS)
    per_unit_min_mva = total_load_mva / (
        max(n - 1, 1) * float(SUBSTATION_N1_CONTINGENCY_TARGET)
    )
    mva = next(
        (m for m in SUBSTATION_MVA_LADDER if m >= per_unit_min_mva),
        SUBSTATION_MVA_LADDER[-1],
    )

    sub_idx = list(net.trafo.index[net.trafo["vn_lv_kv"] >= 1.0])
    mv_buses = [int(net.trafo.at[i, "lv_bus"]) for i in sub_idx]
    # Tie the MV LV-side buses onto a common node with closed bus-bus switches
    # (the normal closed-tie operating state) — a zero-impedance fuse, unlike a
    # near-zero line which ill-conditions the power flow.
    for other in mv_buses[1:]:
        pp.create_switch(net, bus=mv_buses[0], element=other, et="b", closed=True)
    # Add transformers (copied from the first) until the bank has N units.
    template = net.trafo.loc[sub_idx[0]]
    while len(sub_idx) < n:
        new_idx = pp.create_transformer_from_parameters(
            net,
            hv_bus=int(template.hv_bus),
            lv_bus=mv_buses[0],
            sn_mva=mva,
            vn_hv_kv=float(template.vn_hv_kv),
            vn_lv_kv=float(template.vn_lv_kv),
            vk_percent=float(template.vk_percent),
            vkr_percent=float(template.vkr_percent),
            pfe_kw=float(template.pfe_kw),
            i0_percent=float(template.i0_percent),
            shift_degree=float(template.shift_degree),
        )
        sub_idx.append(int(new_idx))
    for i in sub_idx:
        net.trafo.at[i, "sn_mva"] = mva
    # The synthetic template carries a tap-dependency flag with no lookup table;
    # the parallel N-1 bank uses fixed taps, so disable it to keep runpp clean.
    if "tap_dependency_table" in net.trafo.columns:
        net.trafo["tap_dependency_table"] = False

    usable_mw = mva * float(pf)
    return {
        "n_transformers": n,
        "mva_per_transformer": float(mva),
        "total_area_load_mw": round(total_load_mw, ROUND_DECIMALS),
        "normal_loading_percent": round(
            total_load_mw / (n * usable_mw) * 100.0, ROUND_DECIMALS
        ),
        "firm_capacity_normal_mw": round((n - 1) * usable_mw, ROUND_DECIMALS),
        "firm_capacity_emergency_mw": round(
            (n - 1) * usable_mw * float(SUBSTATION_EMERGENCY_FACTOR), ROUND_DECIMALS
        ),
    }


def build_scenario_profiles(
    net: Any, cache_dir: Path, data_dir: Path, json_dir: Path
) -> tuple[dict[str, np.ndarray], dict[str, Any], dict[str, Any]]:
    """Assemble the ``(n_load, 24)`` kW profile per scenario from the annual seam.

    Args:
        net: Loaded pandapower net (read-only here).
        cache_dir: Stage-2 topology cache directory.
        data_dir: F1 annual artifact directory.
        json_dir: Governed JSON directory (F2 firm + F3 curtailment headline).

    Returns:
        A tuple ``(profiles, meta, mc_inputs)``: scenario name → per-load
        profile matrix, a metadata dict, and the cold-day Monte-Carlo inputs
        (per-day variant aggregates + the feeder's downstream bus list).
    """
    base_annual = np.load(data_dir / "base_annual.npy").astype(DTYPE)[0]
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    tday = np.load(data_dir / "tday_mean_c.npy").astype(DTYPE)
    firm = int(
        json.loads((json_dir / "firm_hosting_annual.json").read_text())["firm_ev_count"]
    )
    flexible = int(
        json.loads((json_dir / "curtailment_hosting.json").read_text())[
            "flexible_ev_count"
        ]
    )
    n_homes = int(
        json.loads(
            (PROJECT_OUTPUTS_DIR / "reports" / "annual_mc_report.json").read_text()
        )["summary"]["n_homes"]
    )

    temp_hourly = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp_hourly)
    design_day = int(np.argmin(tday))

    feeder_sel = json.loads((cache_dir / "feeder_selection.json").read_text())
    feeder_idx = int(feeder_sel["feeder_transformer_idx"])
    downstream = json.loads((cache_dir / "downstream_bus_map.json").read_text())[
        f"transformer:{feeder_idx}"
    ]
    if not net.load["bus"].isin([int(b) for b in downstream]).any():
        raise ValueError(
            f"validate_powerflow found no loads downstream of transformer:"
            f"{feeder_idx}. Remediation: regenerate the topology cache "
            "(prepare_topology_cache.py) so feeder_selection.json matches the net."
        )

    # ── HQ-style sizing: transformers AND LV conductors matched to load ────
    sizing = size_network_to_load(
        net, cache_dir, temp_hourly, design_day, feeder_idx
    )
    base_by_size = sizing["base_by_size"]
    size_by_loadbus = sizing["size_by_loadbus"]

    # ── NETWORK family: per-size base + per-home EV overlay on the design day ─
    # Each home carries the diversified per-home base of ITS transformer's home
    # count; the EV overlay is the design-day mean per-EV profile scaled by the
    # adoption level. All local-hour-ordered (index h = local clock hour h).
    pool_hourly = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    ev_perhome_day = np.roll(
        pool_hourly[:, design_day * 24 : (design_day + 1) * 24].mean(axis=0),
        int(hod0),
    )
    load_bus = net.load["bus"].to_numpy()
    per_load_base = np.stack(
        [base_by_size[size_by_loadbus.get(int(b), n_homes)] for b in load_bus]
    ).astype(DTYPE)

    profiles: dict[str, np.ndarray] = {}
    for pen in NETWORK_PENETRATION_SCENARIOS:
        overlay = float(pen) * ev_perhome_day
        profiles[f"network_pen_{pen:.1f}"] = (per_load_base + overlay).astype(DTYPE)

    meta = {
        "feeder_transformer_idx": feeder_idx,
        "n_homes": n_homes,
        "firm_ev_count": firm,
        "flexible_ev_count": flexible,
        "design_day": design_day,
        "hod0": hod0,
        "feeder_rating_kw": round(_FEEDER_RATING_KW, ROUND_DECIMALS),
        "dynamic_rating_k": float(LV_DYNAMIC_RATING_K),
        "transformer_kva_by_size": {
            str(k): v for k, v in sorted(sizing["kva_by_size"].items())
        },
        "n_transformers_by_size": {
            str(k): int(list(sizing["size_by_trafo"].values()).count(k))
            for k in sorted(set(sizing["size_by_trafo"].values()))
            if k > 0
        },
        "lv_line_util_target": float(LV_LINE_UTIL_TARGET),
        "n_lv_lines_upsized": int(sizing["n_lv_lines_upsized"]),
        "substation": sizing["substation"],
        "basis": "HQ load-matched LV fleet + N-1 substation bank + SDK per-size base + C57.91 dynamic rating",
    }

    # ── Feeder-unit cold-day MC: the curtailment backstop runs at the GOVERNED
    # step resolution (correct energy/headroom), then the AC layer works on the
    # HOURLY aggregate (96-step PFs would ~4x a validation cost for no gate).
    backstop = simulate_curtailment(
        base_annual, pool[:flexible], np.ones(flexible, bool), _FEEDER_RATING_KW,
        res_minutes=ANNUAL_RES_MINUTES,
    )
    base_annual = aggregate_to_hourly(base_annual)
    pool = aggregate_to_hourly(pool)
    served = aggregate_to_hourly(backstop["served_ev_kw"])
    pool_flex = pool[:flexible].sum(axis=0)

    # ── Cold-day Monte-Carlo variants for the subnet sampling layer ────────
    cold_days = np.where(tday < float(COLD_DAY_TMEAN_C))[0]
    if cold_days.size == 0:
        raise ValueError(
            "validate_powerflow found no cold days (Tday < "
            f"{COLD_DAY_TMEAN_C} °C). Remediation: verify tday_mean_c.npy."
        )

    def _cold_matrix(annual: np.ndarray) -> np.ndarray:
        daily = np.asarray(annual, dtype=DTYPE)[: len(tday) * 24].reshape(-1, 24)
        return np.roll(daily[cold_days], int(hod0), axis=1)

    mc_variants = {
        "mc_base_0ev": _cold_matrix(base_annual),
        f"mc_firm_{firm}ev": _cold_matrix(base_annual + pool[:firm].sum(axis=0)),
        f"mc_unmanaged_{flexible}ev": _cold_matrix(base_annual + pool_flex),
        f"mc_curtailed_{flexible}ev": _cold_matrix(base_annual + served),
    }
    mc_inputs = {
        "variants": mc_variants,
        "downstream_buses": downstream,
        "n_cold_days": int(cold_days.size),
    }
    meta["n_cold_days"] = int(cold_days.size)
    return profiles, meta, mc_inputs


def _write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Round float columns and write a deterministic parquet artifact."""
    out = frame.copy()
    for col in out.select_dtypes("float").columns:
        out[col] = out[col].round(ROUND_DECIMALS)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return path


def _figures(
    scenario_results: dict[str, dict[str, pd.DataFrame]],
    lv_bus_ids: np.ndarray,
    meta: dict[str, Any],
    figures_dir: Path,
    mc: pd.DataFrame | None = None,
) -> list[Path]:
    """Render the before/after figures (Agg backend; PNG + PDF each)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    def _save(fig: Any, stem: str) -> None:
        for suffix in (".png", ".pdf"):
            path = figures_dir / f"{stem}{suffix}"
            fig.savefig(path, dpi=200, bbox_inches="tight")
            paths.append(path)
        plt.close(fig)

    network_names = [n for n in scenario_results if n.startswith("network_pen_")]
    dyn_k = float(meta.get("dynamic_rating_k", 1.0))

    # 1. LV voltage percentile bands per network scenario (before vs after).
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for pos, name in enumerate(network_names):
        volt = scenario_results[name]["bus_voltage"]
        lv = volt[volt["bus"].isin(lv_bus_ids)]["vm_pu"]
        q = lv.quantile([0.0, 0.05, 0.5, 0.95, 1.0]).to_numpy()
        ax.vlines(pos, q[0], q[4], color="0.7", lw=2)
        ax.vlines(pos, q[1], q[3], color="C0", lw=6, alpha=0.8)
        ax.plot(pos, q[2], "o", color="C1", zorder=5)
    for key, style in (("normal_low", "--"), ("extreme_low", ":")):
        ax.axhline(VOLTAGE_LIMITS_PU[key], color="C3", ls=style, lw=1)
    ax.set_xticks(range(len(network_names)))
    ax.set_xticklabels(
        [n.replace("network_pen_", "") + " EV/home" for n in network_names]
    )
    ax.set_ylabel("LV bus voltage (pu, design day)")
    ax.set_title("LV voltage distribution vs network-wide EV adoption")
    _save(fig, "powerflow_lv_voltage_bands")

    # 2. Per-transformer max loading distribution, pre-EV vs highest adoption,
    # with the static-nameplate and cold-ambient dynamic thresholds marked.
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for name, color in ((network_names[0], "C0"), (network_names[-1], "C3")):
        trafo = scenario_results[name]["trafo_loading"]
        per_max = trafo.groupby("trafo")["loading_percent"].max()
        ax.hist(per_max, bins=40, alpha=0.55, color=color, label=name)
    ax.axvline(100.0, color="k", ls="--", lw=1, label="static nameplate")
    ax.axvline(
        100.0 * dyn_k, color="C3", ls=":", lw=1.5, label=f"dynamic ({dyn_k:g}x, cold)"
    )
    ax.set_xlabel("Transformer max loading over the design day (%)")
    ax.set_ylabel("Transformers")
    ax.legend(fontsize=8)
    ax.set_title("Transformer loading before vs after EVs (load-matched fleet)")
    _save(fig, "powerflow_trafo_loading_hist")

    # 3. The SAMPLED feeder picture: ECDF of per-cold-day AC peak loading.
    if mc is not None and not mc.empty:
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        peaks_by_variant = mc.groupby(["variant", "realization"])[
            "trafo_loading_percent"
        ].max()
        for variant, color in zip(
            peaks_by_variant.index.get_level_values(0).unique(),
            (f"C{i}" for i in range(10)),
        ):
            peaks = np.sort(peaks_by_variant.loc[variant].to_numpy())
            ecdf = np.arange(1, len(peaks) + 1) / len(peaks)
            over = float((peaks > 100.0).mean())
            ax.step(
                peaks,
                ecdf,
                where="post",
                color=color,
                label=f"{variant} (P(overload)={over:.0%})",
            )
        ax.axvline(100.0, color="k", ls=":", lw=1.5, label="rating (100%)")
        ax.set_xlabel("Per-cold-day AC peak transformer loading (%)")
        ax.set_ylabel("ECDF over the cold days of the year")
        ax.legend(fontsize=8)
        ax.set_title("Sampled feeder overload distribution (cold days, AC)")
        _save(fig, "powerflow_feeder_mc_ecdf")

    return paths


def run_stage(*, cache_dir: Path = PROJECT_CACHE_DIR) -> dict[str, Any]:
    """Run the full AC validation stage: scenarios → artifacts → report.

    Args:
        cache_dir: Stage-2 topology cache directory (test override).

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    effective_cache = script.cache_dir if cache_dir == PROJECT_CACHE_DIR else cache_dir
    data_dir = PROJECT_OUTPUTS_DIR / "data"
    json_dir = PROJECT_OUTPUTS_DIR / "json"

    net = _load_net(effective_cache)
    lv_bus_ids = net.bus.index[net.bus["vn_kv"] < 1.0].to_numpy()
    profiles, meta, mc_inputs = build_scenario_profiles(
        net, effective_cache, data_dir, json_dir
    )

    scenario_results: dict[str, dict[str, pd.DataFrame]] = {}
    violations: dict[str, dict[str, Any]] = {}
    for name, p_kw in profiles.items():
        results = run_design_day_powerflow(net, p_kw)
        scenario_results[name] = results
        violations[name] = count_violations(
            results, lv_bus_ids, dynamic_k=float(meta["dynamic_rating_k"])
        )

    # ── Cold-day Monte-Carlo AC sampling on the extracted feeder subnet ────
    feeder_idx = int(meta["feeder_transformer_idx"])
    subnet, _, _ = extract_feeder_subnet(
        net, feeder_idx, [int(b) for b in mc_inputs["downstream_buses"]]
    )
    hv_bus = int(net.trafo.loc[feeder_idx, "hv_bus"])
    base_volt = scenario_results["network_pen_0.0"]["bus_voltage"]
    mv_vm_hourly = (
        base_volt[base_volt["bus"] == hv_bus]
        .sort_values("hour")["vm_pu"]
        .to_numpy(dtype=DTYPE)
    )
    mc = run_feeder_mc(subnet, mc_inputs["variants"], mv_vm_hourly)

    mc_peaks = mc.groupby(["variant", "realization"])["trafo_loading_percent"].max()
    mc_line_peaks = mc.groupby(["variant", "realization"])[
        "max_line_loading_percent"
    ].max()
    mc_summary: dict[str, dict[str, Any]] = {}
    for variant in mc_inputs["variants"]:
        peaks = mc_peaks.loc[variant]
        line_peaks = mc_line_peaks.loc[variant]
        min_v = (
            mc[mc["variant"] == variant]
            .groupby("realization")["min_home_vm_pu"]
            .min()
        )
        mc_summary[variant] = {
            "p_overload_ac": round(float((peaks > 100.0).mean()), ROUND_DECIMALS),
            "peak_loading_p50": round(float(peaks.quantile(0.50)), ROUND_DECIMALS),
            "peak_loading_p95": round(float(peaks.quantile(0.95)), ROUND_DECIMALS),
            "peak_loading_max": round(float(peaks.max()), ROUND_DECIMALS),
            "max_line_loading_p95": round(
                float(line_peaks.quantile(0.95)), ROUND_DECIMALS
            ),
            "max_line_loading_max": round(float(line_peaks.max()), ROUND_DECIMALS),
            "n_lines_over_100_days": int((line_peaks > 100.0).sum()),
            "min_home_vm_pu": round(float(min_v.min()), ROUND_DECIMALS),
            "n_realizations": int(len(peaks)),
        }

    long_frames = {
        key: pd.concat(
            [
                scenario_results[name][key].assign(scenario=name)
                for name in scenario_results
            ],
            ignore_index=True,
        )
        for key in ("bus_voltage", "line_loading", "trafo_loading")
    }
    artifact_paths = [
        _write_parquet(long_frames["bus_voltage"], data_dir / "powerflow_bus_voltage.parquet"),
        _write_parquet(long_frames["line_loading"], data_dir / "powerflow_line_loading.parquet"),
        _write_parquet(long_frames["trafo_loading"], data_dir / "powerflow_trafo_loading.parquet"),
        _write_parquet(mc, data_dir / "powerflow_feeder_mc.parquet"),
    ]

    violations_payload = {
        "slack_vm_pu": SLACK_VM_PU,
        "voltage_limits_pu": dict(VOLTAGE_LIMITS_PU),
        "scenarios": {
            name: {
                key: (round(val, ROUND_DECIMALS) if isinstance(val, float) else val)
                for key, val in scenario_violations.items()
            }
            for name, scenario_violations in sorted(violations.items())
        },
        "feeder_mc": mc_summary,
        **meta,
    }
    violations_path = json_dir / "powerflow_violations.json"
    violations_path.parent.mkdir(parents=True, exist_ok=True)
    violations_path.write_text(
        json.dumps(violations_payload, indent=2, sort_keys=True) + "\n"
    )
    artifact_paths.append(violations_path)

    artifact_paths.extend(
        _figures(scenario_results, lv_bus_ids, meta, script.figures_dir, mc=mc)
    )

    pre = violations["network_pen_0.0"]
    post = violations[f"network_pen_{NETWORK_PENETRATION_SCENARIOS[-1]:.1f}"]
    firm_variant = f"mc_firm_{meta['firm_ev_count']}ev"
    unmanaged_variant = f"mc_unmanaged_{meta['flexible_ev_count']}ev"
    curtailed_variant = f"mc_curtailed_{meta['flexible_ev_count']}ev"
    summary = {
        "n_scenarios": len(profiles),
        "n_powerflows": len(profiles) * N_DESIGN_HOURS,
        "n_mc_powerflows": int(len(mc)),
        "slack_vm_pu": SLACK_VM_PU,
        **{f"pre_ev_{k}": v for k, v in pre.items()},
        **{f"post_ev_{k}": v for k, v in post.items()},
        "mc_p_overload_ac_at_firm": mc_summary[firm_variant]["p_overload_ac"],
        "mc_p_overload_ac_unmanaged": mc_summary[unmanaged_variant]["p_overload_ac"],
        "mc_p_overload_ac_curtailed": mc_summary[curtailed_variant]["p_overload_ac"],
        **meta,
    }

    warnings = []
    if pre["n_trafos_over_dynamic"]:
        warnings.append(
            f"{pre['n_trafos_over_dynamic']} transformer(s) exceed the cold-ambient "
            "dynamic thermal rating BEFORE any EV even after HQ load-matched "
            "sizing — a residual under-capacity spot, surfaced not hidden."
        )
    if mc_summary[curtailed_variant]["p_overload_ac"] > 0.0:
        warnings.append(
            "AC-vs-kW rating gap: the curtailment backstop enforces the kW "
            f"rating ({round(_FEEDER_RATING_KW, 2)} kW), so backstop-held cold "
            "days land at ~"
            f"{mc_summary[curtailed_variant]['peak_loading_p95']:.0f}% AC "
            "loading (losses + reactive flow, ~3-4% of sn). The backstop still "
            "removes the overload depth (unmanaged max "
            f"{mc_summary[unmanaged_variant]['peak_loading_max']:.0f}% -> "
            f"curtailed max {mc_summary[curtailed_variant]['peak_loading_max']:.0f}%). "
            "An AC-consistent kW rating is a deliberate study decision, "
            "reported here, not silently applied."
        )
    validation = {"valid": True, "errors": [], "warnings": warnings}
    summary = {
        key: (round(val, ROUND_DECIMALS) if isinstance(val, float) else val)
        for key, val in summary.items()
    }
    return script.write_report(
        "powerflow_validation_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation=validation,
    )


def main() -> None:
    """CLI entry point for the AC power-flow validation stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir)
    summary = report.get("summary", {})
    print(
        "Validated AC power flow + report: "
        f"{summary.get('n_powerflows')} full-net + {summary.get('n_mc_powerflows')} "
        f"cold-day MC power flows | design day {summary.get('design_day')} | "
        f"network (load-matched fleet) trafos>dynamic: "
        f"pre-EV={summary.get('pre_ev_n_trafos_over_dynamic')} -> "
        f"{NETWORK_PENETRATION_SCENARIOS[-1]} EV/home="
        f"{summary.get('post_ev_n_trafos_over_dynamic')} | "
        f"feeder MC P(overload): firm={summary.get('mc_p_overload_ac_at_firm')}, "
        f"unmanaged={summary.get('mc_p_overload_ac_unmanaged')}, "
        f"curtailed={summary.get('mc_p_overload_ac_curtailed')}"
    )


if __name__ == "__main__":
    main()

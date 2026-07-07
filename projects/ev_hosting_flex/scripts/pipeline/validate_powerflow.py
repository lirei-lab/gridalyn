"""AC power-flow validation of the twin before and after adding EVs (stage 7).

F5 of the study-B annual migration: every scenario is now driven by the ANNUAL
artifacts (SDK-agent base, cold-coupled EV pool, curtailment backstop) — the
design-day inputs are gone. Two deterministic full-net families on the year's
binding peak day plus a sampled cold-day Monte-Carlo on the feeder subnet:

* ``network_pen_*`` — the "before vs after" system picture on the peak day:
  every one of the 3235 homes carries the per-home SDK base profile plus the
  cold-coupled pool overlay at a uniform adoption level.
* ``feeder_*`` — the study unit on the same day: base, the governed firm
  count, the full pool unmanaged, and the full pool under the curtailment
  backstop (the served post-contract profile).
* ``mc_*`` — the SAMPLED picture: every cold day of the year solved in AC on
  the extracted feeder subtree per variant; ``p_overload_ac`` = fraction of
  cold days whose AC peak loading exceeds 100 %.

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
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    COLD_DAY_TMEAN_C,
    DTYPE,
    NETWORK_PENETRATION_SCENARIOS,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SLACK_VM_PU,
    TRANSFORMER_KVA,
    VOLTAGE_LIMITS_PU,
)

_FEEDER_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def _load_net(cache_dir: Path) -> Any:
    """Load the cached pandapower net as an attribute-bag (GUARD-02)."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        return pickle.load(handle)


def _day_slice(annual: np.ndarray, day: int, hod0: int) -> np.ndarray:
    """Return the (24,) LOCAL-midnight-anchored slice of day ``day``.

    The annual arrays are TMY-phase-anchored (position 0 = local ``hod0``);
    rolling by ``hod0`` re-labels the axis so index h = local clock hour h
    (2026-07-07 phase fix — same day-block approximation as study-B).
    """
    block = np.asarray(annual, dtype=DTYPE)[day * 24 : (day + 1) * 24]
    return np.roll(block, int(hod0))


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

    hod0 = tmy_hour_of_day(load_annual_tmy())

    feeder_sel = json.loads((cache_dir / "feeder_selection.json").read_text())
    feeder_idx = int(feeder_sel["feeder_transformer_idx"])
    downstream = json.loads((cache_dir / "downstream_bus_map.json").read_text())[
        f"transformer:{feeder_idx}"
    ]
    feeder_load_mask = net.load["bus"].isin([int(b) for b in downstream]).to_numpy()
    n_feeder_homes = int(feeder_load_mask.sum())
    if n_feeder_homes == 0:
        raise ValueError(
            f"validate_powerflow found no loads downstream of transformer:"
            f"{feeder_idx}. Remediation: regenerate the topology cache "
            "(prepare_topology_cache.py) so feeder_selection.json matches the net."
        )

    # The curtailment backstop runs at the GOVERNED step resolution (correct
    # energy/headroom), THEN the whole AC layer works on the HOURLY aggregate:
    # 96-step power flows would ~4x a validation cost for no gate value, so the
    # AC layer is deliberately the hourly view of the 15-min governed arrays.
    backstop = simulate_curtailment(
        base_annual, pool[:flexible], np.ones(flexible, bool), _FEEDER_RATING_KW,
        res_minutes=ANNUAL_RES_MINUTES,
    )
    base_annual = aggregate_to_hourly(base_annual)
    pool = aggregate_to_hourly(pool)
    served = aggregate_to_hourly(backstop["served_ev_kw"])

    # The year's binding day: peak hour of base + the full unmanaged pool.
    pool_flex = pool[:flexible].sum(axis=0)
    peak_day = int(np.argmax(base_annual + pool_flex) // 24)

    base_day = _day_slice(base_annual, peak_day, hod0)
    per_home_base = base_day / float(n_homes)
    n_load = len(net.load)
    base_all = np.tile(per_home_base, (n_load, 1)).astype(DTYPE)

    profiles: dict[str, np.ndarray] = {}
    for pen in NETWORK_PENETRATION_SCENARIOS:
        n_evs = int(round(pen * n_homes))
        overlay_per_home = _day_slice(pool[:n_evs].sum(axis=0), peak_day, hod0) / float(
            n_homes
        )
        profiles[f"network_pen_{pen:.1f}"] = (base_all + overlay_per_home).astype(
            DTYPE
        )

    def _feeder_scenario(feeder_agg_kw: np.ndarray) -> np.ndarray:
        matrix = base_all.copy()
        matrix[feeder_load_mask, :] = feeder_agg_kw / float(n_feeder_homes)
        return matrix.astype(DTYPE)

    ev_firm_day = _day_slice(pool[:firm].sum(axis=0), peak_day, hod0)
    ev_flex_day = _day_slice(pool_flex, peak_day, hod0)
    ev_served_day = _day_slice(served, peak_day, hod0)
    profiles["feeder_base_0ev"] = _feeder_scenario(base_day)
    profiles[f"feeder_firm_{firm}ev"] = _feeder_scenario(base_day + ev_firm_day)
    profiles[f"feeder_unmanaged_{flexible}ev"] = _feeder_scenario(
        base_day + ev_flex_day
    )
    profiles[f"feeder_curtailed_{flexible}ev"] = _feeder_scenario(
        base_day + ev_served_day
    )

    meta = {
        "feeder_transformer_idx": feeder_idx,
        "n_feeder_homes": n_feeder_homes,
        "n_homes": n_homes,
        "firm_ev_count": firm,
        "flexible_ev_count": flexible,
        "peak_day": peak_day,
        "hod0": hod0,
        "feeder_rating_kw": round(_FEEDER_RATING_KW, ROUND_DECIMALS),
        "basis": "study-B annual seam (SDK base + cold-coupled pool + backstop)",
    }

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
    feeder_names = [n for n in scenario_results if n.startswith("feeder_")]

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
    ax.set_ylabel("LV bus voltage (pu, peak day)")
    ax.set_title("LV voltage distribution vs network-wide EV adoption")
    _save(fig, "powerflow_lv_voltage_bands")

    # 2. Per-transformer max loading distribution, pre-EV vs highest adoption.
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for name, color in ((network_names[0], "C0"), (network_names[-1], "C3")):
        trafo = scenario_results[name]["trafo_loading"]
        per_max = trafo.groupby("trafo")["loading_percent"].max()
        ax.hist(per_max, bins=40, alpha=0.55, color=color, label=name)
    ax.axvline(100.0, color="k", ls="--", lw=1)
    ax.set_xlabel("Transformer max loading over the peak day (%)")
    ax.set_ylabel("Transformers")
    ax.legend()
    ax.set_title("Transformer loading before vs after EVs")
    _save(fig, "powerflow_trafo_loading_hist")

    # 3. Study-feeder hourly profile on the peak day: base / firm / unmanaged /
    # curtailed vs the rating — the mechanism in one panel.
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    feeder_idx = meta["feeder_transformer_idx"]
    palette = [f"C{i}" for i in range(10)]
    for name, color in zip(feeder_names, palette):
        trafo = scenario_results[name]["trafo_loading"]
        prof = (
            trafo[trafo["trafo"] == feeder_idx]
            .sort_values("hour")["loading_percent"]
            .to_numpy()
            / 100.0
            * meta["feeder_rating_kw"]
        )
        style = "--" if "unmanaged" in name else "-"
        ax.step(
            range(N_DESIGN_HOURS), prof, style, where="mid", color=color, label=name
        )
    ax.axhline(
        meta["feeder_rating_kw"],
        color="k",
        ls=":",
        lw=1.5,
        label=f"rating {meta['feeder_rating_kw']:.2f} kW",
    )
    ax.set_xlabel(f"Peak-day hour (day {meta['peak_day']})")
    ax.set_ylabel("Feeder transformer load (kW)")
    ax.legend(fontsize=8)
    ax.set_title(f"Study feeder (trafo {feeder_idx}) before/after EVs")
    _save(fig, "powerflow_feeder_profile")

    # 4. The SAMPLED picture: ECDF of per-cold-day AC peak loading per variant.
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
        violations[name] = count_violations(results, lv_bus_ids)

    # ── Cold-day Monte-Carlo AC sampling on the extracted feeder subnet ────
    feeder_idx = int(meta["feeder_transformer_idx"])
    subnet, _, _ = extract_feeder_subnet(
        net, feeder_idx, [int(b) for b in mc_inputs["downstream_buses"]]
    )
    hv_bus = int(net.trafo.loc[feeder_idx, "hv_bus"])
    base_volt = scenario_results["feeder_base_0ev"]["bus_voltage"]
    mv_vm_hourly = (
        base_volt[base_volt["bus"] == hv_bus]
        .sort_values("hour")["vm_pu"]
        .to_numpy(dtype=DTYPE)
    )
    mc = run_feeder_mc(subnet, mc_inputs["variants"], mv_vm_hourly)

    mc_peaks = mc.groupby(["variant", "realization"])["trafo_loading_percent"].max()
    mc_summary: dict[str, dict[str, Any]] = {}
    for variant in mc_inputs["variants"]:
        peaks = mc_peaks.loc[variant]
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
    if pre["n_trafos_over_100"]:
        warnings.append(
            f"{pre['n_trafos_over_100']} transformer(s) exceed 100% loading "
            "BEFORE any EV (the oversubscribed 10-12-home tail clusters of "
            "the physical twin) — pre-existing hot spots, surfaced not hidden."
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
        f"cold-day MC power flows | peak day {summary.get('peak_day')} | "
        f"pre-EV trafos>100%={summary.get('pre_ev_n_trafos_over_100')} | "
        f"post-EV ({NETWORK_PENETRATION_SCENARIOS[-1]} EV/home) "
        f"trafos>100%={summary.get('post_ev_n_trafos_over_100')} | "
        f"MC P(overload): firm={summary.get('mc_p_overload_ac_at_firm')}, "
        f"unmanaged={summary.get('mc_p_overload_ac_unmanaged')}, "
        f"curtailed={summary.get('mc_p_overload_ac_curtailed')}"
    )


if __name__ == "__main__":
    main()

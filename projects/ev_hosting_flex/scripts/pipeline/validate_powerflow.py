"""AC power-flow validation of the twin before and after adding EVs (stage 7).

Materializes the previously stubbed ``validate_powerflow`` workflow stage: runs
the cached pandapower twin through 24 deterministic hourly AC power flows per
scenario and emits the governed bus-voltage / line-loading / transformer-loading
artifacts plus a CSA C235 + thermal violations summary.

Two scenario families share the same kernel (``_powerflow.py``):

* ``network_pen_*`` — the "before vs after" system picture: every one of the
  3235 homes carries the deterministic heating-degree design-day base plus the
  diversified coincident EV overlay at a uniform adoption level
  (``NETWORK_PENETRATION_SCENARIOS``; 0.0 is the pre-EV reference).
* ``feeder_*`` — the study unit (the governed feeder transformer) driven by the
  study's own artifacts: the day-ahead ``Q_design`` base, plus the MC EV pool's
  p50 aggregate at the governed ``firm_ev_count``, plus the deferral count
  clipped to the transformer headroom (the flexibility-mechanism envelope).

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

from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    N_DESIGN_HOURS,
    base_profile_per_home_kw,
    clip_to_headroom,
    count_violations,
    design_day_hourly_temps,
    ev_profile_per_home_kw,
    run_design_day_powerflow,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
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


def build_scenario_profiles(
    net: Any, cache_dir: Path, data_dir: Path, json_dir: Path
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Assemble the ``(n_load, 24)`` kW profile per scenario.

    Args:
        net: Loaded pandapower net (read-only here).
        cache_dir: Stage-2 topology cache directory.
        data_dir: Stage-3 data directory (``q_design.npy`` / ``ev_pool_design.npy``).
        json_dir: Governed JSON directory (firm / deferral headline counts).

    Returns:
        A tuple ``(profiles, meta)``: scenario name → per-load profile matrix,
        and a metadata dict (feeder index, counts, per-family basis notes).
    """
    n_load = len(net.load)
    temps = design_day_hourly_temps()
    base_home = base_profile_per_home_kw(temps)
    base_all = np.tile(base_home, (n_load, 1)).astype(DTYPE)

    profiles: dict[str, np.ndarray] = {}
    for pen in NETWORK_PENETRATION_SCENARIOS:
        overlay = ev_profile_per_home_kw(pen)
        profiles[f"network_pen_{pen:.1f}"] = (base_all + overlay).astype(DTYPE)

    # ── Feeder family: the governed study unit on its own artifacts ────────
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

    q_design = np.load(data_dir / "q_design.npy").astype(DTYPE)
    ev_pool = np.load(data_dir / "ev_pool_design.npy").astype(DTYPE)
    pool_p50 = np.percentile(ev_pool, 50, axis=0).astype(DTYPE)  # (n_ev+1, 24)

    firm = int(json.loads((json_dir / "firm_hosting.json").read_text())["firm_ev_count"])
    deferral = int(
        json.loads((json_dir / "nonwires_economics.json").read_text())[
            "deferral_flexible_ev_count"
        ]
    )
    ev_max = pool_p50.shape[0] - 1
    if not (0 <= firm <= ev_max and 0 <= deferral <= ev_max):
        raise ValueError(
            f"validate_powerflow needs firm={firm} and deferral={deferral} inside "
            f"the EV pool ceiling [0, {ev_max}]. Remediation: re-run stages 3-6 "
            "so the headline counts and ev_pool_design.npy agree."
        )

    def _feeder_scenario(feeder_agg_kw: np.ndarray) -> np.ndarray:
        matrix = base_all.copy()
        matrix[feeder_load_mask, :] = feeder_agg_kw / float(n_feeder_homes)
        return matrix.astype(DTYPE)

    ev_firm = pool_p50[firm]
    ev_flex = clip_to_headroom(pool_p50[deferral], q_design, _FEEDER_RATING_KW)
    profiles["feeder_base_0ev"] = _feeder_scenario(q_design)
    profiles[f"feeder_firm_{firm}ev"] = _feeder_scenario(q_design + ev_firm)
    profiles[f"feeder_flex_{deferral}ev_clipped"] = _feeder_scenario(
        q_design + ev_flex
    )

    # ── Tail scenarios: the ensemble realizations where the risk lives ─────
    # The p50 trajectories above never overload BY CONSTRUCTION of the firm
    # gate (P(overload) <= 10% means the median case is safe; the risk is in
    # the cold tail). Two REAL MC realizations make that tail visible in AC:
    # the p95-peak realization at the firm count (brushes the rating), and the
    # worst-peak realization at the deferral count WITHOUT the clip (the
    # unmanaged "after" the flexibility mechanism prevents).
    q_real = np.load(data_dir / "q_real.npy").astype(DTYPE)  # (K, 24) MC base
    tot_firm = q_real + ev_pool[:, firm, :]
    tot_unmanaged = q_real + ev_pool[:, deferral, :]
    order_firm = np.argsort(tot_firm.max(axis=1), kind="stable")
    r_p95 = int(order_firm[int(round(0.95 * (len(order_firm) - 1)))])
    r_worst = int(np.argsort(tot_unmanaged.max(axis=1), kind="stable")[-1])
    profiles[f"feeder_tail_p95_{firm}ev"] = _feeder_scenario(tot_firm[r_p95])
    profiles[f"feeder_tail_worst_{deferral}ev_unmanaged"] = _feeder_scenario(
        tot_unmanaged[r_worst]
    )

    meta = {
        "feeder_transformer_idx": feeder_idx,
        "n_feeder_homes": n_feeder_homes,
        "firm_ev_count": firm,
        "deferral_ev_count": deferral,
        "tail_p95_realization": r_p95,
        "tail_worst_realization": r_worst,
        "feeder_rating_kw": round(_FEEDER_RATING_KW, ROUND_DECIMALS),
        "design_day_mean_temp_c": round(float(temps.mean()), ROUND_DECIMALS),
        "base_peak_per_home_kw": round(float(base_home.max()), ROUND_DECIMALS),
        "network_basis": "deterministic heating-degree design day (T_BALANCE/R_THERM/BG_KW)",
        "feeder_basis": "Q_design + MC ev_pool p50 (firm) / headroom-clipped (deferral)",
    }
    return profiles, meta


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
    ax.set_ylabel("LV bus voltage (pu, all 24 h)")
    ax.set_title("LV voltage distribution vs network-wide EV adoption")
    _save(fig, "powerflow_lv_voltage_bands")

    # 2. Per-transformer max loading distribution, pre-EV vs highest adoption.
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for name, color in ((network_names[0], "C0"), (network_names[-1], "C3")):
        trafo = scenario_results[name]["trafo_loading"]
        per_max = trafo.groupby("trafo")["loading_percent"].max()
        ax.hist(per_max, bins=40, alpha=0.55, color=color, label=name)
    ax.axvline(100.0, color="k", ls="--", lw=1)
    ax.set_xlabel("Transformer max loading over the design day (%)")
    ax.set_ylabel("Transformers")
    ax.legend()
    ax.set_title("Transformer loading before vs after EVs")
    _save(fig, "powerflow_trafo_loading_hist")

    # 3. Study-feeder hourly profile: p50 family (solid) vs the MC tail
    # realizations (dashed) vs the rating — median calm, tail bites, clip cuts.
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
        style = "--" if "_tail_" in name else "-"
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
    ax.set_xlabel("Design-day hour")
    ax.set_ylabel("Feeder transformer load (kW)")
    ax.legend(fontsize=8)
    ax.set_title(f"Study feeder (trafo {feeder_idx}) before/after EVs")
    _save(fig, "powerflow_feeder_profile")

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
    profiles, meta = build_scenario_profiles(net, effective_cache, data_dir, json_dir)

    scenario_results: dict[str, dict[str, pd.DataFrame]] = {}
    violations: dict[str, dict[str, Any]] = {}
    for name, p_kw in profiles.items():
        results = run_design_day_powerflow(net, p_kw)
        scenario_results[name] = results
        violations[name] = count_violations(results, lv_bus_ids)

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
        **meta,
    }
    violations_path = json_dir / "powerflow_violations.json"
    violations_path.parent.mkdir(parents=True, exist_ok=True)
    violations_path.write_text(
        json.dumps(violations_payload, indent=2, sort_keys=True) + "\n"
    )
    artifact_paths.append(violations_path)

    artifact_paths.extend(
        _figures(scenario_results, lv_bus_ids, meta, script.figures_dir)
    )

    pre = violations["network_pen_0.0"]
    post = violations[f"network_pen_{NETWORK_PENETRATION_SCENARIOS[-1]:.1f}"]
    summary = {
        "n_scenarios": len(profiles),
        "n_powerflows": len(profiles) * N_DESIGN_HOURS,
        "slack_vm_pu": SLACK_VM_PU,
        **{f"pre_ev_{k}": v for k, v in pre.items()},
        **{f"post_ev_{k}": v for k, v in post.items()},
        **meta,
    }
    validation = {
        "valid": True,
        "errors": [],
        "warnings": (
            [
                f"{pre['n_trafos_over_100']} transformer(s) exceed 100% loading "
                "BEFORE any EV (the oversubscribed 10-12-home tail clusters of "
                "the physical twin) — pre-existing hot spots, surfaced not hidden."
            ]
            if pre["n_trafos_over_100"]
            else []
        ),
    }
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
        f"{summary.get('n_powerflows')} power flows over {summary.get('n_scenarios')} scenarios | "
        f"pre-EV min LV V={summary.get('pre_ev_min_lv_vm_pu')} pu, "
        f"trafos>100%={summary.get('pre_ev_n_trafos_over_100')} | "
        f"post-EV ({NETWORK_PENETRATION_SCENARIOS[-1]} EV/home) min LV V="
        f"{summary.get('post_ev_min_lv_vm_pu')} pu, "
        f"trafos>100%={summary.get('post_ev_n_trafos_over_100')}"
    )


if __name__ == "__main__":
    main()

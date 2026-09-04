"""Locational flexibility contracts: clear the market where the congestion is.

This is the unification of what used to be a second project. `flexibility_cls`
ran the flexibility market against a SUBSTATION constraint on a parallel network;
once both studies were put on the same Québec twin and the substation was sized
to its N-1 firm capacity, that constraint stopped binding under the rating
convention this study uses. The congestion on this network is at the POLE
transformers -- the fleet triage counts them -- so that is where a contract has
to clear to mean anything.

The mechanism itself is SDK code (`gridalyn.operations.clearing.selection`), not
project code, so this stage builds its inputs and reads its results:

    build_constraint_requirements   loading above the limit -> kW to shed, per asset
    build_provider_registry         one row per controllable EV, with its feeder
    build_network_sensitivity       which provider can relieve which constraint
    build_locational_clearing       select providers per constraint event

Soft CLS (building thermal flexibility) is deliberately absent. Measured on this
network, capping heating does not store energy -- it creates a deficit that is
repaid at the installed baseboard power, so it moves the peak rather than
reducing it. Only Hard CLS (EV curtailment) is offered here.
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    ANNUAL_RES_MINUTES,
    cold_capability_curve,
    day_mean_temps,
    feeder_rating,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import draw_clustered_adoption
from projects.ev_hosting_flex.scripts.config import (
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    CHARGER_MIX,
    COLD_DAY_TMEAN_C,
    EV_KWH_PER_YEAR,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    TRIAGE_ADOPTION_GRID,
    TRIAGE_BASE_DISPERSION,
    TRIAGE_K_BASE,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (
    _ensure_base_mc_cache,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (
    size_network_to_load,
)

_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0
_EPOCH = pd.Timestamp("2024-01-01 00:00:00")
_STEPS_PER_DAY = 24 * 60 // int(ANNUAL_RES_MINUTES)


def transformer_loading_frame(
    homes_by_trafo: dict[int, int],
    rating_by_trafo: dict[int, float],
    base_by_size: dict[int, np.ndarray],
    ev_by_trafo: dict[int, np.ndarray],
    k_curve: np.ndarray | None,
    cold_days: np.ndarray,
) -> pd.DataFrame:
    """Return per-transformer loading over the cold days.

    Only cold days are carried: a contract that never activates outside them
    would add rows the clearing has to scan and no events to clear.

    Args:
        homes_by_trafo: Transformer index -> homes served.
        rating_by_trafo: Transformer index -> nameplate usable kW.
        base_by_size: Home count -> one base realization in kW.
        ev_by_trafo: Transformer index -> aggregate EV kW on that asset.
        k_curve: Per-step capability multiplier, or None for the nameplate.
        cold_days: Day indices to keep.

    Returns:
        Long frame with ``timestamp``, ``trafo_idx``, ``loading_percent``,
        ``sn_mva`` — the columns ``build_constraint_requirements`` requires.
    """
    keep = np.concatenate(
        [np.arange(d * _STEPS_PER_DAY, (d + 1) * _STEPS_PER_DAY) for d in cold_days]
    )
    # Real timestamps, not step indices: the SDK infers the settlement interval
    # from the gap between them (``infer_dt_h``), and ``pd.to_datetime`` reads a
    # bare integer as nanoseconds since the epoch -- which silently collapses
    # dt_h to ~1e-13 h and scales every energy and cost KPI by ~1e-12.
    stamps = _EPOCH + pd.to_timedelta(keep * float(ANNUAL_RES_MINUTES), unit="m")
    rows: list[pd.DataFrame] = []
    for trafo, homes in homes_by_trafo.items():
        rating = float(rating_by_trafo[trafo])
        total = base_by_size[homes] + ev_by_trafo[trafo]
        limit = rating if k_curve is None else rating * k_curve
        # Divide BEFORE selecting: with a rating that follows the ambient the
        # peak-load step is not the peak-loading step.
        loading = (total / limit * 100.0)[keep]
        rows.append(
            pd.DataFrame(
                {
                    "timestamp": stamps,
                    "trafo_idx": int(trafo),
                    "loading_percent": loading,
                    "sn_mva": rating / float(POWER_FACTOR) / 1000.0,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def asset_registry_frame(
    homes_by_trafo: dict[int, int],
    ev_count_by_trafo: dict[int, int],
    charger_kw: float,
    scenario_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(asset_registry, connectivity)`` for the provider registry.

    One row per home. A home offers Hard CLS when it has an EV; Soft CLS is
    switched off everywhere (see the module docstring for why).

    Args:
        homes_by_trafo: Transformer index -> homes served.
        ev_count_by_trafo: Transformer index -> EVs assigned to it.
        charger_kw: Curtailable power per EV.
        scenario_id: Scenario label carried through the clearing.

    Returns:
        The asset registry and the building -> transformer connectivity.
    """
    assets: list[dict[str, Any]] = []
    conn: list[dict[str, Any]] = []
    for trafo, homes in homes_by_trafo.items():
        n_ev = int(ev_count_by_trafo[trafo])
        for h in range(homes):
            bid = f"b{trafo}_{h}"
            assets.append(
                {
                    "scenario_id": scenario_id,
                    "building_id": bid,
                    "load_id": bid,
                    "soft_cls_participant": False,
                    "hard_cls_enabled": h < n_ev,
                    "has_ev": h < n_ev,
                    # The registry builds provider_id from `ev_id`; without a
                    # distinct one every EV collapses into a single provider and
                    # any per-provider count becomes meaningless.
                    "ev_id": f"ev_{trafo}_{h}" if h < n_ev else None,
                    "max_soft_kw": 0.0,
                    "max_hard_kw": float(charger_kw) if h < n_ev else 0.0,
                }
            )
            conn.append(
                {
                    "building_id": bid,
                    "load_id": bid,
                    "load_bus_id": f"bus:{trafo}:{h}",
                    # The constraint_id the requirements carry is derived from
                    # this, so the two frames key on the same asset.
                    "lv_transformer_id": f"transformer:{trafo}",
                }
            )
    return pd.DataFrame(assets), pd.DataFrame(conn)


def clear_one_adoption(
    adoption: float,
    homes_by_trafo: dict[int, int],
    rating_by_trafo: dict[int, float],
    base_by_size: dict[int, np.ndarray],
    pool: np.ndarray,
    k_curve: np.ndarray | None,
    cold_days: np.ndarray,
    charger_kw: float,
) -> dict[str, Any]:
    """Clear locational contracts at one fleet-mean adoption level."""
    from gridalyn.operations.clearing.selection import (
        build_constraint_requirements,
        build_locational_clearing,
        build_network_sensitivity,
        build_provider_registry,
    )

    order = sorted(homes_by_trafo)
    homes_arr = np.array([homes_by_trafo[t] for t in order], dtype=float)
    rng = np.random.default_rng(int(SEED) + int(round(adoption * 1000)))
    rates = draw_clustered_adoption(
        homes_arr, float(adoption), float(TRIAGE_BASE_DISPERSION), rng
    )
    ev_count = {
        t: min(int(round(rates[i] * homes_by_trafo[t])), int(pool.shape[0]))
        for i, t in enumerate(order)
    }
    ev_kw = {t: pool[: ev_count[t]].sum(axis=0) for t in order}

    scenario = f"adoption_{adoption:.2f}"
    ts = transformer_loading_frame(
        homes_by_trafo, rating_by_trafo, base_by_size, ev_kw, k_curve, cold_days
    )
    constraint_ids = [f"transformer:{t}" for t in order]
    requirements = build_constraint_requirements(
        transformer_timeseries=ts,
        transformer_id_by_idx={int(t): f"transformer:{t}" for t in order},
        constraint_ids=constraint_ids,
        limit_percent=100.0,
    )
    assets, conn = asset_registry_frame(homes_by_trafo, ev_count, charger_kw, scenario)
    providers = build_provider_registry(assets, conn)
    impact = build_network_sensitivity(providers)
    _events, selections, summary = build_locational_clearing(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario,
        dt_h=_HOURS_PER_STEP,
        # TOPOLOGY, not the default surrogate: relief here is physical — an EV
        # can only unload the transformer it is connected to, which is what
        # `build_network_sensitivity` encodes (1.0 on its own asset, 0.0
        # elsewhere). The surrogate path expects predictions from a trained
        # model, which this study neither has nor needs.
        clearing_method="topology",
    )

    # `build_constraint_requirements` emits a row per (asset, step) with
    # required_kw = 0 where nothing is over the limit, so counting the frame
    # measures its SIZE, not the congestion. Only the active rows are events.
    active = requirements.loc[requirements["required_kw"].astype(float) > 0.0]
    n_ev_total = int(sum(ev_count.values()))
    frames = {"events": _events, "selections": selections, "providers": providers}
    served_kw = float(selections["selected_kw"].sum()) if len(selections) else 0.0
    curtailed_kwh = served_kw * _HOURS_PER_STEP
    requested_kwh = n_ev_total * float(EV_KWH_PER_YEAR)
    return {
        "adoption_ev_per_home": float(adoption),
        "n_evs": n_ev_total,
        "n_constrained_assets": int(active["constraint_id"].nunique()),
        "n_constraint_events": int(len(active)),
        "required_kw_total": round(float(active["required_kw"].sum()), ROUND_DECIMALS),
        "n_providers_selected": (
            int(selections["provider_id"].nunique()) if len(selections) else 0
        ),
        "curtailed_kwh": round(curtailed_kwh, ROUND_DECIMALS),
        "curtailed_fraction": round(
            curtailed_kwh / requested_kwh if requested_kwh > 0 else 0.0, ROUND_DECIMALS
        ),
        "contract_cost_usd_per_year": round(
            float(C_AVAIL_EV_YR) * n_ev_total + curtailed_kwh * float(C_A_CURTAIL),
            2,
        ),
        "clearing_summary": {
            k: v for k, v in summary.items() if isinstance(v, (int, float, str, bool))
        },
        "_frames": frames,
        "_summary": summary,
        "_scenario_id": scenario,
    }


def _persist_operational(
    result: dict[str, Any], script: ProjectScript
) -> dict[str, Path]:
    """Write the clearing into the twin, then materialise operational artifacts.

    The saturation case is the one persisted: it is the design point where the
    contracts actually clear, so the operational view shows a populated market
    rather than an empty one.

    Args:
        result: One entry from ``clear_one_adoption`` (carries the frames).

    Returns:
        Mapping of artifact name to the path written.
    """
    from gridalyn.operations.artifacts import (
        materialize_flexibility_operation_artifacts,
    )
    from gridalyn.operations.clearing.selection import write_locational_clearing_outputs

    frames = result.pop("_frames")
    summary = result.pop("_summary")
    scenario_id = result.pop("_scenario_id")

    # Project-local, deliberately: `ArtifactLayout(root).flexibility` is a single
    # workspace-wide directory, so two studies clearing into it overwrite each
    # other's artifacts. The writers were never the constraint -- both take an
    # explicit directory -- so each study keeps its clearing under its own
    # outputs and the twin stays whatever the twin stage put there.
    flex_dir = PROJECT_OUTPUTS_DIR / "flexibility"
    flex_dir.mkdir(parents=True, exist_ok=True)
    written = write_locational_clearing_outputs(
        out_dir=flex_dir,
        events=frames["events"],
        selections=frames["selections"],
        report=summary,
    )
    registry_path = flex_dir / "provider_registry.parquet"
    frames["providers"].to_parquet(registry_path, index=False)
    written["provider_registry"] = registry_path

    written.update(
        materialize_flexibility_operation_artifacts(
            # base_dir, not root. This function takes the WORKSPACE root -- it
            # builds `root / "projects" / <id> / "outputs"` and reads the twin's
            # base metadata through ArtifactLayout(root) to resolve the model
            # version id. `script.root` is the PROJECT directory, so passing it
            # pointed ArtifactLayout at a path that does not exist, the model
            # version resolved to None, and write_operation_run rejected the
            # empty governance field.
            #
            # It was `root=ROOT` (the workspace) until the 2026-08-17
            # boilerplate migration swapped in script.root. Nothing caught it
            # for seventeen days because this is the only caller and it runs
            # only in a full flagship run.
            root=script.base_dir,
            project_id="ev_hosting_flex",
            scenario_id=scenario_id,
            flexibility_dir=flex_dir,
        )
    )
    return written


def derive_locational_contracts(script: ProjectScript) -> dict[str, Any]:
    cache_dir = script.cache_dir
    data_dir = script.data_dir
    """Clear locational contracts across the anchored adoption grid."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        script.read_json("outputs/cache/feeder_selection.json")[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    tday = day_mean_temps(temp)
    hod0 = int(tmy_hour_of_day(temp))
    cold_days = np.where(tday < float(COLD_DAY_TMEAN_C))[0]
    design_day = int(np.argmin(tday))
    sizing = size_network_to_load(net, script, temp, design_day, feeder_idx)
    size_by_trafo = sizing["size_by_trafo"]

    pf = float(POWER_FACTOR)
    lv = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    homes_by_trafo = {int(t): int(size_by_trafo[int(t)]) for t in lv}
    rating_by_trafo = {
        int(t): float(net.trafo.at[int(t), "sn_mva"]) * 1000.0 * pf for t in lv
    }
    sizes = sorted(set(homes_by_trafo.values()))

    base_mc = _ensure_base_mc_cache(data_dir, temp, sizes, int(TRIAGE_K_BASE))
    base_by_size = {h: base_mc[h][0] for h in sizes}
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(float)
    _cap, series = feeder_rating(temp)
    k_curve = (
        None
        if series is None
        else cold_capability_curve(temp, res_minutes=int(ANNUAL_RES_MINUTES))
    )
    charger_kw = float(
        np.average(
            sorted(CHARGER_MIX), weights=[CHARGER_MIX[k] for k in sorted(CHARGER_MIX)]
        )
    )

    results = [
        clear_one_adoption(
            a,
            homes_by_trafo,
            rating_by_trafo,
            base_by_size,
            pool,
            k_curve,
            cold_days,
            charger_kw,
        )
        for a in TRIAGE_ADOPTION_GRID
    ]

    # Persist the operational scenario into the shared digital twin and
    # materialise the project-local operational artifacts. This is what makes
    # the twin and the dashboard consume THIS study: the SDK writers are
    # project-agnostic, they were simply never called from here.
    operational = _persist_operational(results[-1], script)
    # Every other cell still carries its DataFrames; they exist to be persisted,
    # never to be serialised, and the payload is written as JSON.
    for cell in results:
        for key in ("_frames", "_summary", "_scenario_id"):
            cell.pop(key, None)

    payload: dict[str, Any] = {
        "operational_artifacts": {k: str(v) for k, v in operational.items()},
        "n_transformers": len(homes_by_trafo),
        "n_cold_days": int(cold_days.size),
        "dispersion": float(TRIAGE_BASE_DISPERSION),
        "charger_kw_mean": round(charger_kw, ROUND_DECIMALS),
        "hod0": hod0,
        "adoption_grid": [float(a) for a in TRIAGE_ADOPTION_GRID],
        "by_adoption": results,
    }
    out_ref = script.write_json("outputs/json/locational_contracts.json", payload)

    at_sat = results[-1]
    payload["artifact_paths"] = [out_ref] + _figures(payload, script)
    payload["summary"] = {
        "n_transformers": payload["n_transformers"],
        "n_constrained_assets_at_saturation": at_sat["n_constrained_assets"],
        "n_providers_selected_at_saturation": at_sat["n_providers_selected"],
        "curtailed_fraction_at_saturation": at_sat["curtailed_fraction"],
        "contract_cost_usd_at_saturation": at_sat["contract_cost_usd_per_year"],
        "saturation_adoption": at_sat["adoption_ev_per_home"],
    }
    return payload


def _figures(payload: dict[str, Any], script: ProjectScript) -> list[Path]:
    """Constrained assets and contract cost across the adoption grid."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir = script.figures_dir
    figures_dir.mkdir(parents=True, exist_ok=True)
    rows = payload["by_adoption"]
    x = [r["adoption_ev_per_home"] for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 4.4))
    ax1.plot(x, [r["n_constrained_assets"] for r in rows], "o-", label="constrained")
    ax1.plot(
        x, [r["n_providers_selected"] for r in rows], "s-", label="providers cleared"
    )
    ax1.set_xlabel("EV adoption (fleet mean, EV per home)")
    ax1.set_ylabel("count")
    ax1.set_title(f"Locational clearing ({payload['n_transformers']} transformers)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.plot(x, [r["contract_cost_usd_per_year"] for r in rows], "o-")
    ax2.set_xlabel("EV adoption (fleet mean, EV per home)")
    ax2.set_ylabel("contract cost ($/yr)")
    ax2.set_title("Cost of the contracts that clear")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    path = figures_dir / "locational_contracts.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return [path]


def run_stage() -> dict[str, Any]:
    """Run the locational-contract clearing and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_locational_contracts(script)
    warnings = [
        "HARD CLS ONLY. Soft CLS (building thermal flexibility) is offered as "
        "zero everywhere: measured on this network, capping heating does not "
        "store energy, it creates a deficit repaid at the installed baseboard "
        "power, so it moves the peak rather than reducing it. Offering it here "
        "would credit relief the physics does not provide.",
        "CLEARS AT THE POLE TRANSFORMER, not the substation. Sized to its N-1 "
        "firm capacity and judged against the ambient-dependent rating, the "
        "substation does not bind on this network even at 40 % EV penetration; "
        "the congestion is local, so the contract has to be local to matter.",
        "One base realization per size class and one clustered-adoption draw "
        "per adoption level: this stage sizes the CONTRACT, it does not carry "
        "the uncertainty band. Read it beside the fleet triage, which sweeps "
        "dispersion and both rating conventions.",
    ]
    return script.write_report(
        "locational_contracts_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the locational-contract stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Locational contracts + report: at saturation "
        f"({s.get('saturation_adoption')} EV/home) "
        f"{s.get('n_constrained_assets_at_saturation')} constrained assets, "
        f"{s.get('n_providers_selected_at_saturation')} providers cleared, "
        f"{s.get('curtailed_fraction_at_saturation')} of EV energy curtailed, "
        f"${s.get('contract_cost_usd_at_saturation')}/yr"
    )


if __name__ == "__main__":
    main()

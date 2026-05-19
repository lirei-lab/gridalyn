#!/usr/bin/env python3
"""Generate pandapower verification report for locational flexibility policies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.simulation.analytics.network_impact.verification_report import (
    build_constraint_aware_dispatch,
    build_constraint_requirements,
    build_locational_dispatch,
    build_network_impact_verification_report,
    build_provider_ranking,
    summarize_dispatch,
    write_network_impact_verification_report,
)
from gridalyn.projects.workflows.flexibility.spatial_powerflow_validation import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MARKET_DISPATCH_PATH,
    _load_s4_inputs,
    _powerflow_metrics,
)
from gridalyn.operations.market.spatial_cls import (
    allocate_addition_by_headroom,
    apply_spatial_cls,
)


DEFAULT_PROVIDERS = DEFAULT_LAYOUT.flexibility / "provider_registry.parquet"
DEFAULT_SENSITIVITY = DEFAULT_LAYOUT.flexibility / "network_sensitivity.parquet"
DEFAULT_PREDICTIONS = DEFAULT_LAYOUT.flexibility / "network_impact_predictions.parquet"
DEFAULT_TRANSFORMERS = DEFAULT_LAYOUT.base / "grid_transformers.parquet"
DEFAULT_OVERLOAD_REPORT = DEFAULT_LAYOUT.reports / "mv_lv_transformer_overload_report.json"
DEFAULT_TRANSFORMER_TIMESERIES = DEFAULT_LAYOUT.timeseries / "S4_powerflow_transformers.parquet"
DEFAULT_OUT = DEFAULT_LAYOUT.flexibility / "network_impact_verification_report.json"


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _constraints_from_overload_report(
    *,
    overload_report_path: Path,
    transformers_path: Path,
    scenario_id: str,
    top_n: int,
) -> list[str]:
    if not overload_report_path.exists() or not transformers_path.exists():
        return []
    report = json.loads(overload_report_path.read_text())
    scenario = next(
        (
            item
            for item in report.get("scenarios", [])
            if str(item.get("scenario_id")) == scenario_id
        ),
        None,
    )
    if not scenario:
        return []
    transformers = pd.read_parquet(transformers_path)
    by_idx = {
        int(row["pandapower_trafo"]): str(row["transformer_id"])
        for row in transformers.to_dict("records")
    }
    constraint_ids = []
    for item in scenario.get("top_transformers", [])[:top_n]:
        trafo_idx = item.get("trafo_idx")
        if trafo_idx is None:
            continue
        constraint_id = by_idx.get(int(trafo_idx))
        if constraint_id:
            constraint_ids.append(constraint_id)
    return constraint_ids


def _fallback_constraints(providers: pd.DataFrame, scenario_id: str, top_n: int) -> list[str]:
    scenario_providers = providers.loc[providers["scenario_id"] == scenario_id]
    if scenario_providers.empty:
        return []
    return (
        scenario_providers.groupby("constraint_zone_id")["available_capacity_kw"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index.astype(str)
        .tolist()
    )


def _with_rebound(
    managed_ev_kw: np.ndarray,
    rebound_kw: np.ndarray,
    ev_eligible: np.ndarray,
    charger_kw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    added_kw, delivered_kw = allocate_addition_by_headroom(
        managed_ev_kw,
        rebound_kw,
        ev_eligible,
        charger_kw,
    )
    return managed_ev_kw + added_kw, delivered_kw


def generate_report(
    *,
    provider_path: Path,
    sensitivity_path: Path,
    predictions_path: Path,
    overload_report_path: Path,
    transformers_path: Path,
    transformer_timeseries_path: Path,
    out_path: Path,
    scenario_id: str,
    cache_dir: Path,
    market_dispatch_path: Path,
    constraint_ids: list[str] | None = None,
    top_constraints: int = 3,
) -> dict:
    if scenario_id != "S4":
        raise ValueError("Current powerflow verification loader supports scenario_id='S4'")

    providers = pd.read_parquet(provider_path)
    sensitivity = pd.read_parquet(sensitivity_path)
    predictions = pd.read_parquet(predictions_path)
    transformers = pd.read_parquet(transformers_path)
    transformer_timeseries = pd.read_parquet(transformer_timeseries_path)

    selected_constraints = constraint_ids or _constraints_from_overload_report(
        overload_report_path=overload_report_path,
        transformers_path=transformers_path,
        scenario_id=scenario_id,
        top_n=top_constraints,
    )
    if not selected_constraints:
        selected_constraints = _fallback_constraints(providers, scenario_id, top_constraints)
    if not selected_constraints:
        raise ValueError(f"No constraints available for scenario {scenario_id}")

    buildings, registry, building_kw, ev_kw, soft_kw, hard_kw, rebound_kw = _load_s4_inputs(
        cache_dir=cache_dir,
        market_dispatch_path=market_dispatch_path,
    )
    dt_h = 5.0 / 60.0
    if building_kw.shape[0] > 1:
        dt_h = 24.0 / float(building_kw.shape[0])
    soft_eligible = registry["soft_cls_participant"].to_numpy(dtype=bool)
    hard_enabled = registry["hard_cls_enabled"].to_numpy(dtype=bool)
    ev_eligible = registry["has_ev"].to_numpy(dtype=bool)
    charger_kw = registry["charger_kw"].to_numpy(dtype=float)
    hard_preferred = ev_eligible & hard_enabled & ~soft_eligible

    aggregate = apply_spatial_cls(
        building_kw=building_kw,
        ev_kw=ev_kw,
        soft_cls_kw=soft_kw,
        hard_cls_kw=hard_kw,
        soft_eligible=soft_eligible,
        hard_preferred=hard_preferred,
        ev_eligible=ev_eligible,
    )
    aggregate_ev_kw, aggregate_rebound_delivered = _with_rebound(
        aggregate.managed_ev_kw,
        rebound_kw,
        ev_eligible,
        charger_kw,
    )

    topology_ranking = build_provider_ranking(
        providers,
        sensitivity=sensitivity,
        scenario_id=scenario_id,
        constraint_ids=selected_constraints,
        method="topology",
    )
    topology = build_locational_dispatch(
        building_kw=building_kw,
        ev_kw=ev_kw,
        soft_target_kw=soft_kw,
        hard_target_kw=hard_kw,
        provider_ranking=topology_ranking,
    )
    topology_ev_kw, topology_rebound_delivered = _with_rebound(
        topology["managed_ev_kw"],
        rebound_kw,
        ev_eligible,
        charger_kw,
    )
    transformer_id_by_idx = {
        int(row["pandapower_trafo"]): str(row["transformer_id"])
        for row in transformers.to_dict("records")
    }
    constraint_requirements = build_constraint_requirements(
        transformer_timeseries=transformer_timeseries,
        transformer_id_by_idx=transformer_id_by_idx,
        constraint_ids=selected_constraints,
        limit_percent=100.0,
    )
    constraint_aware = build_constraint_aware_dispatch(
        building_kw=building_kw,
        ev_kw=ev_kw,
        requirements=constraint_requirements,
        provider_ranking=topology_ranking,
    )
    constraint_aware_ev_kw, constraint_aware_rebound_delivered = _with_rebound(
        constraint_aware["managed_ev_kw"],
        rebound_kw,
        ev_eligible,
        charger_kw,
    )

    surrogate_ranking = build_provider_ranking(
        providers,
        predictions=predictions,
        scenario_id=scenario_id,
        constraint_ids=selected_constraints,
        method="surrogate",
    )
    surrogate = build_locational_dispatch(
        building_kw=building_kw,
        ev_kw=ev_kw,
        soft_target_kw=soft_kw,
        hard_target_kw=hard_kw,
        provider_ranking=surrogate_ranking,
    )
    surrogate_ev_kw, surrogate_rebound_delivered = _with_rebound(
        surrogate["managed_ev_kw"],
        rebound_kw,
        ev_eligible,
        charger_kw,
    )

    case_matrices = {
        "unmanaged": {
            "building_kw": building_kw,
            "ev_kw": ev_kw,
        },
        "aggregate_cls": {
            "building_kw": aggregate.managed_building_kw,
            "ev_kw": aggregate_ev_kw,
        },
        "topology_locational": {
            "building_kw": topology["managed_building_kw"],
            "ev_kw": topology_ev_kw,
        },
        "constraint_aware_clearing": {
            "building_kw": constraint_aware["managed_building_kw"],
            "ev_kw": constraint_aware_ev_kw,
        },
        "surrogate_locational": {
            "building_kw": surrogate["managed_building_kw"],
            "ev_kw": surrogate_ev_kw,
        },
    }

    case_metrics = {}
    for label, matrices in case_matrices.items():
        p_total_mw = (matrices["building_kw"] + matrices["ev_kw"]) / 1000.0
        q_total_mvar = (matrices["building_kw"] / 1000.0) * 0.1
        case_metrics[label] = _powerflow_metrics(label, p_total_mw, q_total_mvar, cache_dir=cache_dir)

    aggregate_soft_shortfall = np.maximum(soft_kw - aggregate.soft_delivered_kw, 0.0)
    aggregate_hard_shortfall = np.maximum(hard_kw - aggregate.hard_delivered_kw, 0.0)
    dispatch_summaries = {
        "aggregate_cls": summarize_dispatch(
            soft_delivered_kw=aggregate.soft_delivered_kw,
            hard_delivered_kw=aggregate.hard_delivered_kw,
            soft_shortfall_kw=aggregate_soft_shortfall,
            hard_shortfall_kw=aggregate_hard_shortfall,
            dt_h=dt_h,
        )
        | {"rebound_delivered_mwh": float(aggregate_rebound_delivered.sum() * dt_h / 1000.0)},
        "topology_locational": summarize_dispatch(
            soft_delivered_kw=topology["soft_delivered_kw"],
            hard_delivered_kw=topology["hard_delivered_kw"],
            soft_shortfall_kw=topology["soft_shortfall_kw"],
            hard_shortfall_kw=topology["hard_shortfall_kw"],
            dt_h=dt_h,
        )
        | {"rebound_delivered_mwh": float(topology_rebound_delivered.sum() * dt_h / 1000.0)},
        "constraint_aware_clearing": summarize_dispatch(
            soft_delivered_kw=constraint_aware["soft_delivered_kw"],
            hard_delivered_kw=constraint_aware["hard_delivered_kw"],
            soft_shortfall_kw=constraint_aware["soft_shortfall_kw"],
            hard_shortfall_kw=constraint_aware["hard_shortfall_kw"],
            dt_h=dt_h,
        )
        | {
            "rebound_delivered_mwh": float(constraint_aware_rebound_delivered.sum() * dt_h / 1000.0),
            "local_requirement_mwh": float(
                constraint_requirements["required_kw"].sum() * dt_h / 1000.0
            )
            if not constraint_requirements.empty
            else 0.0,
            "constraint_event_count": int(
                (constraint_requirements.get("required_kw", pd.Series(dtype=float)).astype(float) > 0.0).sum()
            ),
        },
        "surrogate_locational": summarize_dispatch(
            soft_delivered_kw=surrogate["soft_delivered_kw"],
            hard_delivered_kw=surrogate["hard_delivered_kw"],
            soft_shortfall_kw=surrogate["soft_shortfall_kw"],
            hard_shortfall_kw=surrogate["hard_shortfall_kw"],
            dt_h=dt_h,
        )
        | {"rebound_delivered_mwh": float(surrogate_rebound_delivered.sum() * dt_h / 1000.0)},
    }

    report = build_network_impact_verification_report(
        scenario_id=scenario_id,
        constraint_ids=selected_constraints,
        case_metrics=case_metrics,
        dispatch_summaries=dispatch_summaries,
    )
    report["inputs"] = {
        "provider_registry": _relpath(provider_path),
        "network_sensitivity": _relpath(sensitivity_path),
        "network_impact_predictions": _relpath(predictions_path),
        "overload_report": _relpath(overload_report_path),
        "grid_transformers": _relpath(transformers_path),
        "transformer_timeseries": _relpath(transformer_timeseries_path),
        "topology_cache": _relpath(cache_dir),
        "market_dispatch": _relpath(market_dispatch_path),
    }
    report["artifacts"] = {"report": _relpath(out_path)}
    report["selection"] = {
        "topology_provider_count": int(len(topology_ranking)),
        "constraint_aware_event_count": len(constraint_aware["events"]),
        "surrogate_provider_count": int(len(surrogate_ranking)),
        "constraint_aware_policy": "local transformer overload requirements cleared with local providers, Soft first and Hard CLS as recourse",
        "topology_policy": "same aggregate soft/hard targets allocated to local topology-ranked providers",
        "surrogate_policy": "same aggregate soft/hard targets allocated to local surrogate-ranked providers",
        "rebound_policy": "same EV rebound profile allocated to available charger headroom",
    }
    write_network_impact_verification_report(out_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-path", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--sensitivity-path", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--overload-report-path", type=Path, default=DEFAULT_OVERLOAD_REPORT)
    parser.add_argument("--transformers-path", type=Path, default=DEFAULT_TRANSFORMERS)
    parser.add_argument("--transformer-timeseries-path", type=Path, default=DEFAULT_TRANSFORMER_TIMESERIES)
    parser.add_argument("--out-path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--market-dispatch-path", type=Path, default=DEFAULT_MARKET_DISPATCH_PATH)
    parser.add_argument("--constraint-id", action="append", dest="constraint_ids")
    parser.add_argument("--top-constraints", type=int, default=3)
    args = parser.parse_args()

    report = generate_report(
        provider_path=args.provider_path,
        sensitivity_path=args.sensitivity_path,
        predictions_path=args.predictions_path,
        overload_report_path=args.overload_report_path,
        transformers_path=args.transformers_path,
        transformer_timeseries_path=args.transformer_timeseries_path,
        out_path=args.out_path,
        scenario_id=args.scenario_id,
        cache_dir=args.cache_dir,
        market_dispatch_path=args.market_dispatch_path,
        constraint_ids=args.constraint_ids,
        top_constraints=args.top_constraints,
    )
    print(
        json.dumps(
            {
                "scenario_id": report["scenario_id"],
                "constraint_ids": report["constraint_ids"],
                "comparisons": report["comparisons"],
                "dispatch": report["dispatch"],
                "artifacts": report["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

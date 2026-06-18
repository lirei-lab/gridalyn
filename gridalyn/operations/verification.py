"""Canonical CLS verification surface (VERIF-02 / VERIF-03).

This module unifies the formerly separate verification helpers behind the frozen
``gridalyn.operations`` facade:

* cross-artifact consistency validation
  (``validate_cls_output_consistency`` / :class:`CLSOutputConsistencyResult`),
  moved from ``gridalyn.operations.flexibility.validation`` — this asserts the
  95% security **envelope** (Stage 02) artifacts describe one coherent run;
* locational-clearing verification (``apply_locational_selections``,
  ``build_locational_clearing_verification_report``,
  ``write_locational_verification_outputs``), moved from
  ``gridalyn.operations.market.locational_verification``;
* the provider-selection shadow report (``build_shadow_report`` /
  ``write_shadow_report``), moved from
  ``gridalyn.operations.market.provider_shadow``.

The 95% envelope (Stage 02, ``ev_summary_results.json``) and the per-realization
out-of-sample ``E_omega`` distribution (Stage 03,
``stage2_realization_summary.json``) are two NEVER-interchangeable metric groups;
the per-realization ``E_omega`` replay lives in :mod:`gridalyn.operations.replay`.
The locational allocation-vs-selection split is structurally resolved by the
:mod:`gridalyn.operations.clearing` package (``allocation`` vs ``selection``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.operations.clearing.selection import select_providers_for_constraint

_SCENARIO_RE = re.compile(r"^S\d+_(\d+)pct$")


@dataclass(frozen=True)
class CLSOutputConsistencyResult:
    """Cross-artifact consistency result for a CLS study run."""

    errors: list[str]
    scenario_labels: list[str]
    dynamic_limit_min_mw: float
    dynamic_limit_max_mw: float
    s4_soft_cls_mwh: float
    s4_hard_cls_mwh: float

    @property
    def valid(self) -> bool:
        """Return ``True`` when no consistency errors were recorded."""
        return not self.errors


def validate_cls_output_consistency(
    *,
    ev_summary: dict[str, Any],
    flex_requirements: dict[str, Any],
    pandapower_validation: dict[str, Any],
    dispatch_timeseries: pd.DataFrame,
    temporal_bounds: pd.DataFrame,
    n_buildings: int,
    dispatch_scenario: str = "S4_40pct",
    tolerance: float = 1e-9,
) -> CLSOutputConsistencyResult:
    """Validate that CLS JSON/parquet artifacts describe the same study run."""
    errors: list[str] = []

    scenarios = _scenario_items(ev_summary)
    pp_scenarios = {
        item["label"]: item
        for item in pandapower_validation.get("scenarios", [])
        if "label" in item
    }
    if set(scenarios) != set(pp_scenarios):
        errors.append(
            f"Scenario sets differ: ev_summary={sorted(scenarios)} "
            f"pandapower={sorted(pp_scenarios)}"
        )

    for label, values in scenarios.items():
        match = _SCENARIO_RE.match(label)
        if not match:
            errors.append(f"Scenario label has unexpected format: {label}")
            continue
        ev_pct = int(match.group(1))
        expected_evs = int(round(n_buildings * (ev_pct / 100.0)))
        if values["n_ev"] != expected_evs:
            errors.append(f"{label}: n_ev {values['n_ev']} != expected {expected_evs}")

        if label in pp_scenarios:
            _assert_close(
                errors,
                f"{label}: pandapower p_peak_mw vs ev_summary unmanaged_peak_mw",
                float(pp_scenarios[label]["p_peak_mw"]),
                float(values["unmanaged_peak_mw"]),
                tolerance,
            )

    _require_columns_validation(
        errors,
        dispatch_timeseries,
        ["t_hours", "p_soft_cls_mw", "p_hard_cls_mw", "p_rebound_mw", "p_limit_trace_mw"],
        "dispatch_timeseries",
    )
    _require_columns_validation(errors, temporal_bounds, ["p_limit_trace"], "temporal_bounds")

    dt_h = _infer_dt_h(dispatch_timeseries, errors)
    dispatch_values = scenarios.get(dispatch_scenario, {})
    s4_soft = _sum_energy(dispatch_timeseries, "p_soft_cls_mw", dt_h)
    s4_hard = _sum_energy(dispatch_timeseries, "p_hard_cls_mw", dt_h)
    s4_rebound = _sum_energy(dispatch_timeseries, "p_rebound_mw", dt_h)

    if dispatch_values:
        _assert_close(
            errors,
            f"{dispatch_scenario} total_soft_cls_mwh",
            float(dispatch_values["total_soft_cls_mwh"]),
            s4_soft,
            tolerance,
        )
        _assert_close(
            errors,
            f"{dispatch_scenario} total_hard_cls_mwh",
            float(dispatch_values["total_hard_cls_mwh"]),
            s4_hard,
            tolerance,
        )
        _assert_close(
            errors,
            f"{dispatch_scenario} total_rebound_mwh",
            float(dispatch_values["total_rebound_mwh"]),
            s4_rebound,
            tolerance,
        )

    dynamic_max = _series_max(dispatch_timeseries, "p_limit_trace_mw")
    temporal_max = _series_max(temporal_bounds, "p_limit_trace")
    temporal_min = _series_min(temporal_bounds, "p_limit_trace")
    _assert_close(
        errors,
        "ev_summary p_limit_dynamic_mw legacy alias",
        float(ev_summary["p_limit_dynamic_mw"]),
        float(ev_summary["dynamic_limit_max_mw"]),
        1e-12,
    )
    _assert_close(
        errors,
        "ev_summary dynamic_limit_max_mw vs dispatch",
        float(ev_summary["dynamic_limit_max_mw"]),
        dynamic_max,
        tolerance,
    )
    _assert_close(
        errors,
        "flex dynamic_limit_max_mw vs temporal",
        float(flex_requirements["dynamic_limit_max_mw"]),
        temporal_max,
        tolerance,
    )
    _assert_close(
        errors,
        "flex dynamic_limit_min_mw vs temporal",
        float(flex_requirements["dynamic_limit_min_mw"]),
        temporal_min,
        tolerance,
    )
    _assert_close(
        errors,
        "flex p_limit_kw legacy alias",
        float(flex_requirements["p_limit_kw"]),
        float(flex_requirements["dynamic_limit_at_peak_mw"] * 1000.0),
        tolerance,
    )

    return CLSOutputConsistencyResult(
        errors=errors,
        scenario_labels=sorted(scenarios),
        dynamic_limit_min_mw=float(ev_summary.get("dynamic_limit_min_mw", temporal_min)),
        dynamic_limit_max_mw=float(ev_summary.get("dynamic_limit_max_mw", dynamic_max)),
        s4_soft_cls_mwh=s4_soft,
        s4_hard_cls_mwh=s4_hard,
    )


def _scenario_items(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: value for key, value in summary.items() if isinstance(value, dict)}


def _assert_close(errors: list[str], label: str, left: float, right: float, tol: float) -> None:
    if not np.isclose(left, right, atol=tol, rtol=0.0):
        errors.append(f"{label}: {left} != {right} (tol={tol})")


def _require_columns_validation(
    errors: list[str],
    frame: pd.DataFrame,
    columns: list[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        errors.append(f"{label}: missing columns {missing}")


def _infer_dt_h(frame: pd.DataFrame, errors: list[str]) -> float:
    if "t_hours" not in frame or len(frame) < 2:
        errors.append("dispatch_timeseries: cannot infer dt_h")
        return 0.0
    return float(frame["t_hours"].iloc[1] - frame["t_hours"].iloc[0])


def _sum_energy(frame: pd.DataFrame, column: str, dt_h: float) -> float:
    if column not in frame:
        return 0.0
    return float(frame[column].sum() * dt_h)


def _series_max(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].max()) if column in frame else float("nan")


def _series_min(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].min()) if column in frame else float("nan")


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def _compare_to_unmanaged(metrics: dict[str, Any], unmanaged: dict[str, Any]) -> dict[str, float | int]:
    return {
        "trafo_max_loading_reduction_pctpt": float(
            unmanaged["trafo_max_loading_percent"] - metrics["trafo_max_loading_percent"]
        ),
        "line_max_loading_reduction_pctpt": float(
            unmanaged["line_max_loading_percent"] - metrics["line_max_loading_percent"]
        ),
        "v_min_improvement_pu": float(metrics["v_min_pu"] - unmanaged["v_min_pu"]),
        "ext_grid_peak_reduction_mw": float(
            unmanaged["ext_grid_peak_mw"] - metrics["ext_grid_peak_mw"]
        ),
        "trafo_overload_delta": int(metrics["n_trafo_overloads"] - unmanaged["n_trafo_overloads"]),
        "line_overload_delta": int(metrics["n_line_overloads"] - unmanaged["n_line_overloads"]),
    }


def _dispatch_summary(
    *,
    soft_delivered_kw: np.ndarray,
    hard_delivered_kw: np.ndarray,
    soft_shortfall_kw: np.ndarray,
    hard_shortfall_kw: np.ndarray,
    dt_h: float,
) -> dict[str, float | int]:
    soft_delivered = np.asarray(soft_delivered_kw, dtype=float)
    hard_delivered = np.asarray(hard_delivered_kw, dtype=float)
    soft_shortfall = np.asarray(soft_shortfall_kw, dtype=float)
    hard_shortfall = np.asarray(hard_shortfall_kw, dtype=float)
    total_shortfall = soft_shortfall + hard_shortfall
    total_delivered_kw = soft_delivered + hard_delivered
    return {
        "soft_delivered_mwh": float(soft_delivered.sum() * dt_h / 1000.0),
        "hard_delivered_mwh": float(hard_delivered.sum() * dt_h / 1000.0),
        "total_delivered_mwh": float(total_delivered_kw.sum() * dt_h / 1000.0),
        "soft_shortfall_mwh": float(soft_shortfall.sum() * dt_h / 1000.0),
        "hard_shortfall_mwh": float(hard_shortfall.sum() * dt_h / 1000.0),
        "total_shortfall_mwh": float(total_shortfall.sum() * dt_h / 1000.0),
        "shortfall_event_count": int(np.sum(total_shortfall > 1e-9)),
    }


def apply_locational_selections(
    *,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    selections: pd.DataFrame,
    providers: pd.DataFrame,
    dt_h: float,
) -> dict[str, Any]:
    """Apply provider-level locational clearing selections to load matrices."""
    building = np.asarray(building_kw, dtype=float).copy()
    ev = np.asarray(ev_kw, dtype=float).copy()
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")
    _require_columns(
        selections,
        ["timestep", "provider_id", "provider_type", "selected_kw"],
        "selections",
    )
    _require_columns(providers, ["provider_id", "pandapower_load"], "providers")

    merged = selections.merge(
        providers[["provider_id", "pandapower_load"]],
        on="provider_id",
        how="left",
        validate="many_to_one",
    )
    if merged["pandapower_load"].isna().any():
        missing = sorted(merged.loc[merged["pandapower_load"].isna(), "provider_id"].unique())
        raise ValueError(f"selections contain providers missing from registry: {missing[:5]}")

    n_steps = building.shape[0]
    soft_delivered = np.zeros(n_steps, dtype=float)
    hard_delivered = np.zeros(n_steps, dtype=float)
    soft_shortfall = np.zeros(n_steps, dtype=float)
    hard_shortfall = np.zeros(n_steps, dtype=float)

    for row in merged.sort_values(["timestep", "provider_id"]).to_dict("records"):
        timestep = int(row["timestep"])
        if timestep < 0 or timestep >= n_steps:
            continue
        load_idx = int(row["pandapower_load"])
        if load_idx < 0 or load_idx >= building.shape[1]:
            continue
        requested_kw = max(float(row["selected_kw"]), 0.0)
        provider_type = str(row["provider_type"])
        if provider_type == "soft_cls_building":
            delivered_kw = min(requested_kw, max(float(building[timestep, load_idx]), 0.0))
            building[timestep, load_idx] -= delivered_kw
            soft_delivered[timestep] += delivered_kw
            soft_shortfall[timestep] += max(requested_kw - delivered_kw, 0.0)
        elif provider_type == "hard_cls_ev":
            delivered_kw = min(requested_kw, max(float(ev[timestep, load_idx]), 0.0))
            ev[timestep, load_idx] -= delivered_kw
            hard_delivered[timestep] += delivered_kw
            hard_shortfall[timestep] += max(requested_kw - delivered_kw, 0.0)

    dispatch = pd.DataFrame(
        {
            "timestep": np.arange(n_steps, dtype=int),
            "soft_delivered_kw": soft_delivered,
            "hard_delivered_kw": hard_delivered,
            "soft_shortfall_kw": soft_shortfall,
            "hard_shortfall_kw": hard_shortfall,
            "total_delivered_kw": soft_delivered + hard_delivered,
            "total_shortfall_kw": soft_shortfall + hard_shortfall,
        }
    )
    return {
        "managed_building_kw": building,
        "managed_ev_kw": ev,
        "soft_delivered_kw": soft_delivered,
        "hard_delivered_kw": hard_delivered,
        "soft_shortfall_kw": soft_shortfall,
        "hard_shortfall_kw": hard_shortfall,
        "dispatch": dispatch,
        "summary": _dispatch_summary(
            soft_delivered_kw=soft_delivered,
            hard_delivered_kw=hard_delivered,
            soft_shortfall_kw=soft_shortfall,
            hard_shortfall_kw=hard_shortfall,
            dt_h=dt_h,
        ),
    }


def build_locational_clearing_verification_report(
    *,
    scenario_id: str,
    clearing_summary: dict[str, Any],
    case_metrics: dict[str, dict[str, Any]],
    constraint_ids: list[str],
) -> dict[str, Any]:
    """Build a report comparing locational clearing against unmanaged load."""
    if "unmanaged" not in case_metrics:
        raise ValueError("case_metrics must include unmanaged")
    if "locational_clearing" not in case_metrics:
        raise ValueError("case_metrics must include locational_clearing")
    comparisons = {
        "locational_clearing_vs_unmanaged": _compare_to_unmanaged(
            case_metrics["locational_clearing"],
            case_metrics["unmanaged"],
        )
    }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "locational_clearing_verification",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "constraint_ids": constraint_ids,
        "validation": {
            "authority": "pandapower_ac_powerflow",
            "policy": "locational clearing selections are replayed on the physical network",
        },
        "dispatch": {
            "locational_clearing": clearing_summary,
        },
        "cases": case_metrics,
        "comparisons": comparisons,
    }


def write_locational_verification_outputs(
    *,
    dispatch: pd.DataFrame,
    report: dict[str, Any],
    dispatch_path: Path,
    report_path: Path,
) -> dict[str, Path]:
    """Write locational verification dispatch and report artifacts."""
    dispatch_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch.to_parquet(dispatch_path, index=False)
    report_with_artifacts = {
        **report,
        "artifacts": {
            "dispatch": str(dispatch_path),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report_with_artifacts, indent=2, sort_keys=True))
    return {"dispatch": dispatch_path, "report": report_path}


def _dispatch_dt_h(dispatch: pd.DataFrame) -> float:
    if "t_hours" in dispatch and len(dispatch) > 1:
        diffs = dispatch["t_hours"].diff().dropna()
        if not diffs.empty:
            return float(diffs.median())
    return 5.0 / 60.0


def _provider_selection_summary(selected: pd.DataFrame) -> tuple[float, float, list[dict[str, Any]]]:
    if selected.empty:
        return 0.0, 0.0, []
    by_type = selected.groupby("provider_type")["selected_kw"].sum()
    selected_soft_kw = float(by_type.get("soft_cls_building", 0.0))
    selected_hard_kw = float(by_type.get("hard_cls_ev", 0.0))
    selected_providers = []
    for row in selected.to_dict("records"):
        selected_providers.append(
            {
                "provider_id": row["provider_id"],
                "provider_type": row["provider_type"],
                "selected_kw": float(row["selected_kw"]),
                "expected_relief_kw": float(row["expected_relief_kw"]),
                "effective_cost_per_kw_h": float(row["effective_cost_per_kw_h"]),
            }
        )
    return selected_soft_kw, selected_hard_kw, selected_providers


def build_shadow_report(
    dispatch: pd.DataFrame,
    providers: pd.DataFrame,
    sensitivity: pd.DataFrame,
    *,
    scenario_id: str,
    constraint_ids: list[str],
    max_selected_providers_per_event: int = 20,
) -> dict[str, Any]:
    """Build a non-invasive report comparing aggregate dispatch to local selection."""
    dt_h = _dispatch_dt_h(dispatch)
    events: list[dict[str, Any]] = []
    scenario_providers = providers.loc[providers["scenario_id"] == scenario_id].copy()
    sensitivity_by_constraint = {
        constraint_id: sensitivity.loc[
            (sensitivity["scenario_id"] == scenario_id)
            & (sensitivity["constraint_id"] == constraint_id)
        ].copy()
        for constraint_id in constraint_ids
    }

    for _, row in dispatch.iterrows():
        aggregate_soft_kw = float(row.get("p_soft_cls_mw", 0.0) or 0.0) * 1000.0
        aggregate_hard_kw = float(row.get("p_hard_cls_mw", 0.0) or 0.0) * 1000.0
        required_kw = aggregate_soft_kw + aggregate_hard_kw
        if required_kw <= 0.0:
            continue

        for constraint_id in constraint_ids:
            selected = select_providers_for_constraint(
                scenario_providers,
                sensitivity_by_constraint[constraint_id],
                scenario_id=scenario_id,
                constraint_id=constraint_id,
                required_kw=required_kw,
            )
            selected_soft_kw, selected_hard_kw, selected_providers = _provider_selection_summary(
                selected.head(max_selected_providers_per_event)
            )
            selected_relief_kw = float(selected["expected_relief_kw"].sum()) if not selected.empty else 0.0
            local_shortfall_kw = max(0.0, required_kw - selected_relief_kw)
            total_cost = (
                float((selected["selected_kw"] * selected["effective_cost_per_kw_h"]).sum() * dt_h)
                if not selected.empty
                else 0.0
            )
            events.append(
                {
                    "t_hours": float(row.get("t_hours", 0.0) or 0.0),
                    "constraint_id": constraint_id,
                    "required_kw": required_kw,
                    "aggregate_soft_kw": aggregate_soft_kw,
                    "aggregate_hard_kw": aggregate_hard_kw,
                    "selected_soft_kw": selected_soft_kw,
                    "selected_hard_kw": selected_hard_kw,
                    "selected_relief_kw": selected_relief_kw,
                    "local_shortfall_kw": local_shortfall_kw,
                    "estimated_selection_cost": total_cost,
                    "selected_provider_count": int(len(selected)),
                    "selected_providers": selected_providers,
                }
            )

    aggregate_required_mwh = sum(event["required_kw"] * dt_h / 1000.0 for event in events)
    local_selected_mwh = sum(event["selected_relief_kw"] * dt_h / 1000.0 for event in events)
    local_shortfall_mwh = sum(event["local_shortfall_kw"] * dt_h / 1000.0 for event in events)
    unique_dispatch_required_mwh = float(
        (
            (dispatch.get("p_soft_cls_mw", 0.0) + dispatch.get("p_hard_cls_mw", 0.0))
            .clip(lower=0.0)
            .sum()
            * dt_h
        )
    )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "provider_selection_shadow",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "selection_method": "downstream_transformer_topology_effective_cost",
        "dt_h": dt_h,
        "constraint_ids": constraint_ids,
        "n_events": len(events),
        "summary": {
            "unique_dispatch_required_mwh": unique_dispatch_required_mwh,
            "aggregate_required_mwh": aggregate_required_mwh,
            "local_selected_mwh": local_selected_mwh,
            "local_shortfall_mwh": local_shortfall_mwh,
            "shortfall_event_count": int(sum(event["local_shortfall_kw"] > 0.0 for event in events)),
            "estimated_selection_cost": float(sum(event["estimated_selection_cost"] for event in events)),
        },
        "events": events,
    }


def write_shadow_report(path: Path, report: dict[str, Any]) -> Path:
    """Write a provider-selection shadow report JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return path


__all__ = [
    "CLSOutputConsistencyResult",
    "apply_locational_selections",
    "build_locational_clearing_verification_report",
    "build_shadow_report",
    "validate_cls_output_consistency",
    "write_locational_verification_outputs",
    "write_shadow_report",
]

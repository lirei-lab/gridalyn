"""Verification helpers for replaying locational clearing selections."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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

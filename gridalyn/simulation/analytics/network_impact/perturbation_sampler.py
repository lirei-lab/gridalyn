"""Pandapower perturbation sampling helpers for network impact labels."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _active_timesteps(dispatch: pd.DataFrame, max_timesteps: int) -> list[int]:
    soft = dispatch.get("p_soft_cls_mw", pd.Series(0.0, index=dispatch.index)).astype(float)
    hard = dispatch.get("p_hard_cls_mw", pd.Series(0.0, index=dispatch.index)).astype(float)
    active = dispatch.loc[(soft + hard) > 0.0].copy()
    if active.empty:
        return []
    if "t_hours" in active:
        active = active.sort_values("t_hours")
    return [int(index) for index in active.index[:max_timesteps]]


def _perturbation_values(perturbation_kw: float | Iterable[float]) -> list[float]:
    if isinstance(perturbation_kw, (int, float)):
        return [float(perturbation_kw)]
    values = [float(value) for value in perturbation_kw]
    if not values:
        raise ValueError("perturbation_kw must contain at least one value")
    if any(value <= 0.0 for value in values):
        raise ValueError("perturbation_kw values must be positive")
    return sorted(set(values))


def select_perturbation_samples(
    providers: pd.DataFrame,
    predictions: pd.DataFrame,
    dispatch: pd.DataFrame,
    *,
    scenario_id: str,
    constraint_ids: list[str],
    perturbation_kw: float | Iterable[float],
    max_providers_per_constraint: int,
    max_timesteps: int,
) -> pd.DataFrame:
    """Select ranked provider/timestep perturbations to label with pandapower."""
    _require_columns(
        providers,
        ["provider_id", "scenario_id", "provider_type", "pandapower_load", "available_capacity_kw"],
        "providers",
    )
    _require_columns(
        predictions,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "constraint_id",
            "predicted_deliverability_factor",
            "selection_score",
        ],
        "predictions",
    )
    constraints = set(str(value) for value in constraint_ids)
    candidate_predictions = predictions.loc[
        (predictions["scenario_id"] == scenario_id)
        & predictions["constraint_id"].astype(str).isin(constraints)
        & (predictions["predicted_deliverability_factor"].astype(float) > 0.0)
    ].copy()
    if candidate_predictions.empty:
        return pd.DataFrame()
    candidate_predictions = candidate_predictions.sort_values(
        ["constraint_id", "selection_score", "provider_id"],
        ascending=[True, False, True],
    )
    candidate_predictions = candidate_predictions.groupby("constraint_id", as_index=False).head(
        max_providers_per_constraint
    )
    providers = providers.loc[providers["scenario_id"] == scenario_id].copy()
    candidates = providers.merge(
        candidate_predictions.drop(
            columns=[
                column
                for column in ["available_capacity_kw", "base_cost_per_kw_h", "selection_priority"]
                if column in candidate_predictions.columns
            ]
        ),
        on=["provider_id", "scenario_id", "provider_type"],
        how="inner",
        validate="one_to_many",
    )
    timesteps = _active_timesteps(dispatch, max_timesteps)
    perturbation_values = _perturbation_values(perturbation_kw)
    rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        for timestep in timesteps:
            for perturbation in perturbation_values:
                rows.append(
                    {
                        "sample_id": f"{candidate['constraint_id']}|{candidate['provider_id']}|t{timestep}|kw{perturbation:g}",
                        "scenario_id": scenario_id,
                        "constraint_id": candidate["constraint_id"],
                        "provider_id": candidate["provider_id"],
                        "provider_type": candidate["provider_type"],
                        "pandapower_load": int(candidate["pandapower_load"]),
                        "timestep": int(timestep),
                        "requested_perturbation_kw": float(perturbation),
                        "available_capacity_kw": float(candidate["available_capacity_kw"]),
                        "predicted_deliverability_factor": float(
                            candidate["predicted_deliverability_factor"]
                        ),
                        "selection_score": float(candidate["selection_score"]),
                    }
                )
    return pd.DataFrame(rows).sort_values(["constraint_id", "selection_score", "sample_id"], ascending=[True, False, True]).reset_index(drop=True)


def build_perturbation_matrices(
    *,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    samples: pd.DataFrame,
) -> dict[str, np.ndarray]:
    """Build one perturbation load row per sample."""
    building = np.asarray(building_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")
    _require_columns(
        samples,
        [
            "timestep",
            "provider_type",
            "pandapower_load",
            "requested_perturbation_kw",
            "available_capacity_kw",
        ],
        "samples",
    )
    n_samples = len(samples)
    p_total_mw = np.zeros((n_samples, building.shape[1]), dtype=float)
    q_total_mvar = np.zeros((n_samples, building.shape[1]), dtype=float)
    actual = np.zeros(n_samples, dtype=float)
    for row_idx, sample in enumerate(samples.to_dict("records")):
        timestep = int(sample["timestep"])
        load_idx = int(sample["pandapower_load"])
        perturbed_building = building[timestep].copy()
        perturbed_ev = ev[timestep].copy()
        requested = max(float(sample["requested_perturbation_kw"]), 0.0)
        available = max(float(sample["available_capacity_kw"]), 0.0)
        if sample["provider_type"] == "soft_cls_building":
            reduction = min(requested, available, perturbed_building[load_idx])
            perturbed_building[load_idx] -= reduction
        elif sample["provider_type"] == "hard_cls_ev":
            reduction = min(requested, available, perturbed_ev[load_idx])
            perturbed_ev[load_idx] -= reduction
        else:
            reduction = 0.0
        actual[row_idx] = reduction
        p_total_mw[row_idx] = (perturbed_building + perturbed_ev) / 1000.0
        q_total_mvar[row_idx] = (perturbed_building / 1000.0) * 0.1
    return {
        "p_total_mw": p_total_mw,
        "q_total_mvar": q_total_mvar,
        "actual_perturbation_kw": actual,
    }


def build_baseline_matrices(
    *,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    timesteps: list[int],
) -> dict[str, np.ndarray]:
    """Build baseline matrices for unique sampled timesteps."""
    building = np.asarray(building_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")
    p_total_mw = np.zeros((len(timesteps), building.shape[1]), dtype=float)
    q_total_mvar = np.zeros((len(timesteps), building.shape[1]), dtype=float)
    for row_idx, timestep in enumerate(timesteps):
        p_total_mw[row_idx] = (building[timestep] + ev[timestep]) / 1000.0
        q_total_mvar[row_idx] = (building[timestep] / 1000.0) * 0.1
    return {"p_total_mw": p_total_mw, "q_total_mvar": q_total_mvar}


def build_physics_labels(
    samples: pd.DataFrame,
    *,
    baseline_results: dict[str, np.ndarray],
    perturbed_results: dict[str, np.ndarray],
    baseline_row_by_timestep: dict[int, int],
    transformer_lookup: dict[str, int],
) -> pd.DataFrame:
    """Compute physical labels from baseline and perturbed pandapower outputs."""
    rows: list[dict[str, Any]] = []
    for sample_idx, sample in enumerate(samples.to_dict("records")):
        baseline_idx = baseline_row_by_timestep[int(sample["timestep"])]
        constraint_id = str(sample["constraint_id"])
        trafo_idx = transformer_lookup.get(constraint_id)
        baseline_trafo = baseline_results["spatial_trafo"][baseline_idx]
        perturbed_trafo = perturbed_results["spatial_trafo"][sample_idx]
        baseline_line = baseline_results["spatial_line"][baseline_idx]
        perturbed_line = perturbed_results["spatial_line"][sample_idx]
        baseline_v = baseline_results["spatial_v"][baseline_idx]
        perturbed_v = perturbed_results["spatial_v"][sample_idx]
        actual_kw = float(sample.get("actual_perturbation_kw", 0.0))

        if trafo_idx is not None and 0 <= int(trafo_idx) < len(baseline_trafo):
            base_constraint_trafo = float(baseline_trafo[int(trafo_idx)])
            pert_constraint_trafo = float(perturbed_trafo[int(trafo_idx)])
        else:
            base_constraint_trafo = float(np.max(baseline_trafo))
            pert_constraint_trafo = float(np.max(perturbed_trafo))
        delta_constraint = pert_constraint_trafo - base_constraint_trafo
        relief_pct_per_kw = (-delta_constraint / actual_kw) if actual_kw > 0.0 else 0.0

        rows.append(
            {
                **sample,
                "baseline_constraint_trafo_loading_pct": base_constraint_trafo,
                "perturbed_constraint_trafo_loading_pct": pert_constraint_trafo,
                "delta_constraint_trafo_loading_pct": delta_constraint,
                "baseline_global_trafo_max_loading_pct": float(np.max(baseline_trafo)),
                "perturbed_global_trafo_max_loading_pct": float(np.max(perturbed_trafo)),
                "delta_global_trafo_max_loading_pct": float(np.max(perturbed_trafo) - np.max(baseline_trafo)),
                "baseline_global_line_max_loading_pct": float(np.max(baseline_line)),
                "perturbed_global_line_max_loading_pct": float(np.max(perturbed_line)),
                "delta_global_line_max_loading_pct": float(np.max(perturbed_line) - np.max(baseline_line)),
                "baseline_v_min_pu": float(np.min(baseline_v)),
                "perturbed_v_min_pu": float(np.min(perturbed_v)),
                "delta_v_min_pu": float(np.min(perturbed_v) - np.min(baseline_v)),
                "baseline_ext_grid_mw": float(baseline_results["ext_p_mw"][baseline_idx]),
                "perturbed_ext_grid_mw": float(perturbed_results["ext_p_mw"][sample_idx]),
                "delta_ext_grid_mw": float(
                    perturbed_results["ext_p_mw"][sample_idx]
                    - baseline_results["ext_p_mw"][baseline_idx]
                ),
                "relief_pct_per_kw": float(relief_pct_per_kw),
                "label_source": "pandapower_finite_difference",
            }
        )
    return pd.DataFrame(rows)


def build_sampler_report(
    *,
    labels: pd.DataFrame,
    scenario_id: str,
    constraint_ids: list[str],
    perturbation_kw: float,
) -> dict[str, Any]:
    """Summarize generated finite-difference labels."""
    positive = labels.loc[labels["actual_perturbation_kw"] > 0.0] if len(labels) else labels
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "network_impact_perturbation_samples",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "constraint_ids": constraint_ids,
        "method": "pandapower_finite_difference",
        "perturbation_kw": float(perturbation_kw),
        "summary": {
            "n_samples": int(len(labels)),
            "n_positive_samples": int(len(positive)),
            "provider_count": int(labels["provider_id"].nunique()) if len(labels) else 0,
            "timestep_count": int(labels["timestep"].nunique()) if len(labels) else 0,
            "mean_relief_pct_per_kw": float(positive["relief_pct_per_kw"].mean()) if len(positive) else 0.0,
            "mean_delta_v_min_pu": float(positive["delta_v_min_pu"].mean()) if len(positive) else 0.0,
        },
    }


def write_sampler_artifacts(
    out_dir: Path,
    *,
    labels: pd.DataFrame,
    report: dict[str, Any],
) -> dict[str, Path]:
    """Write finite-difference labels and report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "labels": out_dir / "network_impact_physics_labels.parquet",
        "report": out_dir / "network_impact_physics_labels_report.json",
    }
    labels.to_parquet(paths["labels"], index=False)
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True))
    return paths

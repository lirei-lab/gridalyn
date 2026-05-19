"""Physics-trained tabular surrogate for network impact provider ranking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


FEATURE_COLUMNS = [
    "feature_available_capacity_kw",
    "feature_base_cost_per_kw_h",
    "feature_selection_priority",
    "feature_topology_sensitivity",
]


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _positive_labels(labels: pd.DataFrame) -> pd.DataFrame:
    return labels.loc[labels["actual_perturbation_kw"].astype(float) > 0.0].copy()


def fit_physics_surrogate(training: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    """Fit an explainable physics surrogate from pandapower finite differences."""
    _require_columns(
        training,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "constraint_id",
            "feature_topology_sensitivity",
        ],
        "training",
    )
    _require_columns(
        labels,
        [
            "provider_id",
            "constraint_id",
            "actual_perturbation_kw",
            "relief_pct_per_kw",
            "delta_v_min_pu",
            "delta_global_line_max_loading_pct",
            "delta_global_trafo_max_loading_pct",
        ],
        "labels",
    )
    positive = _positive_labels(labels)
    pair_labels = (
        positive.groupby(["provider_id", "constraint_id"], as_index=False)
        .agg(
            target_relief_pct_per_kw=("relief_pct_per_kw", "mean"),
            target_delta_v_min_pu=("delta_v_min_pu", "mean"),
            target_delta_global_line_max_loading_pct=("delta_global_line_max_loading_pct", "mean"),
            target_delta_global_trafo_max_loading_pct=("delta_global_trafo_max_loading_pct", "mean"),
            label_count=("provider_id", "count"),
        )
        .reset_index(drop=True)
    )
    if "provider_type" in positive.columns:
        label_context = positive.copy()
    else:
        label_context = positive.merge(
            training[["provider_id", "constraint_id", "provider_type"]],
            on=["provider_id", "constraint_id"],
            how="left",
        )
    type_constraint_labels = (
        label_context.dropna(subset=["provider_type"])
        .groupby(["provider_type", "constraint_id"], as_index=False)
        .agg(
            target_relief_pct_per_kw=("relief_pct_per_kw", "mean"),
            target_delta_v_min_pu=("delta_v_min_pu", "mean"),
            target_delta_global_line_max_loading_pct=("delta_global_line_max_loading_pct", "mean"),
            target_delta_global_trafo_max_loading_pct=("delta_global_trafo_max_loading_pct", "mean"),
            label_count=("provider_id", "count"),
        )
    )
    return {
        "model_family": "tabular_physics_lookup_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_label_rows": int(len(labels)),
        "n_positive_label_rows": int(len(positive)),
        "n_supervised_pairs": int(len(pair_labels)),
        "pair_labels": pair_labels,
        "type_constraint_labels": type_constraint_labels,
    }


def _merge_targets(training: pd.DataFrame, model: dict[str, Any]) -> pd.DataFrame:
    pair_labels = model["pair_labels"].copy()
    type_constraint_labels = model["type_constraint_labels"].copy()
    predicted = training.merge(
        pair_labels,
        on=["provider_id", "constraint_id"],
        how="left",
        suffixes=("", "_pair"),
    )
    fallback = type_constraint_labels.rename(
        columns={
            "target_relief_pct_per_kw": "fallback_relief_pct_per_kw",
            "target_delta_v_min_pu": "fallback_delta_v_min_pu",
            "target_delta_global_line_max_loading_pct": "fallback_delta_global_line_max_loading_pct",
            "target_delta_global_trafo_max_loading_pct": "fallback_delta_global_trafo_max_loading_pct",
            "label_count": "fallback_label_count",
        }
    )
    predicted = predicted.merge(
        fallback,
        on=["provider_type", "constraint_id"],
        how="left",
    )
    target_columns = [
        "target_relief_pct_per_kw",
        "target_delta_v_min_pu",
        "target_delta_global_line_max_loading_pct",
        "target_delta_global_trafo_max_loading_pct",
    ]
    fallback_columns = [
        "fallback_relief_pct_per_kw",
        "fallback_delta_v_min_pu",
        "fallback_delta_global_line_max_loading_pct",
        "fallback_delta_global_trafo_max_loading_pct",
    ]
    for target, fallback_col in zip(target_columns, fallback_columns, strict=True):
        predicted[target] = predicted[target].fillna(predicted[fallback_col]).fillna(0.0)
    predicted["label_count"] = predicted["label_count"].fillna(predicted.get("fallback_label_count", 0)).fillna(0)
    return predicted


def predict_physics_impact(training: pd.DataFrame, model: dict[str, Any]) -> pd.DataFrame:
    """Predict selector-compatible provider impact from a physics surrogate."""
    _require_columns(
        training,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "constraint_id",
            "constraint_type",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
            *FEATURE_COLUMNS,
        ],
        "training",
    )
    predicted = _merge_targets(training.copy(), model)
    topology = predicted["feature_topology_sensitivity"].astype(float).clip(lower=0.0, upper=1.0)
    predicted["predicted_deliverability_factor"] = (
        (predicted["target_relief_pct_per_kw"].astype(float) > 0.0).astype(float) * topology
    )
    predicted["predicted_relief_pct_per_kw"] = predicted["target_relief_pct_per_kw"].astype(float) * topology
    predicted["predicted_relief_kw"] = (
        predicted["available_capacity_kw"].astype(float)
        * predicted["predicted_deliverability_factor"]
        * predicted["predicted_relief_pct_per_kw"].clip(lower=0.0)
    )
    predicted["predicted_delta_loading_pct_per_kw"] = -predicted["predicted_relief_pct_per_kw"]
    predicted["predicted_delta_v_min_pu_per_kw"] = predicted["target_delta_v_min_pu"].astype(float)
    predicted["predicted_side_effect_score"] = (
        predicted["target_delta_global_line_max_loading_pct"].astype(float).clip(lower=0.0)
        + predicted["target_delta_global_trafo_max_loading_pct"].astype(float).clip(lower=0.0)
    )
    predicted["effective_cost_per_predicted_kw_h"] = predicted["base_cost_per_kw_h"].astype(float) / predicted[
        "predicted_deliverability_factor"
    ].clip(lower=0.001)
    denominator = (
        predicted["base_cost_per_kw_h"].astype(float).clip(lower=0.001)
        * predicted["selection_priority"].astype(float).clip(lower=1.0)
    )
    predicted["selection_score"] = predicted["predicted_relief_kw"] / denominator
    predicted["selection_rank"] = (
        predicted.groupby(["scenario_id", "constraint_id"])["selection_score"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    columns = [
        "provider_id",
        "scenario_id",
        "provider_type",
        "constraint_id",
        "constraint_type",
        "available_capacity_kw",
        "base_cost_per_kw_h",
        "selection_priority",
        "predicted_deliverability_factor",
        "predicted_relief_pct_per_kw",
        "predicted_relief_kw",
        "predicted_delta_loading_pct_per_kw",
        "predicted_delta_v_min_pu_per_kw",
        "predicted_side_effect_score",
        "effective_cost_per_predicted_kw_h",
        "selection_score",
        "selection_rank",
        "label_count",
    ]
    return predicted[columns].sort_values(["constraint_id", "selection_rank", "provider_id"]).reset_index(drop=True)


def build_physics_surrogate_report(
    model: dict[str, Any],
    predictions: pd.DataFrame,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    """Summarize the physics-trained surrogate predictions."""
    positive = predictions.loc[predictions["predicted_relief_kw"].astype(float) > 0.0]
    supervised = predictions.loc[predictions["label_count"].astype(float) > 0.0]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "network_impact_physics_surrogate",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "model": {
            "model_family": model["model_family"],
            "fallback_policy": "provider_type_constraint_mean_then_topology_zero",
            "label_source": "pandapower_finite_difference",
            "future_backend": "sklearn_or_heterogeneous_gnn",
        },
        "summary": {
            "n_label_rows": int(model["n_label_rows"]),
            "n_positive_label_rows": int(model["n_positive_label_rows"]),
            "n_supervised_pairs": int(model["n_supervised_pairs"]),
            "n_prediction_rows": int(len(predictions)),
            "n_positive_predictions": int(len(positive)),
            "n_supervised_predictions": int(len(supervised)),
            "positive_predicted_relief_kw": float(positive["predicted_relief_kw"].sum()) if len(positive) else 0.0,
            "mean_predicted_relief_pct_per_kw": float(positive["predicted_relief_pct_per_kw"].mean()) if len(positive) else 0.0,
        },
    }


def write_physics_surrogate_artifacts(
    out_dir: Path,
    *,
    predictions: pd.DataFrame,
    report: dict[str, Any],
) -> dict[str, Path]:
    """Write physics surrogate predictions and report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "predictions": out_dir / "network_impact_physics_predictions.parquet",
        "report": out_dir / "network_impact_physics_surrogate_report.json",
    }
    predictions.to_parquet(paths["predictions"], index=False)
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True))
    return paths

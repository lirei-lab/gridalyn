"""Physics-trained tabular surrogate for network impact provider ranking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.simulation.surrogates.contract import (
    RELIEF_ERROR_METRIC,
    RELIEF_ERROR_UNITS,
    ErrorBound,
    SurrogateDescriptor,
    measure_relief_error_bound,
    unmeasured_error_bound,
)

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


def fit_physics_surrogate(
    training: pd.DataFrame, labels: pd.DataFrame
) -> dict[str, Any]:
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
            target_delta_global_line_max_loading_pct=(
                "delta_global_line_max_loading_pct",
                "mean",
            ),
            target_delta_global_trafo_max_loading_pct=(
                "delta_global_trafo_max_loading_pct",
                "mean",
            ),
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
            target_delta_global_line_max_loading_pct=(
                "delta_global_line_max_loading_pct",
                "mean",
            ),
            target_delta_global_trafo_max_loading_pct=(
                "delta_global_trafo_max_loading_pct",
                "mean",
            ),
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
            "target_delta_global_line_max_loading_pct": (
                "fallback_delta_global_line_max_loading_pct"
            ),
            "target_delta_global_trafo_max_loading_pct": (
                "fallback_delta_global_trafo_max_loading_pct"
            ),
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
        predicted[target] = (
            predicted[target].fillna(predicted[fallback_col]).fillna(0.0)
        )
    predicted["label_count"] = (
        predicted["label_count"]
        .fillna(predicted.get("fallback_label_count", 0))
        .fillna(0)
    )
    return predicted


def predict_physics_impact(
    training: pd.DataFrame, model: dict[str, Any]
) -> pd.DataFrame:
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
    topology = (
        predicted["feature_topology_sensitivity"]
        .astype(float)
        .clip(lower=0.0, upper=1.0)
    )
    predicted["predicted_deliverability_factor"] = (
        predicted["target_relief_pct_per_kw"].astype(float) > 0.0
    ).astype(float) * topology
    predicted["predicted_relief_pct_per_kw"] = (
        predicted["target_relief_pct_per_kw"].astype(float) * topology
    )
    predicted["predicted_relief_kw"] = (
        predicted["available_capacity_kw"].astype(float)
        * predicted["predicted_deliverability_factor"]
        * predicted["predicted_relief_pct_per_kw"].clip(lower=0.0)
    )
    predicted["predicted_delta_loading_pct_per_kw"] = -predicted[
        "predicted_relief_pct_per_kw"
    ]
    predicted["predicted_delta_v_min_pu_per_kw"] = predicted[
        "target_delta_v_min_pu"
    ].astype(float)
    predicted["predicted_side_effect_score"] = predicted[
        "target_delta_global_line_max_loading_pct"
    ].astype(float).clip(lower=0.0) + predicted[
        "target_delta_global_trafo_max_loading_pct"
    ].astype(
        float
    ).clip(
        lower=0.0
    )
    predicted["effective_cost_per_predicted_kw_h"] = predicted[
        "base_cost_per_kw_h"
    ].astype(float) / predicted["predicted_deliverability_factor"].clip(lower=0.001)
    denominator = predicted["base_cost_per_kw_h"].astype(float).clip(
        lower=0.001
    ) * predicted["selection_priority"].astype(float).clip(lower=1.0)
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
    return (
        predicted[columns]
        .sort_values(["constraint_id", "selection_rank", "provider_id"])
        .reset_index(drop=True)
    )


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
            "positive_predicted_relief_kw": (
                float(positive["predicted_relief_kw"].sum()) if len(positive) else 0.0
            ),
            "mean_predicted_relief_pct_per_kw": (
                float(positive["predicted_relief_pct_per_kw"].mean())
                if len(positive)
                else 0.0
            ),
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


#: Registry ID of the physics-fitted lookup surrogate.
NETWORK_IMPACT_PHYSICS_SURROGATE_ID = "network_impact_physics_lookup_v1"

#: Label column the hold-out folds are grouped on. A random row split would
#: leak: this model is a group mean over (provider, constraint) pairs, and
#: sibling rows of the same pair at other timesteps would put the answer in
#: the training set.
HOLD_OUT_GROUP_COLUMN = "timestep"


#: The physical model every bound in this module is measured against.
PHYSICS_REFERENCE = "pandapower_ac_powerflow_finite_difference"


def _pool_fold_errors(
    folds: list[ErrorBound],
    *,
    group_column: str,
    n_groups: int,
) -> ErrorBound:
    """Pool per-fold mean absolute errors into one size-weighted bound.

    Args:
        folds: One measured bound per hold-out fold.
        group_column: Label column the folds were grouped on, for the method.
        n_groups: Number of folds attempted, for the method.

    Returns:
        A ``measured`` :class:`ErrorBound` over the pooled samples, or an
        ``unmeasured`` one when no fold produced a measurement.
    """
    scored = [fold for fold in folds if fold.value is not None]
    total = sum(fold.sample_size for fold in scored)
    if total <= 0:
        return unmeasured_error_bound(
            metric=RELIEF_ERROR_METRIC,
            units=RELIEF_ERROR_UNITS,
            reference=PHYSICS_REFERENCE,
            reason=(
                f"no held-out {group_column} fold joined a label to a "
                "prediction; the training frame and the labels appear to "
                "cover disjoint provider/constraint pairs"
            ),
        )
    weighted = sum(float(fold.value or 0.0) * fold.sample_size for fold in scored)
    return ErrorBound(
        metric=RELIEF_ERROR_METRIC,
        units=RELIEF_ERROR_UNITS,
        value=weighted / total,
        sample_size=total,
        method=(
            f"Grouped leave-one-out over {n_groups} {group_column} folds: "
            "each fold refits the lookup on every other group and scores only "
            "the held-out one; per-fold mean absolute errors are pooled "
            "weighted by fold size. No label is in-sample."
        ),
        reference=PHYSICS_REFERENCE,
    )


def measure_physics_surrogate_error_bound(
    training: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    group_column: str = HOLD_OUT_GROUP_COLUMN,
) -> ErrorBound:
    """Measure this surrogate out-of-sample by grouped leave-one-out.

    The model is a lookup of label means, so scoring it on the labels it was
    fitted from measures memorisation, not accuracy. Each fold therefore
    refits on every group but one and scores only the held-out group.

    Args:
        training: Feature table from ``build_training_dataset``.
        labels: Finite-difference labels from ``perturbation_sampler``.
        group_column: Label column defining the folds.

    Returns:
        A ``measured`` :class:`ErrorBound` pooled over all folds, or an
        ``unmeasured`` one when fewer than two groups exist -- with one group
        there is no out-of-sample fold to score.

    Raises:
        ValueError: If ``labels`` lacks ``group_column``.
    """
    if group_column not in labels.columns:
        raise ValueError(
            f"labels is missing the hold-out group column {group_column!r} "
            f"(present columns: {sorted(labels.columns)})"
        )
    landed = _positive_labels(labels)
    groups = sorted(landed[group_column].unique())
    if len(groups) < 2:
        return unmeasured_error_bound(
            metric=RELIEF_ERROR_METRIC,
            units=RELIEF_ERROR_UNITS,
            reference=PHYSICS_REFERENCE,
            reason=(
                f"grouped leave-one-out on {group_column!r} needs at least "
                f"two groups with a landed perturbation, found {len(groups)}; "
                "sample more timesteps with perturbation_sampler before "
                "measuring this bound"
            ),
        )
    folds: list[ErrorBound] = []
    for held_out in groups:
        kept = labels.loc[labels[group_column] != held_out]
        predicted = predict_physics_impact(
            training, fit_physics_surrogate(training, kept)
        )
        folds.append(
            measure_relief_error_bound(
                predicted,
                landed.loc[landed[group_column] == held_out],
                reference=PHYSICS_REFERENCE,
                method=f"held-out {group_column}={held_out!r}",
            )
        )
    return _pool_fold_errors(folds, group_column=group_column, n_groups=len(groups))


#: Measured accuracy of :class:`NetworkImpactPhysicsLookupSurrogate`.
#:
#: Two orders of magnitude tighter than the topology surrogate's 0.470028 on
#: the same 3429 labels, which is the whole argument for fitting against
#: physics: the topology model over-predicts relief by roughly 1.9x
#: systematically, this one is unbiased to six decimals.
PHYSICS_SURROGATE_ERROR_BOUND = ErrorBound(
    metric=RELIEF_ERROR_METRIC,
    units=RELIEF_ERROR_UNITS,
    value=0.002383,
    sample_size=3429,
    method=(
        "Mean absolute error of predicted relief per kW against pandapower "
        "AC finite-difference labels, under grouped leave-one-timestep-out "
        "over the 18 sampled timesteps (each fold refits on the other 17), "
        "pooled over 3429 of 3888 labels whose perturbation landed: scenario "
        "S4, 69 providers x 6 transformer constraints. Measured 2026-08-09 on "
        "instances/default/digital_twin/flexibility/"
        "network_impact_physics_labels.parquet, which is gitignored and so "
        "absent from a clean checkout. Re-derive with "
        "measure_physics_surrogate_error_bound(training, labels)."
    ),
    reference=PHYSICS_REFERENCE,
)


class NetworkImpactPhysicsLookupSurrogate:
    """The physics-fitted lookup surrogate, on the surrogate contract.

    An adaptation, not a reimplementation: :meth:`fit` and :meth:`predict`
    delegate verbatim to :func:`fit_physics_surrogate` and
    :func:`predict_physics_impact`, so
    ``network_impact_physics_predictions.parquet`` is value-identical to the
    pre-contract pipeline.
    """

    DESCRIPTOR = SurrogateDescriptor(
        surrogate_id=NETWORK_IMPACT_PHYSICS_SURROGATE_ID,
        name="Physics-fitted tabular lookup (tabular_physics_lookup_v1)",
        physical_model="pandapower AC power flow (finite-difference labels)",
        error_bound=PHYSICS_SURROGATE_ERROR_BOUND,
    )

    @property
    def descriptor(self) -> SurrogateDescriptor:
        """Return this surrogate's identity and stated error bound.

        Returns:
            The class-level descriptor.
        """
        return self.DESCRIPTOR

    def fit(
        self,
        training: pd.DataFrame,
        labels: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Fit the lookup from finite-difference labels.

        Args:
            training: Feature table from ``build_training_dataset``.
            labels: Finite-difference labels; required, since this surrogate
                is supervised by the physical model.

        Returns:
            The fitted model, as :func:`fit_physics_surrogate` returns it.

        Raises:
            ValueError: If ``labels`` is ``None``. Names the producer of the
                labels rather than only reporting the missing argument.
        """
        if labels is None:
            raise ValueError(
                f"surrogate {NETWORK_IMPACT_PHYSICS_SURROGATE_ID!r} is "
                "supervised and cannot fit without labels; generate them with "
                "perturbation_sampler.build_physics_labels and pass "
                "labels=..."
            )
        return fit_physics_surrogate(training, labels)

    def predict(
        self,
        training: pd.DataFrame,
        model: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Predict provider impact from a fitted lookup.

        Args:
            training: Feature table from ``build_training_dataset``.
            model: The model returned by :meth:`fit`; required.

        Returns:
            Exactly :func:`predict_physics_impact`'s frame.

        Raises:
            ValueError: If ``model`` is ``None``.
        """
        if model is None:
            raise ValueError(
                f"surrogate {NETWORK_IMPACT_PHYSICS_SURROGATE_ID!r} predicts "
                "from a fitted lookup; call fit(training, labels) first and "
                "pass its result as model=..."
            )
        return predict_physics_impact(training, model)

    def verify(
        self,
        predictions: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> ErrorBound:
        """Measure this surrogate against labels for one prediction frame.

        Note:
            This scores whatever frame it is given. When that frame came from
            a lookup fitted on the same labels the result is **in-sample** and
            optimistic; the descriptor's stated bound is the out-of-sample
            number from :func:`measure_physics_surrogate_error_bound`.

        Args:
            predictions: A frame returned by :meth:`predict`.
            labels: Finite-difference labels.

        Returns:
            A freshly measured :class:`ErrorBound` over the supplied data.
        """
        return measure_relief_error_bound(
            predictions,
            labels,
            reference=PHYSICS_REFERENCE,
            method=(
                "Mean absolute error of predicted relief per kW against the "
                "supplied labels, with no hold-out; in-sample when the model "
                "was fitted from these same labels."
            ),
        )

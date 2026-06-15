"""Validation helpers for CLS flexibility-study outputs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import numpy as np
import pandas as pd


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

    _require_columns(
        errors,
        dispatch_timeseries,
        ["t_hours", "p_soft_cls_mw", "p_hard_cls_mw", "p_rebound_mw", "p_limit_trace_mw"],
        "dispatch_timeseries",
    )
    _require_columns(errors, temporal_bounds, ["p_limit_trace"], "temporal_bounds")

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


def _require_columns(
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


__all__ = ["CLSOutputConsistencyResult", "validate_cls_output_consistency"]

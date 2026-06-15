"""Shared metrics for canonical reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_POWER_ENERGY_COLUMNS = {
    "p_soft_cls_mw": "soft_cls_mwh",
    "p_hard_cls_mw": "hard_cls_mwh",
    "p_rebound_mw": "rebound_mwh",
}


def dispatch_timeseries_metrics(
    dispatch: Any,
    *,
    time_column: str = "t_hours",
    energy_columns: dict[str, str] | None = None,
    limit_column: str = "p_limit_trace_mw",
) -> dict[str, Any]:
    """Summarize a dispatch time-series DataFrame or parquet path."""
    if isinstance(dispatch, (str, Path)):
        path = Path(dispatch)
        if not path.exists():
            return {}
        import pandas as pd

        frame = pd.read_parquet(path)
    else:
        frame = dispatch

    if len(frame) < 2 or time_column not in frame:
        return {"n_timesteps": int(len(frame))}

    dt_h = float(frame[time_column].iloc[1] - frame[time_column].iloc[0])
    metrics: dict[str, Any] = {
        "n_timesteps": int(len(frame)),
        "resolution_hours": dt_h,
    }
    for column, key in (energy_columns or DEFAULT_POWER_ENERGY_COLUMNS).items():
        if column in frame:
            metrics[key] = float(frame[column].sum() * dt_h)
    if limit_column in frame:
        metrics["dynamic_limit_min_mw"] = float(frame[limit_column].min())
        metrics["dynamic_limit_max_mw"] = float(frame[limit_column].max())
    return metrics


__all__ = [
    "DEFAULT_POWER_ENERGY_COLUMNS",
    "dispatch_timeseries_metrics",
]

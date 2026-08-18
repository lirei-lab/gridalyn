"""
Generate a JSON report of MV/LV transformer loading by EV scenario.

The report filters the spatial power-flow outputs to 25/0.4 kV transformers,
then summarizes overload counts, headroom, near-overload exposure, and the
highest-loaded transformers for each scenario.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import layout_from_environment  # noqa: E402

DEFAULT_LAYOUT = layout_from_environment(default_root=ROOT)
DEFAULT_TIMESERIES_DIR = DEFAULT_LAYOUT.timeseries
DEFAULT_OUT = DEFAULT_LAYOUT.reports / "mv_lv_transformer_overload_report.json"
DEFAULT_SCENARIOS = ["S0", "S1", "S2", "S3", "S4"]


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _record_from_row(row: pd.Series) -> dict[str, Any]:
    peak_loading = float(row["peak_loading_percent"])
    sn_mva = float(row["sn_mva"])
    return {
        "trafo_idx": int(row["trafo_idx"]),
        "hv_bus": int(row["hv_bus"]),
        "lv_bus": int(row["lv_bus"]),
        "sn_mva": _round(sn_mva, 6),
        "vn_hv_kv": _round(row["vn_hv_kv"], 3),
        "vn_lv_kv": _round(row["vn_lv_kv"], 3),
        "peak_timestamp": str(row["peak_timestamp"]),
        "peak_loading_percent": _round(peak_loading, 4),
        "peak_apparent_power_mva": _round(sn_mva * peak_loading / 100.0, 6),
        "overload_percent_points": _round(max(0.0, peak_loading - 100.0), 4),
        "headroom_to_100_percent_points": _round(100.0 - peak_loading, 4),
        "time_steps_over_80": int(row["time_steps_over_80"]),
        "time_steps_over_90": int(row["time_steps_over_90"]),
        "time_steps_over_100": int(row["time_steps_over_100"]),
    }


def _scenario_report(path: Path, scenario_id: str, top_n: int) -> dict[str, Any]:
    df = pd.read_parquet(path)
    mv_lv = df[
        (df["vn_hv_kv"].round(6) == 25.0) & (df["vn_lv_kv"].round(6) == 0.4)
    ].copy()
    if mv_lv.empty:
        raise RuntimeError(f"{scenario_id}: no MV/LV 25/0.4 kV transformers found.")

    idx = mv_lv.groupby("trafo_idx")["loading_percent"].idxmax()
    peaks = (
        mv_lv.loc[idx]
        .rename(
            columns={
                "timestamp": "peak_timestamp",
                "loading_percent": "peak_loading_percent",
            }
        )
        .sort_values("peak_loading_percent", ascending=False)
        .reset_index(drop=True)
    )

    exposure = mv_lv.groupby("trafo_idx")["loading_percent"].agg(
        time_steps_over_80=lambda s: int((s > 80.0).sum()),
        time_steps_over_90=lambda s: int((s > 90.0).sum()),
        time_steps_over_100=lambda s: int((s > 100.0).sum()),
    )
    peaks = peaks.merge(exposure, on="trafo_idx", how="left")

    total_points = int(len(mv_lv))
    overloaded_points = int((mv_lv["loading_percent"] > 100.0).sum())
    over_90_points = int((mv_lv["loading_percent"] > 90.0).sum())
    over_80_points = int((mv_lv["loading_percent"] > 80.0).sum())

    worst = peaks.iloc[0]
    return {
        "scenario_id": scenario_id,
        "source": str(path.relative_to(ROOT)),
        "n_mv_lv_transformers": int(peaks["trafo_idx"].nunique()),
        "n_timestamps": int(mv_lv["timestamp"].nunique()),
        "time_transformer_points": total_points,
        "overloaded_transformers_count": int(
            (peaks["peak_loading_percent"] > 100.0).sum()
        ),
        "near_overload_transformers_over_90_count": int(
            (peaks["peak_loading_percent"] > 90.0).sum()
        ),
        "warning_transformers_over_80_count": int(
            (peaks["peak_loading_percent"] > 80.0).sum()
        ),
        "overloaded_time_transformer_points": overloaded_points,
        "near_overload_time_transformer_points_over_90": over_90_points,
        "warning_time_transformer_points_over_80": over_80_points,
        "overloaded_time_transformer_share": _round(
            overloaded_points / total_points, 8
        ),
        "near_overload_time_transformer_share_over_90": _round(
            over_90_points / total_points, 8
        ),
        "warning_time_transformer_share_over_80": _round(
            over_80_points / total_points, 8
        ),
        "max_loading_percent": _round(worst["peak_loading_percent"], 4),
        "max_overload_percent_points": _round(
            max(0.0, float(worst["peak_loading_percent"]) - 100.0), 4
        ),
        "min_headroom_to_100_percent_points": _round(
            100.0 - float(worst["peak_loading_percent"]), 4
        ),
        "worst_transformer": _record_from_row(worst),
        "top_transformers": [
            _record_from_row(row) for _, row in peaks.head(top_n).iterrows()
        ],
    }


def build_report(
    timeseries_dir: Path, scenarios: list[str], out_path: Path, top_n: int
) -> None:
    scenario_reports = []
    for scenario_id in scenarios:
        path = timeseries_dir / f"{scenario_id}_powerflow_transformers.parquet"
        scenario_reports.append(_scenario_report(path, scenario_id, top_n))

    any_overloaded = any(
        item["overloaded_transformers_count"] > 0 for item in scenario_reports
    )
    max_item = max(scenario_reports, key=lambda item: item["max_loading_percent"])
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": "MV/LV Transformer Overload Report",
        "scope": {
            "transformer_filter": "vn_hv_kv == 25.0 and vn_lv_kv == 0.4",
            "overloaded_definition": "loading_percent > 100",
            "near_overload_definition": "loading_percent > 90",
            "warning_definition": "loading_percent > 80",
            "scenarios": scenarios,
        },
        "overall": {
            "any_overloaded_mv_lv_transformer": any_overloaded,
            "max_loading_percent": max_item["max_loading_percent"],
            "max_loading_scenario": max_item["scenario_id"],
            "max_overload_percent_points": max_item["max_overload_percent_points"],
            "min_headroom_to_100_percent_points": max_item[
                "min_headroom_to_100_percent_points"
            ],
            "interpretation": (
                "No MV/LV transformer exceeds 100% loading in the simulated "
                "S0-S4 scenarios."
                if not any_overloaded
                else "At least one MV/LV transformer exceeds 100% loading in "
                "the simulated scenarios."
            ),
        },
        "scenarios": scenario_reports,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(f"Wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Report MV/LV transformer overloads.")
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scenarios", nargs="+", default=DEFAULT_SCENARIOS)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    build_report(args.timeseries_dir, args.scenarios, args.out, args.top_n)


if __name__ == "__main__":
    main()

"""Verify per-building EV charging time series for digital-twin scenarios.

Backs ``gridalyn twin verify-timeseries``. The checks are unchanged from the
version that raised ``SystemExit`` inline; :func:`verify_ev_timeseries` now
returns its finding and ``main`` decides what to do with it, which is what
makes the verifier itself verifiable.

Short-circuit order is preserved: the first failure stops the run, because the
later checks index frames the earlier ones establish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout  # noqa: E402

DEFAULT_LAYOUT = ArtifactLayout(ROOT)
BASE_DIR = DEFAULT_LAYOUT.base
SCENARIO_DIR = DEFAULT_LAYOUT.scenarios
TIMESERIES_DIR = DEFAULT_LAYOUT.timeseries


class VerificationFailed(Exception):
    """One verification check failed. Carries the located message."""


_REQUIRED_COLUMNS = frozenset(
    {
        "timestamp",
        "scenario_id",
        "building_id",
        "load_id",
        "pandapower_load",
        "p_ev_kw",
    }
)


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def _check_frame_shape(
    scenario_id: str,
    frame: pd.DataFrame,
    buildings: pd.DataFrame,
    expected_rows: int,
    expected_timestamps: int,
) -> None:
    """Check one scenario frame's columns, size and identity coverage.

    Raises:
        VerificationFailed: On the first structural problem, because the value
            checks below index columns this establishes.
    """
    missing = _REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise VerificationFailed(f"{scenario_id} missing columns {sorted(missing)}.")
    if "area_m2" in frame.columns:
        raise VerificationFailed(
            f"{scenario_id} EV time series must not contain area_m2."
        )
    if len(frame) != expected_rows:
        raise VerificationFailed(
            f"{scenario_id} expected {expected_rows} rows, found {len(frame)}."
        )
    if frame["timestamp"].nunique() != expected_timestamps:
        raise VerificationFailed(f"{scenario_id} timestamp count mismatch.")
    if set(frame["building_id"].unique()) != set(buildings["building_id"]):
        raise VerificationFailed(f"{scenario_id} building ids do not match base twin.")


def _check_load_values(
    scenario_id: str,
    frame: pd.DataFrame,
    active_ids: set,
    inactive_ids: set,
) -> None:
    """Check that EV load is non-negative and lands only where it should.

    Raises:
        VerificationFailed: On the first violation.
    """
    if (frame["p_ev_kw"] < -1e-9).any():
        raise VerificationFailed(f"{scenario_id} has negative EV load.")
    inactive = frame.loc[frame["building_id"].isin(inactive_ids), "p_ev_kw"]
    if not np.isclose(float(inactive.abs().max()), 0.0, atol=1e-9):
        raise VerificationFailed(
            f"{scenario_id} inactive buildings have nonzero EV load."
        )
    active = frame.loc[frame["building_id"].isin(active_ids), "p_ev_kw"]
    if active_ids and float(active.max()) <= 0.0:
        raise VerificationFailed(f"{scenario_id} active EV buildings never charge.")


def _check_monotonic(
    scenario_id: str,
    total_by_time: pd.Series,
    peak: float,
    previous_total: pd.Series | None,
    previous_peak: float | None,
) -> None:
    """Aggregate EV load must not fall as adoption rises.

    Raises:
        VerificationFailed: If either the pointwise series or the peak drops.
    """
    if (
        previous_total is not None
        and (total_by_time.values + 1e-6 < previous_total.values).any()
    ):
        raise VerificationFailed(
            f"aggregate EV load is not pointwise monotonic at {scenario_id}."
        )
    if previous_peak is not None and peak + 1e-6 < previous_peak:
        raise VerificationFailed(f"peak EV load is not monotonic at {scenario_id}.")


def verify_ev_timeseries(
    *,
    base_dir: Path = BASE_DIR,
    scenario_dir: Path = SCENARIO_DIR,
    timeseries_dir: Path = TIMESERIES_DIR,
) -> dict[str, Any]:
    """Verify the per-building EV time series without printing or exiting.

    Args:
        base_dir: Directory holding the canonical base artifacts.
        scenario_dir: Directory holding the EV assignment table.
        timeseries_dir: Directory holding the per-scenario EV load frames.

    Returns:
        ``{"valid": bool, "error": str | None, "lines": list[str]}``.
    """
    lines: list[str] = []
    try:
        buildings = pd.read_parquet(base_dir / "buildings.parquet")
        assignments = pd.read_parquet(scenario_dir / "ev_assignments.parquet")
        summary = _load_json(timeseries_dir / "ev_load_summary.json")

        resolution = int(summary["resolution_minutes"])
        expected_timestamps = int(24 * 60 / resolution)
        expected_rows = len(buildings) * expected_timestamps

        previous_total: pd.Series | None = None
        previous_peak: float | None = None
        totals: dict[str, pd.Series] = {}

        for item in summary["scenarios"]:
            scenario_id = item["scenario_id"]
            frame = pd.read_parquet(timeseries_dir / f"{scenario_id}_ev_load.parquet")
            rows = assignments.loc[assignments["scenario_id"] == scenario_id]
            active_ids = set(rows.loc[rows["has_ev"], "building_id"])
            inactive_ids = set(rows.loc[~rows["has_ev"], "building_id"])

            _check_frame_shape(
                scenario_id, frame, buildings, expected_rows, expected_timestamps
            )
            _check_load_values(scenario_id, frame, active_ids, inactive_ids)

            total_by_time = frame.groupby("timestamp", sort=True)["p_ev_kw"].sum()
            peak = float(total_by_time.max())
            _check_monotonic(
                scenario_id, total_by_time, peak, previous_total, previous_peak
            )
            totals[scenario_id] = total_by_time
            previous_total, previous_peak = total_by_time, peak

            energy = float(total_by_time.sum() * resolution / 60.0)
            lines.append(
                f"{scenario_id}: rows={len(frame):7d} | active={len(active_ids):4d} | "
                f"peak={peak:8.2f} kW | energy={energy:9.2f} kWh"
            )

        if not np.isclose(float(totals["S0"].max()), 0.0, atol=1e-9):
            raise VerificationFailed("S0 must have zero EV load.")
    except VerificationFailed as failure:
        return {"valid": False, "error": str(failure), "lines": lines}
    return {"valid": True, "error": None, "lines": lines}


def main() -> None:
    """Run the verification and report it, exiting non-zero on failure."""
    report = verify_ev_timeseries()
    print("=== EV Time-Series Verification ===")
    for line in report["lines"]:
        print(line)
    if not report["valid"]:
        raise SystemExit(f"ERROR: {report['error']}")
    print(
        "OK: EV time series are aligned, area-independent, and monotonic "
        "across scenarios."
    )


if __name__ == "__main__":
    main()

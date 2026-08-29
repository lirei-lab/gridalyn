"""Verify digital-twin EV powerflow outputs.

Backs ``gridalyn twin verify-powerflow``. The checks are unchanged from the
version that raised ``SystemExit`` inline; :func:`verify_scenarios` now returns
its finding and ``main`` decides what to do with it, which is what makes the
verifier itself verifiable.

Short-circuit order is preserved: the first failure stops the run, because the
later checks read frames and summaries the earlier ones establish.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout  # noqa: E402

DEFAULT_LAYOUT = ArtifactLayout(ROOT)
BASE_DIR = DEFAULT_LAYOUT.base
TIMESERIES_DIR = DEFAULT_LAYOUT.timeseries


class VerificationFailed(Exception):
    """One verification check failed. Carries the located message."""


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def _check_row_counts(
    scenario_id: str,
    frames: dict[str, pd.DataFrame],
    base_counts: dict[str, int],
    n_timestamps: int,
) -> None:
    """Every result frame must hold one row per element per timestamp.

    Raises:
        VerificationFailed: On a mismatch, naming both dicts so the offending
            frame is visible rather than only that something differs.
    """
    expected = {key: n_timestamps * count for key, count in base_counts.items()}
    actual = {key: len(frame) for key, frame in frames.items()}
    if actual != expected:
        raise VerificationFailed(
            f"{scenario_id} row counts mismatch. expected={expected}, "
            f"actual={actual}"
        )


def _check_timestamps_aligned(
    scenario_id: str, frames: dict[str, pd.DataFrame]
) -> None:
    """All four frames must cover the same instants.

    Raises:
        VerificationFailed: If any frame covers a different timestamp set.
    """
    stamps = {frozenset(frame["timestamp"].unique()) for frame in frames.values()}
    if len(stamps) != 1:
        raise VerificationFailed(f"{scenario_id} timestamp sets are not aligned.")


def _check_power_decomposition(scenario_id: str, power: pd.DataFrame) -> None:
    """Total power must be exactly its declared parts.

    Raises:
        VerificationFailed: If the identity breaks, EV load is negative, or the
            frame carries area, which the overlays are required to ignore.
    """
    if "area_m2" in power.columns:
        raise VerificationFailed(
            f"{scenario_id} powerflow power output must not contain area_m2."
        )
    residual = (
        (power["p_building_mw"] + power["p_ev_mw"] - power["p_total_mw"]).abs().max()
    )
    if float(residual) > 1e-8:
        raise VerificationFailed(f"{scenario_id} violates p_total = p_building + p_ev.")
    if (power["p_ev_mw"] < -1e-12).any():
        raise VerificationFailed(f"{scenario_id} has negative EV load.")


def _check_baseline_is_ev_free(power: pd.DataFrame, summary: dict) -> None:
    """S0 is the no-EV reference and must carry no EV load at all.

    Raises:
        VerificationFailed: If the baseline carries EV load in either the
            frame or its summary.
    """
    if float(power["p_ev_mw"].abs().max()) > 1e-12:
        raise VerificationFailed("S0 must have zero EV load.")
    if abs(float(summary["ev_peak_mw"])) > 1e-12:
        raise VerificationFailed("S0 summary must have zero EV peak.")


def _check_monotonic(scenario_id: str, summary: dict, previous: dict | None) -> None:
    """Rising adoption must not lower load or raise the minimum voltage.

    Raises:
        VerificationFailed: On the first non-monotone quantity.
    """
    if previous is None:
        return
    if summary["ev_peak_mw"] + 1e-9 < previous["ev_peak_mw"]:
        raise VerificationFailed(f"{scenario_id} EV peak is not monotonic.")
    if summary["ext_grid_peak_mw"] + 1e-6 < previous["ext_grid_peak_mw"]:
        raise VerificationFailed(f"{scenario_id} ext-grid peak is not monotonic.")
    if summary["v_min_pu"] > previous["v_min_pu"] + 1e-6:
        raise VerificationFailed(
            f"{scenario_id} minimum voltage unexpectedly improved."
        )


def verify_scenarios(
    scenarios: list[str],
    timeseries_dir: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Verify EV powerflow outputs without printing or exiting.

    Args:
        scenarios: Scenario ids to verify, in rising-adoption order.
        timeseries_dir: Directory holding the per-scenario powerflow results.
        base_dir: Directory holding the canonical base artifacts.

    Returns:
        ``{"valid": bool, "error": str | None, "lines": list[str]}``.
    """
    lines: list[str] = []
    try:
        base_counts = {
            "nodes": len(pd.read_parquet(base_dir / "grid_buses.parquet")),
            "lines": len(pd.read_parquet(base_dir / "grid_lines.parquet")),
            "transformers": len(
                pd.read_parquet(base_dir / "grid_transformers.parquet")
            ),
            "power": len(pd.read_parquet(base_dir / "buildings.parquet")),
        }
        previous: dict | None = None
        for scenario_id in scenarios:
            summary = _load_json(
                timeseries_dir / f"{scenario_id}_powerflow_summary.json"
            )
            frames = {
                key: pd.read_parquet(
                    timeseries_dir / f"{scenario_id}_powerflow_{suffix}.parquet"
                )
                for key, suffix in (
                    ("nodes", "nodes"),
                    ("lines", "lines"),
                    ("transformers", "transformers"),
                    ("power", "power"),
                )
            }
            _check_row_counts(
                scenario_id, frames, base_counts, int(summary["n_timestamps"])
            )
            _check_timestamps_aligned(scenario_id, frames)
            _check_power_decomposition(scenario_id, frames["power"])
            if scenario_id == "S0":
                _check_baseline_is_ev_free(frames["power"], summary)
            _check_monotonic(scenario_id, summary, previous)
            previous = summary
            lines.append(
                f"{scenario_id}: ext_peak={summary['ext_grid_peak_mw']:.2f} MW | "
                f"ev_peak={summary['ev_peak_mw']:.2f} MW | "
                f"v_min={summary['v_min_pu']:.4f} | "
                f"line_max={summary['line_max_loading_percent']:.2f}% | "
                f"trafo_max={summary['trafo_max_loading_percent']:.2f}%"
            )
    except VerificationFailed as failure:
        return {"valid": False, "error": str(failure), "lines": lines}
    return {"valid": True, "error": None, "lines": lines}


def main() -> None:
    """Run the verification and report it, exiting non-zero on failure."""
    parser = argparse.ArgumentParser(
        description="Verify digital-twin EV powerflow outputs."
    )
    parser.add_argument("--scenarios", nargs="+", default=["S0", "S1"])
    parser.add_argument("--timeseries-dir", type=Path, default=TIMESERIES_DIR)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR)
    args = parser.parse_args()
    report = verify_scenarios(args.scenarios, args.timeseries_dir, args.base_dir)
    print("=== EV Powerflow Verification ===")
    for line in report["lines"]:
        print(line)
    if not report["valid"]:
        raise SystemExit(f"ERROR: {report['error']}")
    print(
        "OK: EV powerflow outputs are aligned and satisfy "
        "p_total = p_building + p_ev."
    )


if __name__ == "__main__":
    main()

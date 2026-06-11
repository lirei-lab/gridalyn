"""Pinned TMY weather input for the EV capacity limitation study.

The study weather is committed at ``inputs/tmy_trois_rivieres.csv`` (PVGIS
SARAH-3 TMY for Trois-Rivières, QC) so every pipeline stage and every machine
reproduces the exact published study day. Do NOT replace this loader with
``download_tmy()``: its silent synthetic fallback changes the study day and
invalidates the manuscript numbers.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMY_INPUT_PATH = PROJECT_ROOT / "inputs" / "tmy_trois_rivieres.csv"
TMY_SOURCE = "pvgis_sarah3 (pinned project input)"


def load_project_tmy() -> pd.DataFrame:
    """Return the pinned 8760-row study TMY with a tz-aware DatetimeIndex."""
    tmy = pd.read_csv(TMY_INPUT_PATH, index_col="timestamp")
    # The TMY mixes months from different years, so offsets may alternate
    # between EST and EDT; parse through UTC to keep a uniform tz-aware index.
    tmy.index = pd.to_datetime(tmy.index, utc=True).tz_convert("America/Toronto")
    tmy.attrs["gridalyn_weather_source"] = TMY_SOURCE
    return tmy


__all__ = ["TMY_INPUT_PATH", "TMY_SOURCE", "load_project_tmy"]

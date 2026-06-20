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

# The committed-CSV pin is the ONLY weather source on the reproducible path. A
# weather ``source`` of ``"auto"`` would let ``download_tmy`` silently cross to a
# live PVGIS fetch (or its synthetic fallback) and change the study day, so it is
# rejected here as a belt-and-suspenders guard (D-08).
PINNED_WEATHER_SOURCE = "pinned_csv"
_FORBIDDEN_WEATHER_SOURCES = frozenset({"auto"})


def guard_pinned_weather_source(source: str) -> str:
    """Reject a non-pinned weather ``source`` on the reproducible study path.

    Args:
        source: The weather source a caller is about to resolve.

    Returns:
        The validated ``source`` unchanged when it is not a forbidden value.

    Raises:
        ValueError: If ``source`` is ``"auto"`` — silently switching to a live
            PVGIS fetch would invalidate the committed study numbers; the study
            must load the pinned CSV via :func:`load_project_tmy` instead.
    """
    if source in _FORBIDDEN_WEATHER_SOURCES:
        raise ValueError(
            f"weather source {source!r} is forbidden on the reproducible "
            f"flexibility_cls path (it would silently fetch live PVGIS and "
            f"change the study day); load the pinned CSV via load_project_tmy()."
        )
    return source


def load_project_tmy() -> pd.DataFrame:
    """Return the pinned 8760-row study TMY with a tz-aware DatetimeIndex."""
    tmy = pd.read_csv(TMY_INPUT_PATH, index_col="timestamp")
    # The TMY mixes months from different years, so offsets may alternate
    # between EST and EDT; parse through UTC to keep a uniform tz-aware index.
    tmy.index = pd.to_datetime(tmy.index, utc=True).tz_convert("America/Toronto")
    tmy.attrs["gridalyn_weather_source"] = TMY_SOURCE
    return tmy


__all__ = [
    "PINNED_WEATHER_SOURCE",
    "TMY_INPUT_PATH",
    "TMY_SOURCE",
    "guard_pinned_weather_source",
    "load_project_tmy",
]

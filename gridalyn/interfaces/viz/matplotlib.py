"""Reusable Matplotlib helpers for project figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def format_hour_label(hour: float) -> str:
    """Format a decimal hour as an HH:MM label."""
    h = int(hour % 24)
    m = int(round((hour % 1) * 60))
    if m == 60:
        h = (h + 1) % 24
        m = 0
    return f"{h:02d}:{m:02d}"


def apply_hour_axis(
    ax: Any,
    *,
    start: float = 0.0,
    end: float = 28.0,
    step: float = 4.0,
    label: str = "Time of Day [HH:MM]",
    fontsize: int = 14,
) -> None:
    """Apply a common hour-of-day x-axis to a Matplotlib axis."""
    import numpy as np
    import matplotlib.ticker as ticker

    ax.set_xlim(start, end)
    ax.set_xticks(np.arange(start, end + 1e-9, step))
    ax.xaxis.set_major_formatter(
        ticker.FuncFormatter(lambda value, _pos: format_hour_label(value))
    )
    if label:
        ax.set_xlabel(label, fontsize=fontsize)


def style_timeseries_axis(
    ax: Any,
    *,
    grid: bool = True,
    grid_style: str = "--",
    grid_alpha: float = 0.4,
    hide_top_right: bool = False,
) -> None:
    """Apply a restrained default style for project time-series figures."""
    if grid:
        ax.grid(True, linestyle=grid_style, alpha=grid_alpha)
    if hide_top_right:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def save_figure_pair(
    fig: Any,
    output_path: Path | str,
    *,
    dpi: int = 200,
    pdf: bool = True,
    bbox_inches: str = "tight",
) -> dict[str, Path]:
    """Save a figure to PNG and, by default, matching PDF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    if pdf:
        pdf_path = output_path.with_suffix(".pdf")
        fig.savefig(pdf_path, bbox_inches=bbox_inches)
        written["pdf"] = pdf_path
    fig.savefig(output_path, dpi=dpi, bbox_inches=bbox_inches)
    written[output_path.suffix.removeprefix(".") or "figure"] = output_path
    return written


__all__ = [
    "apply_hour_axis",
    "format_hour_label",
    "save_figure_pair",
    "style_timeseries_axis",
]

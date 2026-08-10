"""Reusable pandapower artifact writers for Gridalyn projects."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import pandapower as pp
import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation.observation.contract import observe_network

# Module-level default so the Path is not constructed in an argument default
# (bugbear B008). Safe to share: Path is immutable, and this is already the
# single object every caller has received since the default was introduced.
_DEFAULT_MATPLOTLIB_CACHE_DIR = Path("outputs/cache/matplotlib")


def configure_headless_matplotlib(
    cache_dir: Path | str = _DEFAULT_MATPLOTLIB_CACHE_DIR,
) -> None:
    """Configure Matplotlib for workflow scripts that run without a display."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path(cache_dir).resolve()))
    import matplotlib

    matplotlib.use("Agg")


def _result_table(net: pp.pandapowerNet, element: str) -> pd.DataFrame:
    table = getattr(net, element)
    result = getattr(net, f"res_{element}", pd.DataFrame())
    if isinstance(result, pd.DataFrame) and not result.empty:
        return table.join(result, how="left", rsuffix="_result")
    return table.copy()


def write_pandapower_element_tables(
    net: pp.pandapowerNet,
    output_dir: Path | str,
    *,
    elements: Iterable[str] = ("bus", "line", "load"),
) -> dict[str, Path]:
    """Write standard pandapower element/result tables and return their paths."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for element in elements:
        if not hasattr(net, element):
            continue
        plural = f"{element}es" if element == "bus" else f"{element}s"
        path = target / f"{plural}.csv"
        _result_table(net, element).to_csv(path, index_label=f"{element}_id")
        paths[plural] = path
    return paths


def _optional_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_pandapower_summary(
    net: pp.pandapowerNet,
    *,
    network: str | None = None,
    simulation_engine: str = "pandapower",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, stable summary for a solved pandapower network."""
    observation = observe_network(net)
    summary: dict[str, Any] = {
        "simulation_engine": simulation_engine,
        "bus_count": int(len(getattr(net, "bus", []))),
        "line_count": int(len(getattr(net, "line", []))),
        "load_count": int(len(getattr(net, "load", []))),
        "slack_count": int(len(getattr(net, "ext_grid", []))),
        "sgen_count": int(len(getattr(net, "sgen", []))),
        "transformer_count": int(len(getattr(net, "trafo", []))),
        "converged": observation.converged,
        "total_load_mw": float(net.load.p_mw.sum()) if hasattr(net, "load") else 0.0,
        "total_load_mvar": (
            float(net.load.q_mvar.sum()) if hasattr(net, "load") else 0.0
        ),
        "total_generation_mw": (
            float(net.sgen.p_mw.sum())
            if hasattr(net, "sgen") and len(net.sgen)
            else 0.0
        ),
        # An unobserved quantity reduces to nan and an unobserved loss column
        # to None; _optional_float maps both to None, which is what the
        # per-table isinstance/column guards this replaces produced. The one
        # case where they differ -- a reported but empty loss column, which
        # sums to 0.0 rather than None -- the contract preserves.
        "min_voltage_pu": _optional_float(observation.min_voltage_pu),
        "max_voltage_pu": _optional_float(observation.max_voltage_pu),
        "max_line_loading_percent": _optional_float(
            observation.max_line_loading_percent
        ),
        "total_line_loss_mw": _optional_float(observation.total_line_loss_mw),
    }
    if network is not None:
        summary["network"] = network
    if extra:
        summary.update(extra)
    return summary


def write_voltage_profile_figure(
    net: pp.pandapowerNet,
    path: Path | str,
    *,
    title: str,
    lower_limit_pu: float | None = 0.95,
    upper_limit_pu: float | None = 1.05,
    xlabel: str = "Bus",
    ylabel: str = "Voltage magnitude [p.u.]",
    figsize: tuple[float, float] = (8.5, 4.6),
) -> Path:
    """Write a standard feeder voltage-profile figure."""
    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    figure_path = Path(path)
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    voltage = observe_network(net).voltage_frame()

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8)
    if lower_limit_pu is not None:
        ax.axhline(
            lower_limit_pu,
            color="#c0392b",
            linestyle="--",
            linewidth=1.2,
            label=f"{lower_limit_pu:.2f} p.u.",
        )
    if upper_limit_pu is not None:
        ax.axhline(
            upper_limit_pu,
            color="#7f8c8d",
            linestyle=":",
            linewidth=1.2,
            label=f"{upper_limit_pu:.2f} p.u.",
        )
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.32)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def write_powerflow_report(
    path: Path | str,
    *,
    metadata: ReportMetadata,
    net: pp.pandapowerNet,
    inputs: list[dict[str, Any]] | None = None,
    artifacts: Iterable[Path | str | dict[str, Any]] = (),
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a standard Gridalyn report for a pandapower power-flow run."""
    artifact_refs = [
        artifact if isinstance(artifact, dict) else file_reference(artifact)
        for artifact in artifacts
    ]
    report_summary = build_pandapower_summary(net)
    if summary:
        report_summary.update(summary)
    valid = bool(getattr(net, "converged", False))
    report_validation = validation or {
        "valid": valid,
        "errors": [] if valid else ["pandapower power flow did not converge"],
        "warnings": [],
    }
    return write_report(
        path,
        metadata=metadata,
        inputs=inputs or [],
        artifacts=artifact_refs,
        summary=report_summary,
        validation=report_validation,
    )


__all__ = [
    "build_pandapower_summary",
    "configure_headless_matplotlib",
    "write_pandapower_element_tables",
    "write_powerflow_report",
    "write_voltage_profile_figure",
]

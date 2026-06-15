"""Lightweight developer visualizations.

The production dashboard consumes digital-twin catalog and Parquet artifacts.
This namespace only exposes Folium-based inspection maps for synthetic network
generation and tutorial/debug workflows.
"""

__all__ = [
    "GridPlotter",
    "apply_hour_axis",
    "format_hour_label",
    "save_figure_pair",
    "style_timeseries_axis",
]


def __getattr__(name: str):
    if name == "GridPlotter":
        from gridalyn.interfaces.viz.interactive import GridPlotter

        globals()[name] = GridPlotter
        return GridPlotter
    if name in {
        "apply_hour_axis",
        "format_hour_label",
        "save_figure_pair",
        "style_timeseries_axis",
    }:
        from gridalyn.interfaces.viz import matplotlib as _matplotlib

        value = getattr(_matplotlib, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.interfaces.viz' has no attribute {name!r}")

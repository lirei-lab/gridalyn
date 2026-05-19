"""Lightweight developer visualizations.

The production dashboard consumes digital-twin catalog and Parquet artifacts.
This namespace only exposes Folium-based inspection maps for synthetic network
generation and tutorial/debug workflows.
"""

__all__ = ["GridPlotter"]


def __getattr__(name: str):
    if name == "GridPlotter":
        from gridalyn.interfaces.viz.interactive import GridPlotter

        globals()[name] = GridPlotter
        return GridPlotter
    raise AttributeError(f"module 'gridalyn.interfaces.viz' has no attribute {name!r}")

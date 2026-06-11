"""Project bindings for the Gridalyn prosumer-battery demo model."""

from __future__ import annotations

from gridalyn.projects import load_prosumer_assets, load_radial_feeder_spec
from gridalyn.simulation import build_radial_pandapower_feeder


FEEDER_SPEC = load_radial_feeder_spec("project.yaml")
LOADS_MW = FEEDER_SPEC.loads_mw
PROSUMER_ASSETS = load_prosumer_assets("project.yaml")


def build_synthetic_feeder():
    """Create the project feeder declared in project.yaml."""
    return build_radial_pandapower_feeder(FEEDER_SPEC)


__all__ = [
    "FEEDER_SPEC",
    "LOADS_MW",
    "PROSUMER_ASSETS",
    "build_synthetic_feeder",
]

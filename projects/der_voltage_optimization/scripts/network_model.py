"""Project bindings for the Gridalyn DER voltage-optimization demo model."""

from __future__ import annotations

import dataclasses

from gridalyn.projects import (
    load_der_dispatch_assets,
    load_generated_bus_loads_mw,
    load_radial_feeder_spec,
)
from gridalyn.simulation import build_radial_pandapower_feeder


_DECLARED_SPEC = load_radial_feeder_spec("project.yaml")
# Diversify per-bus shares with the generated coincident-peak snapshot while
# keeping the system total anchored to the declared loadsMw.
FEEDER_SPEC = dataclasses.replace(
    _DECLARED_SPEC,
    loads_mw=load_generated_bus_loads_mw(
        "project.yaml", anchor_loads_mw=_DECLARED_SPEC.loads_mw
    ),
)
LOADS_MW = FEEDER_SPEC.loads_mw
DER_ASSETS = load_der_dispatch_assets("project.yaml")


def build_der_feeder():
    """Create the project feeder declared in project.yaml."""
    return build_radial_pandapower_feeder(FEEDER_SPEC)

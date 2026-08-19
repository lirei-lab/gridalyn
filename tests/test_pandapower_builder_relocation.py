"""Gate the relocation of PandapowerGridBuilder into gridalyn.twin.

Phase 28 (Milestone 14) moved ``PandapowerGridBuilder`` from
``gridalyn.simulation.simulators.powerflow.builder`` down to
``gridalyn.twin.adapters.pandapower_builder`` -- a pure file move, no logic
change, since the class's only real dependency (``PowerGridGraph``) already
lived in ``twin``. Four behaviours are held here:

(a) the new import path resolves to the class;
(b) the old import path is gone, not duplicated;
(c) ``synthetic_network.py``'s orchestrator uses the twin-native class, not a
    second one wearing the same name;
(d) the constructed network's structure is unchanged -- exact table shapes
    for a deterministic fixture, so a future edit to this exact construction
    path cannot silently drift without this test noticing.
"""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn.simulation.simulators.powerflow.synthetic_network import (
    build_synthetic_network_from_geojson,
)
from gridalyn.twin.adapters.pandapower_builder import PandapowerGridBuilder
from gridalyn.twin.geoprocess import FakeGeoJSONGenerator


def test_the_new_path_resolves_the_class() -> None:
    """(a) The twin-native import path is real."""
    assert (
        PandapowerGridBuilder.__module__ == "gridalyn.twin.adapters.pandapower_builder"
    )


def test_the_old_path_no_longer_resolves() -> None:
    """(b) The old path is gone, not left as a second copy."""
    import importlib

    try:
        importlib.import_module("gridalyn.simulation.simulators.powerflow.builder")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(
            "gridalyn.simulation.simulators.powerflow.builder still imports -- "
            "the relocation should have removed it, not duplicated it"
        )


def test_synthetic_network_uses_the_twin_native_builder() -> None:
    """(c) The orchestrator binds the twin-native class, not a look-alike."""
    import gridalyn.simulation.simulators.powerflow.synthetic_network as module

    assert module.PandapowerGridBuilder is PandapowerGridBuilder


def test_constructed_network_structure_is_unchanged(tmp_path: Path) -> None:
    """(d) A deterministic fixture pins the exact resulting table shapes."""
    footprints_path = tmp_path / "buildings.geojson"
    out_dir = tmp_path / "synthetic_network"
    generator = FakeGeoJSONGenerator(grid_size=3, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()), encoding="utf-8"
    )

    result = build_synthetic_network_from_geojson(
        footprints_path=footprints_path,
        config_path=Path("configs/grid/config.json"),
        out_dir=out_dir,
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=False,
    )
    net = result.net

    assert len(net.bus) == 14
    assert len(net.line) == 11
    assert len(net.trafo) == 2
    assert len(net.load) == 9
    assert len(net.ext_grid) == 1
    assert len(net.bus_geodata) == 14

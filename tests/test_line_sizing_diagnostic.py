from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridalyn.foundation.platform.capabilities import missing_capability_modules

_SIM_MISSING = missing_capability_modules("sim")

requires_sim = pytest.mark.skipif(
    bool(_SIM_MISSING),
    reason="requires the 'sim' extra (pandapower)",
)

_EXPECTED_ROW_KEYS = {
    "idx",
    "level",
    "max_i_ka",
    "length_km",
    "downstream_load_mw",
    "downstream_count",
    "loading_percent",
}


@requires_sim
def test_line_sizing_diagnostic_structure_and_constant_rating(
    tmp_path: Path,
) -> None:
    from gridalyn.simulation import LineSizingResult, analyze_line_sizing
    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )
    from gridalyn.twin.geoprocess import FakeGeoJSONGenerator

    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=3, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )
    config = json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))

    build = build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=config,
        out_dir=tmp_path / "network",
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=True,
    )
    net = build.net

    # Read-only snapshot before the diagnostic runs.
    line_count_before = len(net.line)
    max_i_ka_before = net.line["max_i_ka"].tolist()

    result = analyze_line_sizing(net)

    assert isinstance(result, LineSizingResult)
    assert result.rows, "expected at least one on-tree line row"
    for row in result.rows:
        assert set(row.keys()) == _EXPECTED_ROW_KEYS

    assert result.per_level, "expected per-level aggregates"
    for aggregate in result.per_level.values():
        # Headline finding: max_i_ka is constant within each voltage level.
        assert len(aggregate["distinct_max_i_ka"]) == 1

    assert "downstream_load_vs_max_i_ka" in result.correlations

    # Read-only guarantee: the input net is untouched.
    assert len(net.line) == line_count_before
    assert net.line["max_i_ka"].tolist() == max_i_ka_before

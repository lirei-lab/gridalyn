from __future__ import annotations

import json
from pathlib import Path

from gridalyn.simulation.simulators.powerflow.synthetic_network import (
    build_synthetic_network_from_config,
    build_synthetic_network_from_geojson,
)
from gridalyn.twin.geoprocess import FakeGeoJSONGenerator


def test_synthetic_network_generator_builds_report_and_cache(tmp_path: Path) -> None:
    footprints_path = tmp_path / "buildings.geojson"
    out_dir = tmp_path / "synthetic_network"
    generator = FakeGeoJSONGenerator(grid_size=3, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )

    result = build_synthetic_network_from_geojson(
        footprints_path=footprints_path,
        config_path=Path("configs/grid/config.json"),
        out_dir=out_dir,
        clustering_crs="auto",
        write_cache=True,
        run_powerflow=False,
    )

    report = result.validation_report

    assert report["valid"] is True
    assert report["source"]["footprints_path"].endswith("buildings.geojson")
    assert report["coordinate_reference_systems"]["geographic_crs"] == "EPSG:4326"
    assert report["coordinate_reference_systems"]["clustering_crs"]
    assert report["counts"]["buildings"] == 9
    assert report["counts"]["pandapower_loads"] == 9
    assert report["topology"]["isolated_nodes_total"] == 0
    assert result.report_path == out_dir / "synthetic_network_validation.json"
    assert result.report_path.exists()
    assert (out_dir / "pg_graph_cache.pkl").exists()
    assert (out_dir / "pp_net_cache.pkl").exists()
    assert len(result.net.load) == 9


def test_synthetic_network_generator_can_run_powerflow_on_small_case(
    tmp_path: Path,
) -> None:
    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=2, seed=13, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )

    result = build_synthetic_network_from_geojson(
        footprints_path=footprints_path,
        config_path=Path("configs/grid/config.json"),
        out_dir=tmp_path / "network",
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=True,
    )

    assert result.validation_report["powerflow"]["attempted"] is True
    assert result.validation_report["powerflow"]["converged"] is True
    assert result.net.converged is True


def test_synthetic_network_generator_accepts_runtime_config_mapping(
    tmp_path: Path,
) -> None:
    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=2, seed=17, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )
    config = json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))

    result = build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=config,
        config_source="test_runtime_config",
        out_dir=tmp_path / "network",
        write_cache=True,
    )

    assert result.validation_report["valid"] is True
    assert result.validation_report["source"]["config_path"] == "test_runtime_config"
    assert result.validation_report["source"]["config_sha256"]
    assert (tmp_path / "network" / "pp_net_cache.pkl").exists()

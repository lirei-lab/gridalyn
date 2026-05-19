from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from gridalyn.adapters.geojson import (
    FakeGeoJSONGenerator,
    GeoProcessor,
    extract_building_data,
    validate_geojson,
)
from gridalyn.core.graph import PowerGridGraph
from gridalyn.geoprocess import FakeGeoJSONGenerator as LegacyFakeGeoJSONGenerator
from examples.data_acquisition.prepare_microsoft_building_footprints import (
    prepare_footprints,
)


def test_geojson_adapter_exports_synthetic_network_building_tools() -> None:
    generator = FakeGeoJSONGenerator(grid_size=2, seed=7, rectangular=True)
    payload = generator.generate_geojson()

    valid, message = validate_geojson(payload)
    buildings = extract_building_data(payload)

    assert valid, message
    assert len(buildings) == 4
    assert GeoProcessor.__name__ == "GeoProcessor"


def test_geoprocess_namespace_remains_compatible() -> None:
    assert LegacyFakeGeoJSONGenerator is FakeGeoJSONGenerator


def test_power_grid_graph_extracts_centroids_as_longitude_latitude(tmp_path: Path) -> None:
    geojson_path = tmp_path / "one_building.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": "b1"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-72.60, 46.34],
                                    [-72.59, 46.34],
                                    [-72.59, 46.35],
                                    [-72.60, 46.35],
                                    [-72.60, 46.34],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    graph = PowerGridGraph()
    buildings = graph.extract_building_centers_and_areas(str(geojson_path))
    row = buildings.iloc[0]

    assert row["Longitude"] == pytest.approx(-72.595, abs=0.001)
    assert row["Latitude"] == pytest.approx(46.345, abs=0.001)
    assert graph.building_centroids is not None
    assert graph.building_centroids[0][0] == pytest.approx(row["Longitude"])
    assert graph.building_centroids[0][1] == pytest.approx(row["Latitude"])


def test_geo_processor_filters_mixed_geometries_before_polygon_clip(
    tmp_path: Path,
) -> None:
    """OSMnx and imported building layers may contain non-polygon geometries."""
    source_path = tmp_path / "mixed_buildings.geojson"
    output_path = tmp_path / "filtered_buildings.geojson"
    buildings = gpd.GeoDataFrame(
        [
            {"building": "yes", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])},
            {"building": "yes", "geometry": LineString([(0, 0), (1, 1)])},
        ],
        crs="EPSG:4326",
    )
    buildings.to_file(source_path, driver="GeoJSON")

    processor = GeoProcessor(
        buildings_file=str(source_path),
        polygon_coords=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)],
        output_file=str(output_path),
    )

    processor.process_buildings_in_polygon()

    filtered = gpd.read_file(output_path)
    assert len(filtered) == 1
    assert set(filtered.geom_type) <= {"Polygon", "MultiPolygon"}


def test_microsoft_footprint_preparer_reads_geojson_lines(tmp_path: Path) -> None:
    """Microsoft partitions are commonly line-delimited GeoJSON features."""
    input_path = tmp_path / "microsoft.geojsonl"
    output_path = tmp_path / "buildings.geojson"
    features = [
        {
            "type": "Feature",
            "properties": {"confidence": 0.95},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
            },
        },
        {
            "type": "Feature",
            "properties": {"confidence": 0.9},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(feature) for feature in features),
        encoding="utf-8",
    )

    count = prepare_footprints(input_path, output_path)

    filtered = gpd.read_file(output_path)
    assert count == 1
    assert len(filtered) == 1
    assert filtered.iloc[0]["confidence"] == pytest.approx(0.95)

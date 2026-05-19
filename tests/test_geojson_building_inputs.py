import gzip
import json
from pathlib import Path

from gridalyn.twin.geoprocess import (
    load_polygon_coordinates,
    prepare_microsoft_building_footprints,
)


def test_load_polygon_coordinates_accepts_gridalyn_config(tmp_path: Path) -> None:
    path = tmp_path / "polygon.json"
    path.write_text(
        json.dumps(
            {
                "polygon_coordinates": [
                    [-72.0, 46.0],
                    [-72.0, 46.1],
                    [-71.9, 46.1],
                    [-72.0, 46.0],
                ]
            }
        )
    )

    assert load_polygon_coordinates(path) == [
        (-72.0, 46.0),
        (-72.0, 46.1),
        (-71.9, 46.1),
        (-72.0, 46.0),
    ]


def test_prepare_microsoft_building_footprints_converts_jsonl_gz(tmp_path: Path) -> None:
    source = tmp_path / "buildings.geojsonl.gz"
    output = tmp_path / "prepared.geojson"
    feature = {
        "type": "Feature",
        "properties": {"id": "b1"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-72.0, 46.0],
                    [-72.0, 46.001],
                    [-71.999, 46.001],
                    [-71.999, 46.0],
                    [-72.0, 46.0],
                ]
            ],
        },
    }
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(feature) + "\n")

    count = prepare_microsoft_building_footprints(source, output)

    assert count == 1
    payload = json.loads(output.read_text())
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 1

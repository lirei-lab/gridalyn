"""Generate a deterministic building-footprint GeoJSON input."""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.twin.adapters.geojson import FakeGeoJSONGenerator, validate_geojson


PROJECT_NAME = "synthetic_geojson_feeder"


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/reports"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def main() -> int:
    _ensure_outputs()
    output_path = Path("outputs/data/building_footprints.geojson")
    generator = FakeGeoJSONGenerator(
        grid_size=3,
        seed=27,
        rectangular=True,
        min_size_variance=0.95,
        max_size_variance=1.05,
    )
    payload = generator.generate_geojson()
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    validation_errors = validate_geojson(str(output_path))
    write_report(
        "outputs/reports/building_footprints_report.json",
        metadata=ReportMetadata(
            report_id="building_footprints_report",
            source_domain="geospatial_input",
            project={"name": PROJECT_NAME},
        ),
        inputs=[],
        artifacts=[file_reference(output_path)],
        summary={
            "project_intent": "generate_demo_building_footprints",
            "building_count": len(payload["features"]),
            "source_crs": payload.get("crs", {}).get("properties", {}).get("name"),
        },
        validation={"valid": not validation_errors, "errors": validation_errors, "warnings": []},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

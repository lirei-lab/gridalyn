"""Generate a deterministic building-footprint GeoJSON input."""

from __future__ import annotations

import json

from gridalyn.projects.scripting import project_script
from gridalyn.twin.adapters.geojson import FakeGeoJSONGenerator, validate_geojson


def main() -> int:
    script = project_script()
    output_path = script.data_dir / "building_footprints.geojson"
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
    script.write_report(
        "building_footprints_report",
        inputs=[],
        artifacts=[script.file_reference(output_path)],
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

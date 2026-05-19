"""Prepare project-owned synthetic topology cache artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.data.datasets import get_dataset_path
from gridalyn.simulators.powerflow.runner import MonteCarloSimulationManager

from projects.flexibility_cls.scripts.config import (
    GRID_CONFIG,
    PROJECT_CACHE_DIR,
    TOPOLOGY_CACHE_MANIFEST,
)


REQUIRED_CACHE_FILES = (
    "pg_graph_cache.pkl",
    "pp_net_cache.pkl",
    "grid_cache_meta.json",
)
FOOTPRINT_VALIDATION_REPORT = "building_footprint_validation_report.json"


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geojson_bounds(gdf: gpd.GeoDataFrame) -> dict[str, float]:
    minx, miny, maxx, maxy = gdf.to_crs("EPSG:4326").total_bounds
    return {
        "min_lon": float(minx),
        "min_lat": float(miny),
        "max_lon": float(maxx),
        "max_lat": float(maxy),
    }


def _validate_building_footprints(source: Path, report_path: Path) -> dict[str, Any]:
    """Validate project building-footprint GeoJSON and write a lineage report."""
    resolved = source.resolve()
    gdf = gpd.read_file(resolved)
    warnings: list[str] = []
    errors: list[str] = []

    if gdf.crs is None:
        warnings.append("Input CRS is missing; assuming EPSG:4326 for reporting.")
        gdf = gdf.set_crs("EPSG:4326")

    geometry_counts = {
        str(key): int(value) for key, value in gdf.geom_type.value_counts().items()
    }
    polygon_mask = gdf.geom_type.isin(["Polygon", "MultiPolygon"])
    polygon_count = int(polygon_mask.sum())
    if polygon_count == 0:
        errors.append("No Polygon or MultiPolygon building footprints found.")

    invalid_count = int((~gdf.geometry.is_valid).sum())
    if invalid_count:
        warnings.append(f"{invalid_count} invalid geometries will be repaired downstream.")

    polygon_gdf = gdf.loc[polygon_mask].copy()
    projected = polygon_gdf.to_crs(epsg=3857) if not polygon_gdf.empty else polygon_gdf
    area_series = projected.geometry.area if not polygon_gdf.empty else []
    area_summary = {
        "total_m2": float(area_series.sum()) if polygon_count else 0.0,
        "mean_m2": float(area_series.mean()) if polygon_count else 0.0,
        "min_m2": float(area_series.min()) if polygon_count else 0.0,
        "max_m2": float(area_series.max()) if polygon_count else 0.0,
    }

    report = {
        "schema_version": "1.0",
        "artifact_type": "building_footprint_validation_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "valid": not errors,
        "source": {
            "path": source.as_posix(),
            "resolved_path": resolved.as_posix(),
            "sha256": _file_sha256(resolved),
            "format": "GeoJSON FeatureCollection",
            "crs": str(gdf.crs),
        },
        "counts": {
            "features": int(len(gdf)),
            "polygon_footprints": polygon_count,
            "non_polygon_features": int(len(gdf) - polygon_count),
            "invalid_geometries": invalid_count,
        },
        "geometry_types": geometry_counts,
        "bounds_wgs84": _geojson_bounds(gdf) if len(gdf) else {},
        "area_summary": area_summary,
        "errors": errors,
        "warnings": warnings,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise ValueError(f"Invalid building footprint input: {errors}")
    return report


def _cache_counts(manager: MonteCarloSimulationManager) -> dict[str, int]:
    net = manager.pp_net
    pg = manager.pg_graph
    return {
        "buses": int(len(net.bus)),
        "lines": int(len(net.line)),
        "transformers": int(len(net.trafo)),
        "loads": int(len(net.load)),
        "buildings": int(len(getattr(pg, "building_data", []))),
    }


def prepare_topology_cache(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    input_file: Path | None = None,
    force_rebuild: bool = False,
) -> Path:
    """Build or refresh the EV project topology cache."""

    source = input_file or get_dataset_path("buildings_inside_polygon.geojson")
    source = Path(source)
    cache_dir.mkdir(parents=True, exist_ok=True)
    validation_report_path = cache_dir / FOOTPRINT_VALIDATION_REPORT
    footprint_report = _validate_building_footprints(source, validation_report_path)

    manager = MonteCarloSimulationManager(
        input_file=str(source),
        cache_dir=str(cache_dir),
        config=GRID_CONFIG,
    )
    manager._prepare_grid(force_rebuild=force_rebuild)

    missing = [name for name in REQUIRED_CACHE_FILES if not (cache_dir / name).exists()]
    if missing:
        raise RuntimeError(f"Topology cache generation did not create: {missing}")

    manifest = {
        "schema_version": "1.0",
        "artifact_type": "synthetic_topology_cache",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": cache_dir.as_posix(),
        "input_file": Path(source).as_posix(),
        "config_hash": _config_hash(GRID_CONFIG),
        "required_files": list(REQUIRED_CACHE_FILES),
        "counts": _cache_counts(manager),
        "building_footprints": {
            "source_path": Path(source).as_posix(),
            "sha256": footprint_report["source"]["sha256"],
            "feature_count": footprint_report["counts"]["features"],
            "polygon_footprints": footprint_report["counts"]["polygon_footprints"],
            "crs": footprint_report["source"]["crs"],
            "bounds_wgs84": footprint_report["bounds_wgs84"],
            "validation_report": validation_report_path.as_posix(),
        },
        "notes": [
            "Project-owned runtime cache for the Flexibility CLS workflow.",
            "Generated artifacts under projects/*/outputs are not committed.",
        ],
    }
    manifest_path = (
        TOPOLOGY_CACHE_MANIFEST
        if cache_dir == PROJECT_CACHE_DIR
        else cache_dir / "topology_cache_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    manifest_path = prepare_topology_cache(
        cache_dir=args.cache_dir,
        input_file=args.input_file,
        force_rebuild=args.force_rebuild,
    )
    print(f"Prepared topology cache manifest: {manifest_path}")


if __name__ == "__main__":
    main()

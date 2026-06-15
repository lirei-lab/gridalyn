"""Synthetic topology-cache builders for project workflows."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd

from gridalyn.simulation.simulators.powerflow.runner import PowerflowMonteCarloRunner


REQUIRED_SYNTHETIC_CACHE_FILES = (
    "pg_graph_cache.pkl",
    "pp_net_cache.pkl",
    "grid_cache_meta.json",
)
FOOTPRINT_VALIDATION_REPORT = "building_footprint_validation_report.json"


def prepare_synthetic_topology_cache(
    *,
    input_file: Path | str,
    cache_dir: Path | str,
    config: dict[str, Any],
    manifest_path: Path | str | None = None,
    force_rebuild: bool = False,
    notes: list[str] | None = None,
) -> Path:
    """Build a synthetic topology cache and write a lineage manifest."""

    source = Path(input_file)
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    validation_report_path = cache_path / FOOTPRINT_VALIDATION_REPORT
    footprint_report = validate_building_footprints(source, validation_report_path)

    runner = PowerflowMonteCarloRunner(
        input_file=str(source),
        cache_dir=str(cache_path),
        config=config,
    )
    runner._prepare_grid(force_rebuild=force_rebuild)

    missing = [
        name
        for name in REQUIRED_SYNTHETIC_CACHE_FILES
        if not (cache_path / name).exists()
    ]
    if missing:
        raise RuntimeError(f"Topology cache generation did not create: {missing}")

    manifest = {
        "schema_version": "1.0",
        "artifact_type": "synthetic_topology_cache",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": cache_path.as_posix(),
        "input_file": source.as_posix(),
        "config_hash": config_hash(config),
        "required_files": list(REQUIRED_SYNTHETIC_CACHE_FILES),
        "counts": cache_counts(runner),
        "building_footprints": {
            "source_path": source.as_posix(),
            "sha256": footprint_report["source"]["sha256"],
            "feature_count": footprint_report["counts"]["features"],
            "polygon_footprints": footprint_report["counts"]["polygon_footprints"],
            "crs": footprint_report["source"]["crs"],
            "bounds_wgs84": footprint_report["bounds_wgs84"],
            "validation_report": validation_report_path.as_posix(),
        },
        "notes": notes or [],
    }
    path = Path(manifest_path) if manifest_path is not None else cache_path / "topology_cache_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path


def validate_building_footprints(source: Path | str, report_path: Path | str) -> dict[str, Any]:
    """Validate building-footprint GeoJSON and write a lineage report."""

    source_path = Path(source)
    resolved = source_path.resolve()
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
            "path": source_path.as_posix(),
            "resolved_path": resolved.as_posix(),
            "sha256": file_sha256(resolved),
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
        "bounds_wgs84": geojson_bounds(gdf) if len(gdf) else {},
        "area_summary": area_summary,
        "errors": errors,
        "warnings": warnings,
    }
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise ValueError(f"Invalid building footprint input: {errors}")
    return report


def cache_counts(runner: PowerflowMonteCarloRunner) -> dict[str, int]:
    """Return stable summary counts from a prepared powerflow runner."""

    net = runner.pp_net
    pg = runner.pg_graph
    return {
        "buses": int(len(net.bus)),
        "lines": int(len(net.line)),
        "transformers": int(len(net.trafo)),
        "loads": int(len(net.load)),
        "buildings": int(len(getattr(pg, "building_data", []))),
    }


def config_hash(config: dict[str, Any]) -> str:
    """Return a stable hash for a grid-generation configuration."""

    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path | str) -> str:
    """Return the SHA256 digest for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def geojson_bounds(gdf: gpd.GeoDataFrame) -> dict[str, float]:
    """Return WGS84 bounds for a GeoDataFrame."""

    minx, miny, maxx, maxy = gdf.to_crs("EPSG:4326").total_bounds
    return {
        "min_lon": float(minx),
        "min_lat": float(miny),
        "max_lon": float(maxx),
        "max_lat": float(maxy),
    }


__all__ = [
    "FOOTPRINT_VALIDATION_REPORT",
    "REQUIRED_SYNTHETIC_CACHE_FILES",
    "cache_counts",
    "config_hash",
    "file_sha256",
    "geojson_bounds",
    "prepare_synthetic_topology_cache",
    "validate_building_footprints",
]

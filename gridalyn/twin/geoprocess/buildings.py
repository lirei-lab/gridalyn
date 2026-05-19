"""Building-footprint acquisition and preparation helpers."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Sequence

import geopandas as gpd
from shapely.geometry import Polygon

from gridalyn.twin.geoprocess.downloader import BuildingDownloader
from gridalyn.twin.geoprocess.processor import GeoProcessor


def load_polygon_coordinates(path: Path | str) -> list[tuple[float, float]]:
    """Load polygon coordinates from Gridalyn JSON or GeoJSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    coordinates: Sequence[Sequence[float]]
    if "polygon_coordinates" in payload:
        coordinates = payload["polygon_coordinates"]
    elif payload.get("type") == "Polygon":
        coordinates = payload["coordinates"][0]
    elif payload.get("type") == "Feature":
        coordinates = payload["geometry"]["coordinates"][0]
    else:
        raise ValueError(
            "Polygon file must contain polygon_coordinates, a Polygon geometry, "
            "or a GeoJSON Feature with Polygon geometry."
        )
    return [(float(lon), float(lat)) for lon, lat in coordinates]


def clip_buildings_by_polygon(
    buildings_file: Path | str,
    polygon_coordinates: Sequence[tuple[float, float]],
    output_file: Path | str,
) -> Path:
    """Clip building footprints to a polygon and write GeoJSON."""

    processor = GeoProcessor(
        str(buildings_file),
        list(polygon_coordinates),
        str(output_file),
    )
    processor.process_buildings_in_polygon()
    return Path(output_file)


def download_osm_building_footprints(
    polygon_coordinates: Sequence[tuple[float, float]],
    output_file: Path | str,
) -> Path:
    """Download OSM building footprints with OSMnx."""

    downloader = BuildingDownloader()
    downloader.download_buildings(
        tuple(tuple(float(value) for value in coordinate) for coordinate in polygon_coordinates),
        str(output_file),
    )
    return Path(output_file)


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _read_geojson_lines(path: Path, limit: int | None = None) -> gpd.GeoDataFrame:
    features = []
    with _open_text(path) as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            features.append(json.loads(stripped))
            if limit is not None and len(features) >= limit:
                break
    if not features:
        raise ValueError(f"No GeoJSON features found in {path}")
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def _load_footprints(path: Path, limit: int | None) -> gpd.GeoDataFrame:
    if path.suffixes[-2:] == [".geojson", ".gz"]:
        return _read_geojson_lines(path, limit)
    if path.suffix in {".jsonl", ".geojsonl", ".gz"}:
        return _read_geojson_lines(path, limit)
    return gpd.read_file(path, rows=limit)


def _polygon_footprints(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.loc[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if gdf.empty:
        raise ValueError("No Polygon/MultiPolygon building footprints found")
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf


def prepare_microsoft_building_footprints(
    input_path: Path | str,
    output_path: Path | str,
    polygon_path: Path | str | None = None,
    limit: int | None = None,
) -> int:
    """Convert a local Microsoft building-footprint partition to GeoJSON."""

    input_path = Path(input_path)
    output_path = Path(output_path)
    footprints = _polygon_footprints(_load_footprints(input_path, limit))
    if polygon_path is not None:
        polygon = Polygon(load_polygon_coordinates(Path(polygon_path)))
        clipper = gpd.GeoDataFrame({"geometry": [polygon]}, crs="EPSG:4326")
        clipper = clipper.to_crs(footprints.crs)
        footprints = gpd.overlay(footprints, clipper, how="intersection")
        footprints = _polygon_footprints(footprints)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    footprints.to_file(output_path, driver="GeoJSON")
    return len(footprints)


__all__ = [
    "clip_buildings_by_polygon",
    "download_osm_building_footprints",
    "load_polygon_coordinates",
    "prepare_microsoft_building_footprints",
]

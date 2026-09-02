"""Compatibility namespace for GeoJSON preprocessing."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "BuildingDownloader": ("gridalyn.twin.geoprocess.downloader", "BuildingDownloader"),
    "clip_buildings_by_polygon": (
        "gridalyn.twin.geoprocess.buildings",
        "clip_buildings_by_polygon",
    ),
    "download_osm_building_footprints": (
        "gridalyn.twin.geoprocess.buildings",
        "download_osm_building_footprints",
    ),
    "FakeGeoJSONGenerator": (
        "gridalyn.twin.geoprocess.generator",
        "FakeGeoJSONGenerator",
    ),
    "GeoProcessor": ("gridalyn.twin.geoprocess.processor", "GeoProcessor"),
    "load_polygon_coordinates": (
        "gridalyn.twin.geoprocess.buildings",
        "load_polygon_coordinates",
    ),
    "prepare_microsoft_building_footprints": (
        "gridalyn.twin.geoprocess.buildings",
        "prepare_microsoft_building_footprints",
    ),
    "calculate_area": ("gridalyn.twin.geoprocess.utils", "calculate_area"),
    "calculate_centroid": ("gridalyn.twin.geoprocess.utils", "calculate_centroid"),
    "extract_building_data": (
        "gridalyn.twin.geoprocess.utils",
        "extract_building_data",
    ),
    "validate_geojson": ("gridalyn.twin.geoprocess.utils", "validate_geojson"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.twin.geoprocess' has no attribute {name!r}")

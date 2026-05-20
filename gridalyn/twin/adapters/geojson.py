"""GeoJSON adapters for synthetic network generation.

This module is the public import path for tools that ingest, filter, validate,
or generate building-footprint GeoJSON before passing those footprints to
:class:`gridalyn.twin.core.graph.PowerGridGraph`.
"""

from __future__ import annotations

from gridalyn.twin.geoprocess.downloader import BuildingDownloader
from gridalyn.twin.geoprocess.generator import FakeGeoJSONGenerator
from gridalyn.twin.geoprocess.processor import GeoProcessor
from gridalyn.twin.geoprocess.utils import (
    calculate_area,
    calculate_centroid,
    extract_building_data,
    validate_geojson,
)

__all__ = [
    "BuildingDownloader",
    "FakeGeoJSONGenerator",
    "GeoProcessor",
    "calculate_area",
    "calculate_centroid",
    "extract_building_data",
    "validate_geojson",
]

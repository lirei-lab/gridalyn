"""Where a base network snapshot sits on the earth, resolved from its tables.

A base snapshot carries coordinates but never says what they mean: no manifest
key records a CRS, and no artifact records an extent. A consumer that wants to
draw the network therefore has to guess two things it cannot verify -- what
``lat``/``lon`` are measured in, and where to open the view. This module
answers both from the snapshot itself and makes the answer's *confidence*
explicit, so a guess is never mistaken for a declaration.

**Which geometries exist, and which are derived.** Only ``grid_buses`` and
``buildings`` carry coordinates; ``grid_lines`` and ``grid_transformers`` carry
electrical parameters and bus endpoints, nothing spatial. A line's geometry is
therefore *derived* -- the segment between the coordinates of its two endpoint
buses -- and a transformer's is the position of one of its buses. Saying so
here is what stops each consumer from rediscovering it by reading
``grid_lines.parquet`` and finding no coordinate column.

**And what KIND each geometry is.** A resolved coordinate pair says "there is a
position here"; it does not say whether that position is the whole geometry or
a reduction of a richer one. For ``buildings`` it is a reduction -- the ingest
starts from real footprints and keeps only the centroid -- so a consumer with
only the coordinates would reasonably draw a footprint layer the twin cannot
support. :data:`BUILDING_GEOMETRY_KIND` and the ``geometry_kinds`` block close
that, on the same principle as ``crs_source``: the confidence and the shape of
an answer travel with the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from gridalyn.twin.network.schema import (
    BUILDINGS,
    GRID_BUSES,
    GRID_LINES,
    GRID_TRANSFORMERS,
    ROLE_FROM_BUS,
    ROLE_LATITUDE,
    ROLE_LONGITUDE,
    ROLE_TO_BUS,
    table_schema,
)

DEFAULT_GEOGRAPHIC_CRS = "EPSG:4326"
"""CRS assumed when a snapshot declares none.

Not an arbitrary default. Every path into the twin's geoprocess layer either
sets or asserts ``EPSG:4326`` -- ``buildings.load_footprints``,
``geoprocess.processor``, ``geoprocess.downloader``, and the synthetic
generator, which stamps ``urn:ogc:def:crs:OGC:1.3:CRS84`` into the GeoJSON it
emits -- and ``build_pandapower_from_geojson`` documents that graph geodata
stays longitude/latitude while clustering happens in a projected CRS. The
assumption is therefore consistent with every in-repo producer; it is still
reported as ``"assumed"`` rather than ``"declared"``, because consistency with
the producers this repo ships is not the same as a statement carried by the
snapshot in hand.
"""

CRS_DECLARED = "declared"
CRS_ASSUMED = "assumed"

_LOCATED_ARTIFACTS: tuple[str, ...] = (GRID_BUSES, BUILDINGS)

GEOMETRY_POINT = "point"
"""A row's geometry is a single position carried on the row itself."""

GEOMETRY_DERIVED = "derived"
"""A row's geometry is built from the positions of the buses it references."""

BUILDING_GEOMETRY_KIND = GEOMETRY_POINT
"""What ``buildings`` geometry IS, decided 2026-09-02 and declared, not implied.

The GeoJSON ingest starts from real footprints:
:meth:`gridalyn.twin.core.graph.PowerGridGraph.
extract_building_centers_and_areas` filters on ``Polygon``/``MultiPolygon`` and
raises when it finds neither. It then keeps the centroid and the area and drops
the polygon, so the base snapshot carries building POINTS and nothing
downstream of it can reconstruct the footprint.

Two honest outcomes were open, and the wrong one was silence. Retaining the
source geometry was measured and is reachable -- the shipped twin's source
layer still exists, 3235 polygons, about 0.23 MB as parquet -- and was
deliberately not taken here: it changes the base-snapshot contract and needs
its own re-base, which does not belong inside a dashboard change. What is taken
is the other honest outcome: the twin SAYS its building geometry is points, so
no consumer offers a layer implying otherwise.
"""

BUILDING_GEOMETRY_REASON = (
    "the GeoJSON ingest reads Polygon/MultiPolygon footprints and retains only "
    "the centroid and the area (PowerGridGraph."
    "extract_building_centers_and_areas); the polygons are not carried into the "
    "base snapshot, and nothing downstream of it can reconstruct them -- a "
    "consumer that wants footprints must go back to the source layer"
)
"""Why building geometry is points, travelling with the declaration itself."""


@dataclass(frozen=True)
class BoundingBox:
    """Geographic extent of a located snapshot, in the snapshot's own CRS.

    Attributes:
        min_lon: Western edge.
        min_lat: Southern edge.
        max_lon: Eastern edge.
        max_lat: Northern edge.
    """

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def center(self) -> tuple[float, float]:
        """Return the extent's midpoint as ``(lon, lat)``.

        A planar midpoint, which is what a map viewport wants and what is
        correct at the span of a distribution network. It is not a geodesic
        centroid and should not be used as one.
        """
        return (
            (self.min_lon + self.max_lon) / 2.0,
            (self.min_lat + self.max_lat) / 2.0,
        )

    def to_list(self) -> list[float]:
        """Return ``[min_lon, min_lat, max_lon, max_lat]``, the GeoJSON order."""
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native rendering carrying both the extent and centre."""
        lon, lat = self.center
        return {
            "bbox": self.to_list(),
            "center": {"lon": lon, "lat": lat},
        }


@dataclass(frozen=True)
class NetworkGeography:
    """What a consumer needs in order to draw a base snapshot.

    Attributes:
        crs: Coordinate reference system the snapshot's coordinates are in.
        crs_source: :data:`CRS_DECLARED` when the snapshot's manifest names the
            CRS, :data:`CRS_ASSUMED` when it is
            :data:`DEFAULT_GEOGRAPHIC_CRS` because nothing declared one.
        bounding_box: Extent of the located artifacts, or ``None`` when the
            snapshot carries no usable coordinates.
        located_artifacts: Canonical artifacts that carry coordinates directly,
            each mapped to the column names the coordinates were resolved to.
        derived_geometry: Canonical artifacts whose geometry must be built from
            bus endpoints, each mapped to the endpoint roles to join on.
        geometry_kinds: What each located artifact's geometry IS, so a consumer
            never infers the shape from the fact that coordinates exist. A
            column pair says "there is a position here"; it does not say
            whether that position is the whole geometry or a reduction of a
            richer one, and for ``buildings`` it is a reduction.
    """

    crs: str
    crs_source: str
    bounding_box: BoundingBox | None
    located_artifacts: Mapping[str, Mapping[str, str]]
    derived_geometry: Mapping[str, tuple[str, ...]]
    geometry_kinds: Mapping[str, Mapping[str, str]]

    @property
    def located(self) -> bool:
        """Whether the snapshot has an extent, i.e. can be put on a map."""
        return self.bounding_box is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native payload for a catalog or report."""
        payload: dict[str, Any] = {
            "crs": self.crs,
            "crs_source": self.crs_source,
            "located": self.located,
            "located_artifacts": {
                artifact: dict(columns)
                for artifact, columns in self.located_artifacts.items()
            },
            "derived_geometry": {
                artifact: list(roles)
                for artifact, roles in self.derived_geometry.items()
            },
            "geometry_kinds": {
                artifact: dict(declaration)
                for artifact, declaration in self.geometry_kinds.items()
            },
        }
        payload["extent"] = (
            self.bounding_box.to_dict() if self.bounding_box is not None else None
        )
        return payload


def _crs_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Return the CRS a manifest declares, or ``None`` when it declares none.

    Args:
        metadata: Parsed ``metadata.json`` payload, or ``None``.

    Returns:
        The declared CRS string, or ``None``. Both the top-level key and the
        ``model_version`` block are consulted, because the manifest nests most
        provenance under the latter.
    """
    if not metadata:
        return None
    for holder in (metadata, metadata.get("model_version") or {}):
        if not isinstance(holder, Mapping):
            continue
        value = holder.get("crs")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coordinate_columns(frame: pd.DataFrame, artifact: str) -> dict[str, str] | None:
    """Resolve an artifact's declared coordinate columns within ``frame``.

    Args:
        frame: Loaded table.
        artifact: Canonical artifact name.

    Returns:
        A mapping of role to resolved column name, or ``None`` when the frame
        carries neither coordinate.
    """
    schema = table_schema(artifact)
    latitude = schema.resolve(frame, ROLE_LATITUDE)
    longitude = schema.resolve(frame, ROLE_LONGITUDE)
    if latitude is None or longitude is None:
        return None
    return {ROLE_LATITUDE: latitude, ROLE_LONGITUDE: longitude}


def _extent(frames: list[tuple[pd.DataFrame, dict[str, str]]]) -> BoundingBox | None:
    """Return the extent spanning every located frame, or ``None``.

    Args:
        frames: Pairs of loaded frame and its resolved coordinate columns.

    Returns:
        The spanning :class:`BoundingBox`, or ``None`` when no frame holds a
        single row with both coordinates present. Rows missing either
        coordinate are dropped rather than treated as zeros, which is what
        keeps a partially-located snapshot from reporting an extent that
        reaches the Gulf of Guinea.
    """
    lats: list[float] = []
    lons: list[float] = []
    for frame, columns in frames:
        if frame.empty:
            continue
        pair = frame[[columns[ROLE_LATITUDE], columns[ROLE_LONGITUDE]]].apply(
            pd.to_numeric, errors="coerce"
        )
        pair = pair.dropna()
        if pair.empty:
            continue
        lats.extend(pair.iloc[:, 0].tolist())
        lons.extend(pair.iloc[:, 1].tolist())
    if not lats or not lons:
        return None
    return BoundingBox(
        min_lon=float(min(lons)),
        min_lat=float(min(lats)),
        max_lon=float(max(lons)),
        max_lat=float(max(lats)),
    )


def resolve_network_geography(
    *,
    frames: Mapping[str, pd.DataFrame],
    metadata: Mapping[str, Any] | None = None,
) -> NetworkGeography:
    """Resolve where a base snapshot sits, from its loaded tables.

    Args:
        frames: Loaded base tables keyed by canonical artifact name. Only the
            artifacts that can carry coordinates are consulted; the rest may be
            absent from the mapping.
        metadata: Parsed ``metadata.json`` payload, consulted for a declared
            CRS. When it declares none, :data:`DEFAULT_GEOGRAPHIC_CRS` is used
            and reported as :data:`CRS_ASSUMED`.

    Returns:
        The resolved :class:`NetworkGeography`. A snapshot with no usable
        coordinates still returns a value -- with ``bounding_box`` ``None`` and
        ``located`` false -- rather than raising: an unlocated network is a
        legitimate model, not an error.
    """
    declared = _crs_from_metadata(metadata)
    located: dict[str, dict[str, str]] = {}
    usable: list[tuple[pd.DataFrame, dict[str, str]]] = []
    for artifact in _LOCATED_ARTIFACTS:
        frame = frames.get(artifact)
        if frame is None:
            continue
        columns = _coordinate_columns(frame, artifact)
        if columns is None:
            continue
        located[artifact] = columns
        usable.append((frame, columns))

    return NetworkGeography(
        crs=declared or DEFAULT_GEOGRAPHIC_CRS,
        crs_source=CRS_DECLARED if declared else CRS_ASSUMED,
        bounding_box=_extent(usable),
        located_artifacts=located,
        derived_geometry={
            GRID_LINES: (ROLE_FROM_BUS, ROLE_TO_BUS),
            GRID_TRANSFORMERS: ("hv_bus", "lv_bus"),
        },
        geometry_kinds=_geometry_kinds(located),
    )


def _geometry_kinds(
    located: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    """Declare what each located artifact's geometry actually is.

    Args:
        located: Artifacts resolved as carrying coordinates directly.

    Returns:
        Artifact to declaration. Only ``buildings`` carries a reason, because
        it is the only artifact whose position is a REDUCTION of a richer
        source geometry rather than the geometry itself.
    """
    kinds: dict[str, dict[str, str]] = {}
    for artifact in located:
        declaration = {"kind": GEOMETRY_POINT}
        if artifact == BUILDINGS:
            declaration["kind"] = BUILDING_GEOMETRY_KIND
            declaration["reason"] = BUILDING_GEOMETRY_REASON
        kinds[artifact] = declaration
    for artifact in (GRID_LINES, GRID_TRANSFORMERS):
        kinds[artifact] = {"kind": GEOMETRY_DERIVED}
    return kinds

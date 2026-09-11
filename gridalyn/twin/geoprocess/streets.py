"""Snap synthetic-network positions onto the street network.

The synthetic builder places an MV/LV transformer on the building with the
highest closeness centrality in its cluster (``PowerGridGraph._create_cluster_mst``),
which puts it in a back yard rather than on a pole in the right-of-way.
Measured on the shipped Trois-Rivieres footprints, the 193 transformers sit a
median **19.4 m** from the nearest street, 43.5% of them more than 20 m away.

This module supplies the geometry needed to site them where a pole would go.
It is deliberately a *capability*, not a default: OSMnx is optional, a street
fetch needs the network, and -- most importantly -- moving a transformer moves
a real electrical quantity. The transformer-to-building service drop is a
pandapower line, and today it is pinned at the configured ``min_length_km``
because the transformer sits exactly on the building. Snapping to the street
turns that 1 m stub into roughly 20 m of conductor, changing its impedance and
therefore the power flow. Every consumer must opt in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import numpy as np

from gridalyn.foundation.platform.capabilities import require_capabilities

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

DEFAULT_NETWORK_TYPE = "drive_service"
"""OSMnx network type fetched by default.

``drive_service`` keeps service roads and alleys, which is where secondary
distribution actually runs; ``drive`` alone drops them and would push poles out
to the nearest through-road.
"""

DEFAULT_BBOX_PADDING_DEG = 0.002
"""Degrees of padding added around the footprint extent before fetching.

Roughly 200 m at the study latitude. Without it, a building on the edge of the
extent has no street on its far side and snaps inward, which is an artifact of
the fetch window rather than of the geography.
"""

BLOCK_BBOX_PADDING_DEG = 0.012
"""Degrees of padding to fetch when street *blocks*, not nearest streets, are needed.

Roughly 1.3 km at the study latitude. A block is a face the street network
encloses, and a face at the edge of the footprint extent only closes if the
streets beyond it were fetched too. The bd 4os.7 and 4os.11 measurements used
this padding and found 871 faces over the shipped footprints.
"""


@dataclass(frozen=True)
class StreetSnapper:
    """Nearest-street lookup over a projected street layer.

    Attributes:
        edges: Street segments in ``metric_crs``, carrying a spatial index.
        metric_crs: The projected CRS ``edges`` is measured in. Distances are
            only meaningful because the layer is projected; snapping in
            longitude/latitude would weight a degree of longitude as a degree
            of latitude.
    """

    edges: "gpd.GeoDataFrame"
    metric_crs: str

    def snap(self, lon: float, lat: float) -> tuple[float, float]:
        """Return the point on the nearest street, as longitude and latitude.

        Args:
            lon: Longitude of the position to snap.
            lat: Latitude of the position to snap.

        Returns:
            ``(longitude, latitude)`` of the closest point on the nearest
            street segment. Coordinates come back in EPSG:4326 because that is
            what graph nodes carry.
        """
        from pyproj import Transformer
        from shapely.geometry import Point
        from shapely.ops import nearest_points

        to_metric = Transformer.from_crs("EPSG:4326", self.metric_crs, always_xy=True)
        to_wgs84 = Transformer.from_crs(self.metric_crs, "EPSG:4326", always_xy=True)
        point = Point(*to_metric.transform(lon, lat))
        edge = self.edges.geometry.iloc[self._nearest_edge_index(point)]
        on_street = nearest_points(edge, point)[0]
        snapped_lon, snapped_lat = to_wgs84.transform(on_street.x, on_street.y)
        return float(snapped_lon), float(snapped_lat)

    def distance_m(self, lon: float, lat: float) -> float:
        """Return the distance in metres from a position to the nearest street.

        Args:
            lon: Longitude of the position.
            lat: Latitude of the position.

        Returns:
            Distance in metres, in ``metric_crs``.
        """
        from pyproj import Transformer
        from shapely.geometry import Point

        to_metric = Transformer.from_crs("EPSG:4326", self.metric_crs, always_xy=True)
        point = Point(*to_metric.transform(lon, lat))
        edge = self.edges.geometry.iloc[self._nearest_edge_index(point)]
        return float(point.distance(edge))

    def block_ids(self, lon_lat: np.ndarray) -> np.ndarray:
        """Return the street block each position falls in.

        A block is a face of the street network: polygonizing the segments
        yields the areas they enclose, so two positions share a block exactly
        when no street runs between them. That is what lets a clustering tell a
        neighbour across the street from a neighbour on the same side.

        Args:
            lon_lat: ``(n, 2)`` longitude/latitude positions.

        Returns:
            ``(n,)`` integer block ids, ``-1`` for a position outside every face
            (beyond the outermost street, or in a face the fetch window left
            open). Ids are comparable only within one call.

        Raises:
            ValueError: If ``lon_lat`` is not ``(n, 2)``, or the street layer is
                empty.
        """
        import geopandas as gpd
        from pyproj import Transformer
        from shapely.ops import polygonize, unary_union

        positions = np.asarray(lon_lat, dtype=float)
        if positions.ndim != 2 or positions.shape[1] != 2:
            raise ValueError(
                f"lon_lat must be an (n, 2) array, got shape {positions.shape}"
            )
        if self.edges.empty:
            raise ValueError(
                "street layer is empty, so it encloses no blocks; "
                "widen the fetch extent or check the network_type"
            )
        faces = list(polygonize(unary_union(list(self.edges.geometry))))
        if not faces or len(positions) == 0:
            return np.full(len(positions), -1, dtype=int)
        to_metric = Transformer.from_crs("EPSG:4326", self.metric_crs, always_xy=True)
        xs, ys = to_metric.transform(positions[:, 0], positions[:, 1])
        points = gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(xs, ys), crs=self.metric_crs
        )
        blocks = gpd.GeoDataFrame(geometry=faces, crs=self.metric_crs)
        joined = gpd.sjoin(points, blocks, how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")].sort_index()
        ids = joined["index_right"].to_numpy(dtype=float)
        return np.where(np.isnan(ids), -1, ids).astype(int)

    def _nearest_edge_index(self, point: "gpd.GeoSeries") -> int:
        """Return the positional index of the street segment nearest ``point``.

        Args:
            point: A shapely point already in ``metric_crs``.

        Returns:
            Positional index into ``edges``.

        Raises:
            ValueError: If the street layer is empty, which would otherwise
                surface as an opaque IndexError from the spatial index.
        """
        if self.edges.empty:
            raise ValueError(
                "street layer is empty, so nothing can be snapped to it; "
                "widen the fetch extent or check the network_type"
            )
        return int(self.edges.sindex.nearest(point, return_all=False)[1][0])


def load_street_snapper(
    bounds: Sequence[float],
    *,
    metric_crs: str,
    network_type: str = DEFAULT_NETWORK_TYPE,
    padding_deg: float = DEFAULT_BBOX_PADDING_DEG,
) -> StreetSnapper:
    """Fetch the street network for an extent and return a snapper over it.

    Args:
        bounds: ``(min_lon, min_lat, max_lon, max_lat)`` in EPSG:4326, e.g.
            a footprint layer's ``total_bounds``.
        metric_crs: Projected CRS to measure in. Pass the same CRS the network
            build clusters in, so siting and clustering agree.
        network_type: OSMnx network type. See :data:`DEFAULT_NETWORK_TYPE` for
            why the default keeps service roads.
        padding_deg: Degrees of padding added around ``bounds`` before
            fetching. See :data:`DEFAULT_BBOX_PADDING_DEG`.

    Returns:
        A :class:`StreetSnapper` over the projected street layer.

    Raises:
        MissingCapabilityError: If the ``geo`` extra (OSMnx) is not installed.
        ValueError: If ``bounds`` is not four values, or the fetch returns no
            street segments -- an empty layer would otherwise fail later, far
            from the cause.
    """
    require_capabilities("geo", context="street-network siting")

    import osmnx as ox

    if len(tuple(bounds)) != 4:
        raise ValueError(
            f"bounds must be (min_lon, min_lat, max_lon, max_lat), got "
            f"{len(tuple(bounds))} value(s)"
        )
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in bounds)
    graph = ox.graph_from_bbox(
        (
            min_lon - padding_deg,
            min_lat - padding_deg,
            max_lon + padding_deg,
            max_lat + padding_deg,
        ),
        network_type=network_type,
        simplify=True,
    )
    edges = ox.graph_to_gdfs(graph, nodes=False)
    if edges.empty:
        raise ValueError(
            f"no {network_type!r} street segments found in "
            f"({min_lon}, {min_lat}, {max_lon}, {max_lat}) padded by "
            f"{padding_deg} deg; widen the extent or choose another network_type"
        )
    return StreetSnapper(
        edges=edges.to_crs(metric_crs).reset_index(drop=True),
        metric_crs=str(metric_crs),
    )


__all__ = [
    "BLOCK_BBOX_PADDING_DEG",
    "DEFAULT_BBOX_PADDING_DEG",
    "DEFAULT_NETWORK_TYPE",
    "StreetSnapper",
    "load_street_snapper",
]

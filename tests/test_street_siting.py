"""Transformers sited on the street rather than on the building they serve.

Every test here runs offline. ``load_street_snapper`` fetches from OSM, which
CI cannot do, so the fetch is exercised only through its argument validation
and the snapping itself is driven from a hand-built street layer.
"""

from __future__ import annotations

import unittest

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import LineString

from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.twin.geoprocess.streets import StreetSnapper, load_street_snapper

# A single east-west street at latitude 46.3400, spanning the test extent.
# EPSG:32618 is the UTM zone the Trois-Rivieres footprints estimate.
_METRIC_CRS = "EPSG:32618"
_STREET_LAT = 46.3400


def _street_layer() -> gpd.GeoDataFrame:
    """Return a one-segment street layer projected into the metric CRS.

    Returns:
        A GeoDataFrame holding a single east-west LineString.
    """
    street = LineString([(-72.6100, _STREET_LAT), (-72.5900, _STREET_LAT)])
    return gpd.GeoDataFrame({"geometry": [street]}, crs="EPSG:4326").to_crs(_METRIC_CRS)


def _snapper() -> StreetSnapper:
    """Return a snapper over the one-segment street layer.

    Returns:
        The snapper under test.
    """
    return StreetSnapper(edges=_street_layer(), metric_crs=_METRIC_CRS)


class StreetSnapperTest(unittest.TestCase):
    """The snapper puts a point on the street and measures the offset."""

    def test_snap_moves_the_point_onto_the_street(self) -> None:
        """A point north of the street lands on it, keeping its longitude."""
        snapper = _snapper()
        lon, lat = snapper.snap(-72.6000, _STREET_LAT + 0.0005)

        self.assertAlmostEqual(lat, _STREET_LAT, places=5)
        self.assertAlmostEqual(lon, -72.6000, places=4)

    def test_snap_is_idempotent_for_a_point_already_on_the_street(self) -> None:
        """Snapping a point already on the street does not move it."""
        snapper = _snapper()
        lon, lat = snapper.snap(-72.6000, _STREET_LAT)

        self.assertLess(snapper.distance_m(lon, lat), 1e-6)

    def test_distance_reports_the_offset_in_metres(self) -> None:
        """0.0005 degrees of latitude is about 55 m, not 0.0005."""
        distance = _snapper().distance_m(-72.6000, _STREET_LAT + 0.0005)

        self.assertGreater(distance, 45.0)
        self.assertLess(distance, 65.0)

    def test_empty_street_layer_says_so_instead_of_indexing_past_the_end(self) -> None:
        """An empty layer raises a located ValueError, not an IndexError."""
        empty = gpd.GeoDataFrame({"geometry": []}, crs=_METRIC_CRS)
        snapper = StreetSnapper(edges=empty, metric_crs=_METRIC_CRS)

        with self.assertRaises(ValueError) as caught:
            snapper.snap(-72.6000, _STREET_LAT)
        self.assertIn("street layer is empty", str(caught.exception))

    def test_bad_bounds_are_rejected_before_any_network_call(self) -> None:
        """A three-value extent fails on its shape, not inside OSMnx."""
        with self.assertRaises(ValueError) as caught:
            load_street_snapper((1.0, 2.0, 3.0), metric_crs=_METRIC_CRS)
        self.assertIn("min_lon", str(caught.exception))


class ClusterCenterSitingTest(unittest.TestCase):
    """Where ``_site_cluster_center`` puts a transformer, with and without a street."""

    def _points(self) -> np.ndarray:
        """Return four buildings north of the street.

        Returns:
            An ``(n, 2)`` array of longitude/latitude pairs.
        """
        return np.array(
            [
                [-72.6000, _STREET_LAT + 0.0004],
                [-72.5990, _STREET_LAT + 0.0004],
                [-72.5980, _STREET_LAT + 0.0005],
                [-72.5970, _STREET_LAT + 0.0005],
            ]
        )

    def _center(self, graph: nx.Graph) -> tuple[float, float]:
        """Return the coordinates of the single cluster centre.

        Args:
            graph: The built cluster graph.

        Returns:
            ``(x, y)`` of the ``tx_0`` node.
        """
        node = graph.nodes["tx_0"]
        return float(node["x"]), float(node["y"])

    def test_default_puts_the_transformer_on_a_building(self) -> None:
        """Without a snapper the centre copies a building's coordinates."""
        grid = PowerGridGraph()
        graph, _labels = grid.create_cluster_graph(
            self._points(), 1, node_prefix="b", cluster_prefix="tx"
        )
        _x, y = self._center(graph)

        self.assertGreater(y, _STREET_LAT, "should still sit north, on a building")
        self.assertGreater(_snapper().distance_m(*self._center(graph)), 40.0)

    def test_snapper_puts_the_transformer_on_the_street(self) -> None:
        """With a snapper the centre lands on the street, at zero offset."""
        grid = PowerGridGraph()
        grid.street_snapper = _snapper()
        graph, _labels = grid.create_cluster_graph(
            self._points(), 1, node_prefix="b", cluster_prefix="tx"
        )
        _x, y = self._center(graph)

        self.assertAlmostEqual(y, _STREET_LAT, places=5)
        self.assertLess(_snapper().distance_m(*self._center(graph)), 1e-6)

    def test_siting_does_not_change_which_buildings_join_the_cluster(self) -> None:
        """Moving the transformer must not move the cluster membership."""
        points = self._points()
        plain = PowerGridGraph()
        _graph_a, labels_a = plain.create_cluster_graph(
            points, 2, node_prefix="b", cluster_prefix="tx"
        )
        snapped = PowerGridGraph()
        snapped.street_snapper = _snapper()
        _graph_b, labels_b = snapped.create_cluster_graph(
            points, 2, node_prefix="b", cluster_prefix="tx"
        )

        np.testing.assert_array_equal(labels_a, labels_b)


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()

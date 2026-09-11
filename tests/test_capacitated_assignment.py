"""MV/LV transformers that serve no more buildings than they were sized for.

bd syntgrid-4os.7. Every test runs offline: the street layers are hand-built,
as in ``test_street_siting.py``, because CI cannot fetch from OSM.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString
from sklearn.cluster import KMeans

from gridalyn.simulation.simulators.powerflow.synthetic_network import (
    build_synthetic_network_from_config,
)
from gridalyn.twin.adapters.pandapower_builder import build_power_grid_and_network
from gridalyn.twin.core.assignment import assign_capacitated
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.twin.geoprocess import FakeGeoJSONGenerator
from gridalyn.twin.geoprocess.streets import StreetSnapper

_METRIC_CRS = "EPSG:32618"


def _two_blobs() -> tuple[np.ndarray, np.ndarray]:
    """Return 30 customers around one centre and 10 around another, 400 m apart.

    Returns:
        ``(points, centers)`` in metres.
    """
    rng = np.random.default_rng(0)
    points = np.vstack(
        [
            rng.normal((0.0, 0.0), 30.0, (30, 2)),
            rng.normal((400.0, 0.0), 30.0, (10, 2)),
        ]
    )
    return points, np.array([[0.0, 0.0], [400.0, 0.0]])


def _nearest(points: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Return the index of each point's nearest centre.

    Args:
        points: ``(n, 2)`` coordinates.
        centers: ``(k, 2)`` coordinates.

    Returns:
        ``(n,)`` centre indices.
    """
    return np.argmin(((points[:, None, :] - centers[None, :, :]) ** 2).sum(-1), axis=1)


class AssignCapacitatedTest(unittest.TestCase):
    """The assignment honours the limit and says so when it cannot."""

    def test_no_cluster_exceeds_the_limit_where_nearest_centre_would(self) -> None:
        """30 customers nearest one centre are split to respect a limit of 20."""
        points, centers = _two_blobs()
        self.assertEqual(np.bincount(_nearest(points, centers)).max(), 30)

        result = assign_capacitated(points, centers, 20)

        self.assertLessEqual(np.bincount(result.labels, minlength=2).max(), 20)
        self.assertTrue(result.converged)

    def test_a_limit_that_does_not_bind_changes_nothing(self) -> None:
        """With room for everyone, every customer sits at its nearest centre."""
        points, centers = _two_blobs()

        result = assign_capacitated(points, centers, len(points))

        np.testing.assert_array_equal(result.labels, _nearest(points, result.centers))

    def test_an_impossible_limit_names_the_capacity_that_would_fit(self) -> None:
        """40 customers on 2 transformers cannot fit a limit of 19."""
        points, centers = _two_blobs()

        with self.assertRaises(ValueError) as caught:
            assign_capacitated(points, centers, 19)
        self.assertIn("40 customers", str(caught.exception))
        self.assertIn("capacity >= 20", str(caught.exception))

    def test_too_few_candidates_widen_instead_of_failing(self) -> None:
        """One candidate per customer is infeasible here, so the step widens."""
        points, centers = _two_blobs()

        narrow = assign_capacitated(points, centers, 20, candidates=1)
        wide = assign_capacitated(points, centers, 20)

        np.testing.assert_array_equal(narrow.labels, wide.labels)

    def test_the_same_inputs_give_the_same_partition(self) -> None:
        """No hidden randomness: two runs agree label for label."""
        points, centers = _two_blobs()

        first = assign_capacitated(points, centers, 20)
        second = assign_capacitated(points, centers, 20)

        np.testing.assert_array_equal(first.labels, second.labels)

    def test_block_penalty_keeps_a_boundary_customer_in_its_own_block(self) -> None:
        """A customer nearer the other centre stays with its own block."""
        block_0 = [[0.0, 0.0], [-5.0, 5.0], [5.0, -5.0], [-5.0, -5.0], [5.0, 5.0]]
        block_1 = [[100.0, 0.0], [95.0, 5.0], [105.0, -5.0], [95.0, -5.0], [105.0, 5.0]]
        points = np.array(block_0 + block_1 + [[45.0, 0.0]])
        blocks = np.array([0] * 5 + [1] * 5 + [1])
        centers = np.array([[0.0, 0.0], [100.0, 0.0]])

        plain = assign_capacitated(points, centers, 11)
        penalised = assign_capacitated(
            points, centers, 11, block_ids=blocks, block_penalty_km2=0.005
        )

        self.assertEqual(plain.labels[-1], plain.labels[0], "geometry alone")
        self.assertEqual(penalised.labels[-1], penalised.labels[5], "its own block")

    def test_a_penalty_without_blocks_is_rejected(self) -> None:
        """A penalty with nothing to penalise is a contract error."""
        points, centers = _two_blobs()

        with self.assertRaises(ValueError) as caught:
            assign_capacitated(points, centers, 20, block_penalty_km2=0.005)
        self.assertIn("needs block_ids", str(caught.exception))


def _snapper(lines: list[LineString]) -> StreetSnapper:
    """Return a snapper over hand-built streets given in longitude/latitude.

    Args:
        lines: Street segments in EPSG:4326.

    Returns:
        The snapper, projected into the metric CRS.
    """
    edges = gpd.GeoDataFrame({"geometry": lines}, crs="EPSG:4326").to_crs(_METRIC_CRS)
    return StreetSnapper(edges=edges, metric_crs=_METRIC_CRS)


_WEST, _MID, _EAST, _SOUTH, _NORTH = -72.6000, -72.5990, -72.5980, 46.3400, 46.3420
# The ring is split at _MID so a crossing street meets it at a shared vertex, the
# way OSM delivers streets: already split at every intersection. A street that
# merely touches a segment's interior does not survive reprojection exactly on it,
# and polygonize would leave it dangling.
_RING = [
    LineString([(_WEST, _SOUTH), (_MID, _SOUTH)]),
    LineString([(_MID, _SOUTH), (_EAST, _SOUTH)]),
    LineString([(_EAST, _SOUTH), (_EAST, _NORTH)]),
    LineString([(_EAST, _NORTH), (_MID, _NORTH)]),
    LineString([(_MID, _NORTH), (_WEST, _NORTH)]),
    LineString([(_WEST, _NORTH), (_WEST, _SOUTH)]),
]


class StreetBlockIdsTest(unittest.TestCase):
    """Blocks are the faces the streets enclose."""

    def test_positions_in_one_block_share_an_id_and_outside_is_minus_one(self) -> None:
        """Two positions inside the ring match; one outside it gets -1."""
        ids = _snapper(_RING).block_ids(
            np.array([[-72.5995, 46.3405], [-72.5985, 46.3415], [-72.6010, 46.3410]])
        )

        self.assertGreaterEqual(ids[0], 0)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[2], -1)

    def test_a_street_between_two_positions_separates_their_blocks(self) -> None:
        """A north-south street through the ring splits it into two blocks."""
        middle = LineString([(_MID, _SOUTH), (_MID, _NORTH)])

        ids = _snapper(_RING + [middle]).block_ids(
            np.array([[-72.5995, 46.3410], [-72.5985, 46.3410]])
        )

        self.assertGreaterEqual(min(ids), 0)
        self.assertNotEqual(ids[0], ids[1])

    def test_an_empty_street_layer_says_so(self) -> None:
        """No streets means no blocks, reported as such."""
        empty = StreetSnapper(
            edges=gpd.GeoDataFrame({"geometry": []}, crs=_METRIC_CRS),
            metric_crs=_METRIC_CRS,
        )

        with self.assertRaises(ValueError) as caught:
            empty.block_ids(np.array([[-72.5995, 46.3405]]))
        self.assertIn("encloses no blocks", str(caught.exception))


class LvGraphPartitionTest(unittest.TestCase):
    """``create_lv_graph`` keeps its default and applies the limit on request."""

    def _grid(self, clustering_crs: str | None) -> PowerGridGraph:
        """Return a graph holding 40 buildings, as if extracted from footprints.

        Args:
            clustering_crs: The CRS clustering runs in, ``None`` for lon/lat.

        Returns:
            The prepared graph.
        """
        rng = np.random.default_rng(3)
        grid = PowerGridGraph()
        grid.building_centroids = np.column_stack(
            [-72.60 + rng.uniform(0, 0.004, 40), 46.34 + rng.uniform(0, 0.003, 40)]
        )
        grid.clustering_crs = clustering_crs
        return grid

    def _build(self, grid: PowerGridGraph, **options: Any) -> None:
        """Build the LV graph at 10 kW per building on 100 kVA units (5 of them).

        Args:
            grid: The prepared graph.
            **options: Partition options passed to ``create_lv_graph``.
        """
        grid.create_lv_graph(
            max_load_per_building=50.0,
            mv_lv_transformer_capacity=100.0,
            capacity_utilization_factor=0.8,
            diversity_factor_lv=5.0,
            **options,
        )

    def test_the_default_partition_is_still_plain_kmeans(self) -> None:
        """Without the option the labels are exactly today's K-means labels."""
        grid = self._grid(_METRIC_CRS)
        self._build(grid)

        points = grid._points_for_clustering(grid.building_centroids)
        expected = KMeans(n_clusters=5, random_state=0, n_init=1).fit_predict(points)
        np.testing.assert_array_equal(grid.labels_lv, expected)
        self.assertIsNone(grid.lv_assignment)

    def test_capacitated_caps_every_transformer_at_the_sized_count(self) -> None:
        """40 buildings on 5 transformers: no transformer serves more than 8."""
        grid = self._grid(_METRIC_CRS)
        self._build(grid, capacitated=True)

        assert grid.lv_assignment is not None
        self.assertEqual(grid.lv_assignment.capacity, 8)
        self.assertLessEqual(np.bincount(grid.labels_lv).max(), 8)

    def test_a_block_penalty_needs_a_metric_clustering_crs(self) -> None:
        """A km^2 penalty over degrees would mean nothing, so it is refused."""
        grid = self._grid(None)

        with self.assertRaises(ValueError) as caught:
            self._build(
                grid,
                capacitated=True,
                block_ids=np.zeros(40, dtype=int),
                block_penalty_km2=0.005,
            )
        self.assertIn("metric CRS", str(caught.exception))

    def test_block_options_without_capacitated_are_refused(self) -> None:
        """Block ids on a plain K-means partition would silently do nothing."""
        grid = self._grid(_METRIC_CRS)

        with self.assertRaises(ValueError) as caught:
            self._build(grid, block_ids=np.zeros(40, dtype=int))
        self.assertIn("capacitated=True", str(caught.exception))


class BuilderOptionsTest(unittest.TestCase):
    """The builder validates the options before it reads anything."""

    def test_an_unknown_method_lists_the_known_ones(self) -> None:
        """A typo fails naming both valid methods, not deep inside the build."""
        with self.assertRaises(ValueError) as caught:
            build_power_grid_and_network(
                footprints_path="unused.geojson", config={}, lv_assignment="balanced"
            )
        self.assertIn("kmeans", str(caught.exception))
        self.assertIn("capacitated", str(caught.exception))

    def test_a_block_penalty_on_kmeans_is_refused_before_any_fetch(self) -> None:
        """The penalty needs the capacitated step; without it, fail at once."""
        with self.assertRaises(ValueError) as caught:
            build_power_grid_and_network(
                footprints_path="unused.geojson", config={}, block_penalty_km2=0.005
            )
        self.assertIn("lv_assignment='capacitated'", str(caught.exception))


class ValidationReportTest(unittest.TestCase):
    """The report states the limit only when the build used one."""

    def _report(self, **options: Any) -> dict[str, Any]:
        """Build 16 footprints on 50 kVA units (4 of them) and return the report.

        Args:
            **options: Partition options for the build.

        Returns:
            The validation report.
        """
        generator = FakeGeoJSONGenerator(grid_size=4, seed=5, rectangular=True)
        config = json.loads(
            Path("configs/grid/config.json").read_text(encoding="utf-8")
        )
        config["transformers"]["lv_mv"]["capacity_kva"] = 50
        with tempfile.TemporaryDirectory() as tmp:
            footprints = Path(tmp) / "buildings.geojson"
            footprints.write_text(
                json.dumps(generator.generate_geojson()), encoding="utf-8"
            )
            result = build_synthetic_network_from_config(
                footprints_path=footprints,
                config=config,
                config_source="test_runtime_config",
                **options,
            )
        return result.validation_report

    def test_the_default_report_carries_no_lv_assignment_block(self) -> None:
        """Existing reports keep their bytes: no block under plain K-means."""
        self.assertNotIn("lv_assignment", self._report())

    def test_a_capacitated_report_states_the_limit_and_the_distribution(self) -> None:
        """16 buildings, 4 transformers: limit 4, and nothing above its rating."""
        block = self._report(lv_assignment="capacitated")["lv_assignment"]

        self.assertEqual(block["transformers"], 4)
        self.assertEqual(block["capacity_customers"], 4)
        self.assertLessEqual(block["customers_per_transformer"]["max"], 4)
        self.assertEqual(block["transformers_over_rated_kva_at_envelope"], 0)
        self.assertTrue(block["converged"])


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()

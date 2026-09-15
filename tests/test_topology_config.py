"""Topology options declared in the grid config, and a street layer pinned on disk.

bd 4os.7 (single re-base). A study pins its partition, siting and slack
setpoint as data in ``config["topology"]`` / ``config["external_grid"]``, and
its streets as a committed file with a declared digest. Every test here runs
offline: the street layers are hand-built around the fake footprints.
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

from gridalyn.simulation.simulators.powerflow.synthetic_network import (
    build_synthetic_network_from_config,
)
from gridalyn.twin.adapters.pandapower_builder import (
    TOPOLOGY_KEYS,
    external_grid_vm_pu,
    resolve_topology_options,
)
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.twin.geoprocess import FakeGeoJSONGenerator
from gridalyn.twin.geoprocess.streets import (
    load_street_snapper_from_file,
    street_layer_sha256,
    write_street_snapshot,
)

# The fake footprints (grid_size=4, seed=5) span lon -72.60002..-72.59811 and
# lat 46.33999..46.34132. The ring encloses them; the middle street splits the
# ring into two blocks and meets it at shared vertices, as OSM delivers streets.
_W, _MID, _E, _S, _N = -72.6010, -72.5991, -72.5970, 46.3395, 46.3420
_STREETS = [
    LineString([(_W, _S), (_MID, _S)]),
    LineString([(_MID, _S), (_E, _S)]),
    LineString([(_E, _S), (_E, _N)]),
    LineString([(_E, _N), (_MID, _N)]),
    LineString([(_MID, _N), (_W, _N)]),
    LineString([(_W, _N), (_W, _S)]),
    LineString([(_MID, _S), (_MID, _N)]),
]


def _base_config() -> dict[str, Any]:
    """Return the SDK default config on 50 kVA units, so 16 buildings need 4.

    Returns:
        A fresh config mapping.
    """
    config = json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))
    config["transformers"]["lv_mv"]["capacity_kva"] = 50
    return config


def _write_inputs(tmp: Path) -> tuple[Path, str]:
    """Write the fake footprints and a street layer beside them.

    Args:
        tmp: Directory to write into.

    Returns:
        ``(footprints_path, street_layer_sha256)``.
    """
    footprints = tmp / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=4, seed=5, rectangular=True)
    footprints.write_text(json.dumps(generator.generate_geojson()), encoding="utf-8")
    streets = tmp / "streets.geojson"
    gpd.GeoDataFrame({"geometry": _STREETS}, crs="EPSG:4326").to_file(
        streets, driver="GeoJSON"
    )
    return footprints, street_layer_sha256(streets)


def _declared_topology(digest: str, **extra: Any) -> dict[str, Any]:
    """Return a topology block that uses the street layer.

    Args:
        digest: The street layer's sha256.
        **extra: Keys to override.

    Returns:
        The block.
    """
    block: dict[str, Any] = {
        "lv_assignment": "capacitated",
        "max_customers_per_transformer": 5,
        "block_penalty_km2": 0.005,
        "snap_transformers_to_streets": True,
        "street_layer": {"path": "streets.geojson", "sha256": digest},
    }
    block.update(extra)
    return block


class ResolveTopologyOptionsTest(unittest.TestCase):
    """What a config declares, validated before anything is read."""

    def test_a_config_without_the_block_resolves_to_todays_build(self) -> None:
        """No topology block: K-means, no streets, no limit."""
        options = resolve_topology_options({}, footprints_path="b.geojson")

        self.assertEqual(options.lv_assignment, "kmeans")
        self.assertFalse(options.uses_streets)
        self.assertIsNone(options.max_customers_per_transformer)
        self.assertIsNone(options.street_layer_path)

    def test_a_relative_street_layer_resolves_beside_the_footprints(self) -> None:
        """The path is relative to the footprint file's directory."""
        options = resolve_topology_options(
            {"topology": _declared_topology("abc")},
            footprints_path="projects/demo/inputs/buildings.geojson",
        )

        self.assertEqual(
            options.street_layer_path, Path("projects/demo/inputs/streets.geojson")
        )
        self.assertEqual(options.max_customers_per_transformer, 5)

    def test_an_explicit_argument_overrides_the_config(self) -> None:
        """A caller can switch siting off for one build."""
        options = resolve_topology_options(
            {"topology": _declared_topology("abc")},
            footprints_path="b.geojson",
            snap_transformers_to_streets=False,
        )

        self.assertFalse(options.snap_transformers_to_streets)

    def test_an_unknown_key_is_refused_by_name(self) -> None:
        """A typo fails listing the supported keys."""
        with self.assertRaises(ValueError) as caught:
            resolve_topology_options(
                {"topology": {"lv_asignment": "capacitated"}}, footprints_path="b"
            )
        self.assertIn("lv_asignment", str(caught.exception))
        for key in TOPOLOGY_KEYS:
            self.assertIn(key, str(caught.exception))

    def test_a_limit_on_kmeans_is_refused(self) -> None:
        """K-means has no limit to honour, so declaring one is a contract error."""
        with self.assertRaises(ValueError) as caught:
            resolve_topology_options(
                {"topology": {"max_customers_per_transformer": 10}},
                footprints_path="b",
            )
        self.assertIn("lv_assignment='capacitated'", str(caught.exception))

    def test_a_street_layer_nothing_uses_is_refused(self) -> None:
        """A declared layer with no siting and no penalty would govern nothing."""
        with self.assertRaises(ValueError) as caught:
            resolve_topology_options(
                {
                    "topology": {
                        "lv_assignment": "capacitated",
                        "street_layer": {"path": "s.geojson", "sha256": "abc"},
                    }
                },
                footprints_path="b",
            )
        self.assertIn("nothing uses it", str(caught.exception))

    def test_a_street_layer_without_its_digest_is_refused(self) -> None:
        """The digest is required: it is what makes a changed layer change the config."""
        with self.assertRaises(ValueError) as caught:
            resolve_topology_options(
                {
                    "topology": _declared_topology(
                        "", street_layer={"path": "streets.geojson"}
                    )
                },
                footprints_path="b",
            )
        self.assertIn("sha256", str(caught.exception))


class ExternalGridSetpointTest(unittest.TestCase):
    """The slack setpoint is declared, defaulted and bounded."""

    def test_the_default_setpoint_is_nominal(self) -> None:
        """No block keeps today's 1.0 pu."""
        self.assertEqual(external_grid_vm_pu({}), 1.0)

    def test_a_declared_setpoint_is_used(self) -> None:
        """The declared value comes back, with a note allowed beside it."""
        config = {"external_grid": {"vm_pu": 1.04, "note": "substation LTC"}}
        self.assertEqual(external_grid_vm_pu(config), 1.04)

    def test_an_implausible_setpoint_is_refused(self) -> None:
        """A setpoint outside [0.9, 1.1] pu is almost certainly a units error."""
        with self.assertRaises(ValueError) as caught:
            external_grid_vm_pu({"external_grid": {"vm_pu": 104}})
        self.assertIn("[0.9, 1.1]", str(caught.exception))


class StreetLayerFileTest(unittest.TestCase):
    """A street layer on disk loads without the network and checks its digest."""

    def test_a_layer_on_disk_gives_blocks_without_the_network(self) -> None:
        """The middle street separates the two halves of the ring."""
        with tempfile.TemporaryDirectory() as raw:
            _footprints, digest = _write_inputs(Path(raw))
            snapper = load_street_snapper_from_file(
                Path(raw) / "streets.geojson",
                metric_crs="EPSG:32618",
                expected_sha256=digest,
            )
            ids = snapper.block_ids(
                np.array([[-72.6000, 46.3405], [-72.5980, 46.3405]])
            )

        self.assertGreaterEqual(min(ids), 0)
        self.assertNotEqual(ids[0], ids[1])

    def test_a_changed_layer_is_refused_naming_both_digests(self) -> None:
        """An edit after the config pinned the digest fails loudly."""
        with tempfile.TemporaryDirectory() as raw:
            _footprints, digest = _write_inputs(Path(raw))
            with self.assertRaises(ValueError) as caught:
                load_street_snapper_from_file(
                    Path(raw) / "streets.geojson",
                    metric_crs="EPSG:32618",
                    expected_sha256="0" * 64,
                )
        self.assertIn(digest, str(caught.exception))
        self.assertIn("0" * 64, str(caught.exception))

    def test_a_missing_layer_names_the_remedy(self) -> None:
        """A declared file that is not there says how to make one."""
        with self.assertRaises(FileNotFoundError) as caught:
            load_street_snapper_from_file("absent.geojson", metric_crs="EPSG:32618")
        self.assertIn("write_street_snapshot", str(caught.exception))

    def test_bad_bounds_are_refused_before_any_fetch(self) -> None:
        """A snapshot with a three-value extent fails on its shape, offline."""
        with self.assertRaises(ValueError) as caught:
            write_street_snapshot((1.0, 2.0, 3.0), "unused.geojson")
        self.assertIn("min_lon", str(caught.exception))


class DeclaredLimitTest(unittest.TestCase):
    """A declared per-transformer limit wins over the sized count."""

    def _grid(self) -> PowerGridGraph:
        """Return a graph holding 40 buildings in UTM, as if extracted.

        Returns:
            The prepared graph.
        """
        rng = np.random.default_rng(3)
        grid = PowerGridGraph()
        grid.building_centroids = np.column_stack(
            [-72.60 + rng.uniform(0, 0.004, 40), 46.34 + rng.uniform(0, 0.003, 40)]
        )
        grid.clustering_crs = "EPSG:32618"
        return grid

    def _build(self, grid: PowerGridGraph, max_customers: int) -> None:
        """Build 5 transformers (10 kW per building on 100 kVA at 0.8).

        Args:
            grid: The prepared graph.
            max_customers: The declared limit.
        """
        grid.create_lv_graph(
            max_load_per_building=50.0,
            mv_lv_transformer_capacity=100.0,
            capacity_utilization_factor=0.8,
            diversity_factor_lv=5.0,
            capacitated=True,
            max_customers=max_customers,
        )

    def test_a_declared_limit_above_the_sized_count_is_used(self) -> None:
        """40 buildings on 5 transformers, declared 10: sizes may vary up to 10."""
        grid = self._grid()
        self._build(grid, 10)

        assert grid.lv_assignment is not None
        self.assertEqual(grid.lv_assignment.capacity, 10)
        self.assertLessEqual(np.bincount(grid.labels_lv).max(), 10)

    def test_a_declared_limit_that_cannot_hold_everyone_is_refused(self) -> None:
        """Declared 6 on 5 transformers cannot place 40 buildings."""
        with self.assertRaises(ValueError) as caught:
            self._build(self._grid(), 6)
        self.assertIn("at least 8", str(caught.exception))


class DeclaredBuildTest(unittest.TestCase):
    """A full build from a declaring config, offline."""

    def test_the_declared_options_reach_the_network_and_the_report(self) -> None:
        """Limit, blocks, siting and setpoint all come from the config file."""
        with tempfile.TemporaryDirectory() as raw:
            footprints, digest = _write_inputs(Path(raw))
            config = _base_config()
            config["topology"] = _declared_topology(digest)
            config["external_grid"] = {"vm_pu": 1.04}
            result = build_synthetic_network_from_config(
                footprints_path=footprints, config=config, run_powerflow=True
            )
            snapper = load_street_snapper_from_file(
                Path(raw) / "streets.geojson", metric_crs="EPSG:32618"
            )

        report = result.validation_report
        self.assertTrue(report["powerflow"]["converged"])
        self.assertEqual(list(result.net.ext_grid.vm_pu), [1.04])
        self.assertEqual(report["topology_options"]["street_layer"]["sha256"], digest)
        self.assertEqual(report["topology_options"]["external_grid_vm_pu"], 1.04)
        self.assertEqual(report["lv_assignment"]["capacity_customers"], 5)
        self.assertEqual(report["lv_assignment"]["capacity_source"], "declared")
        self.assertLessEqual(
            report["lv_assignment"]["customers_per_transformer"]["max"], 5
        )
        feeders = [
            (data["x"], data["y"])
            for _node, data in result.power_grid.graph_lv_buses.nodes(data=True)
            if data.get("type") == "lv_feeder"
        ]
        self.assertTrue(feeders)
        for lon, lat in feeders:
            self.assertLess(snapper.distance_m(lon, lat), 0.01, "sited on a street")

    def test_a_config_without_the_blocks_keeps_its_report_bytes(self) -> None:
        """No topology/external_grid block and no override: no new report key."""
        with tempfile.TemporaryDirectory() as raw:
            footprints, _digest = _write_inputs(Path(raw))
            result = build_synthetic_network_from_config(
                footprints_path=footprints, config=_base_config()
            )

        self.assertNotIn("topology_options", result.validation_report)
        self.assertEqual(list(result.net.ext_grid.vm_pu), [1.0])


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()

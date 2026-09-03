import importlib
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

from gridalyn.projects.dashboard_catalog import FILE_KINDS as _FILE_KINDS
from gridalyn.projects.dashboard_catalog import (
    build_dashboard_catalog,
    write_dashboard_catalog,
)
from gridalyn.projects.workflows.scripts.generate_digital_twin_dashboard_catalog import (
    DEFAULT_EXTENSIONS,
)
from gridalyn.projects.workflows.scripts.verify_dashboard_consistency import (
    SUPPORTED_SCHEMA_VERSIONS,
)
from gridalyn.twin import NetworkModelRepository


class DashboardCatalogTest(unittest.TestCase):
    def test_build_dashboard_catalog_uses_grid_metrics_not_study_fields(self):
        scenario_index = {
            "scenarios": [
                {
                    "scenario_id": "WinterPeak",
                    "label": "Winter Peak",
                    "description": "Cold-weather loading case",
                    "ev_penetration_pct": 40,
                }
            ]
        }
        powerflow_summary = {
            "scenarios": [
                {
                    "scenario_id": "WinterPeak",
                    "ext_grid_peak_mw": 12.3,
                    "load_peak_mw": 11.9,
                    "v_min_pu": 0.94,
                    "line_max_loading_percent": 88.0,
                    "trafo_max_loading_percent": 92.0,
                    "n_buses": 100,
                    "n_lines": 99,
                    "n_transformers": 4,
                    "paths": {
                        "nodes": "instances/default/digital_twin/custom/nodes.parquet",
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            network_impact = (
                root
                / "instances"
                / "default"
                / "digital_twin"
                / "flexibility"
                / "network_impact_catalog.json"
            )
            operations = (
                root
                / "instances"
                / "default"
                / "digital_twin"
                / "operations"
                / "operations_catalog.json"
            )
            network_impact.parent.mkdir(parents=True)
            operations.parent.mkdir(parents=True)
            network_impact.write_text("{}", encoding="utf-8")
            operations.write_text("{}", encoding="utf-8")

            catalog = build_dashboard_catalog(
                scenario_index=scenario_index,
                powerflow_summary=powerflow_summary,
                optional_extensions={
                    "network_impact": network_impact,
                    "operations": operations,
                },
                root=root,
            )

        scenario = catalog["scenarios"][0]
        self.assertEqual(catalog["report_id"], "digital_twin_dashboard_catalog")
        self.assertEqual(scenario["scenario_id"], "WinterPeak")
        self.assertEqual(scenario["metrics"]["grid_peak_mw"], 12.3)
        self.assertEqual(scenario["metrics"]["load_peak_mw"], 11.9)
        self.assertEqual(scenario["topology_counts"]["n_buses"], 100)
        self.assertNotIn("ev_penetration_pct", scenario["metrics"])
        self.assertEqual(
            scenario["extensions"]["network_impact"],
            "/instances/default/digital_twin/flexibility/network_impact_catalog.json",
        )
        self.assertEqual(
            scenario["extensions"]["operations"],
            "/instances/default/digital_twin/operations/operations_catalog.json",
        )

    def test_write_dashboard_catalog_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = (
                Path(tmp)
                / "instances"
                / "default"
                / "digital_twin"
                / "dashboard"
                / "catalog.json"
            )
            written = write_dashboard_catalog(
                path, {"report_id": "digital_twin_dashboard_catalog"}
            )

            self.assertEqual(written, path)
            self.assertEqual(
                json.loads(path.read_text())["report_id"],
                "digital_twin_dashboard_catalog",
            )

    def test_deprecated_interfaces_deep_path_imports_and_warns(self):
        """Ledger #36: the pre-relocation deep path stays importable as a shim.

        Both facade names must resolve to the relocated implementation, and the
        import itself must fire exactly one DeprecationWarning naming the new
        module, so external callers of the published SDK get a migration signal
        instead of an ImportError.
        """
        shim_name = "gridalyn.interfaces.reporting.dashboard_catalog"
        sys.modules.pop(shim_name, None)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                shim = importlib.import_module(shim_name)

            self.assertIs(shim.build_dashboard_catalog, build_dashboard_catalog)
            self.assertIs(shim.write_dashboard_catalog, write_dashboard_catalog)

            deprecations = [
                item for item in caught if issubclass(item.category, DeprecationWarning)
            ]
            self.assertEqual(1, len(deprecations))
            self.assertIn(
                "gridalyn.projects.dashboard_catalog",
                str(deprecations[0].message),
            )
        finally:
            sys.modules.pop(shim_name, None)

    def test_dashboard_catalog_script_declares_operations_extension(self):
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            DEFAULT_EXTENSIONS["operations"].relative_to(repo_root).as_posix(),
            "instances/default/digital_twin/operations/operations_catalog.json",
        )

    def test_build_dashboard_catalog_uses_network_repository_counts_as_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "instances" / "default" / "digital_twin" / "base"
            base.mkdir(parents=True)
            pd.DataFrame([{"bus_id": "bus:0"}, {"bus_id": "bus:1"}]).to_parquet(
                base / "grid_buses.parquet"
            )
            pd.DataFrame(
                [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
            ).to_parquet(base / "grid_lines.parquet")
            pd.DataFrame(
                [
                    {
                        "transformer_id": "transformer:0",
                        "hv_bus_id": "bus:1",
                        "lv_bus_id": "bus:0",
                    }
                ]
            ).to_parquet(base / "grid_transformers.parquet")
            pd.DataFrame(
                [{"building_id": "building:0", "load_id": "load:0"}]
            ).to_parquet(base / "buildings.parquet")
            pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "load_bus_id": "bus:0",
                    }
                ]
            ).to_parquet(base / "building_grid_connectivity.parquet")
            (base / "metadata.json").write_text(
                json.dumps(
                    {
                        "model_version_id": "model:sha256:test",
                        "model_version": {
                            "id": "model:sha256:test",
                            "source_adapter": "TestAdapter",
                        },
                    }
                ),
                encoding="utf-8",
            )

            catalog = build_dashboard_catalog(
                scenario_index={"scenarios": [{"scenario_id": "S0"}]},
                powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
                optional_extensions={},
                root=Path(tmp),
                network_repository=NetworkModelRepository.from_parquet(base),
            )

        self.assertEqual(catalog["network_model"]["counts"]["buses"], 2)
        self.assertEqual(
            catalog["network_model"]["model_version_id"], "model:sha256:test"
        )
        self.assertEqual(
            catalog["network_model"]["model_version"]["source_adapter"], "TestAdapter"
        )
        self.assertEqual(catalog["network_model"]["validation"]["valid"], True)
        self.assertEqual(catalog["scenarios"][0]["topology_counts"]["n_buses"], 2)
        self.assertEqual(catalog["scenarios"][0]["topology_counts"]["n_lines"], 1)
        self.assertEqual(
            catalog["scenarios"][0]["topology_counts"]["n_transformers"], 1
        )
        self.assertEqual(catalog["scenarios"][0]["topology_counts"]["n_loads"], 1)


class DashboardCatalogGeographyTest(unittest.TestCase):
    """The catalog must reach the twin's geography, not only its timeseries.

    Before this block the catalog named per-scenario timeseries artifacts and
    nothing else: no CRS, no extent, and no path to `grid_buses`, `grid_lines`,
    `buildings` or `grid_transformers`. A geo-centred dashboard driven by the
    catalog was therefore impossible -- the only route to the network's
    geography was to hardcode the base paths, which is what a catalog exists to
    prevent.
    """

    def _catalog(self, tmp, *, lat=46.33, crs=None):
        base = Path(tmp) / "instances" / "default" / "digital_twin" / "base"
        base.mkdir(parents=True)
        pd.DataFrame(
            [
                {"bus_id": "bus:0", "lat": lat, "lon": -72.62},
                {"bus_id": "bus:1", "lat": 46.35, "lon": -72.60},
            ]
        ).to_parquet(base / "grid_buses.parquet")
        pd.DataFrame(
            [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
        ).to_parquet(base / "grid_lines.parquet")
        pd.DataFrame(
            [
                {
                    "transformer_id": "transformer:0",
                    "hv_bus_id": "bus:1",
                    "lv_bus_id": "bus:0",
                }
            ]
        ).to_parquet(base / "grid_transformers.parquet")
        pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "lat": 46.34,
                    "lon": -72.61,
                }
            ]
        ).to_parquet(base / "buildings.parquet")
        pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:0",
                }
            ]
        ).to_parquet(base / "building_grid_connectivity.parquet")
        metadata = {"model_version_id": "model:sha256:test"}
        if crs is not None:
            metadata["crs"] = crs
        (base / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
            optional_extensions={},
            root=Path(tmp),
            network_repository=NetworkModelRepository.from_parquet(base),
        )

    def test_catalog_names_every_base_artifact_that_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp)
        paths = catalog["network_model"]["geography"]["paths"]
        self.assertEqual(
            sorted(paths),
            [
                "building_grid_connectivity",
                "buildings",
                "grid_buses",
                "grid_lines",
                "grid_transformers",
            ],
        )
        self.assertEqual(
            paths["grid_buses"],
            "/instances/default/digital_twin/base/grid_buses.parquet",
        )

    def test_catalog_carries_an_extent_and_a_centre_to_open_the_map_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp)
        geography = catalog["network_model"]["geography"]
        self.assertTrue(geography["located"])
        self.assertEqual(geography["extent"]["bbox"], [-72.62, 46.33, -72.60, 46.35])
        self.assertAlmostEqual(geography["extent"]["center"]["lat"], 46.34)

    def test_an_undeclared_crs_is_published_as_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp)
        geography = catalog["network_model"]["geography"]
        self.assertEqual(geography["crs"], "EPSG:4326")
        self.assertEqual(geography["crs_source"], "assumed")

    def test_a_declared_crs_is_published_as_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp, crs="EPSG:32618")
        geography = catalog["network_model"]["geography"]
        self.assertEqual(geography["crs"], "EPSG:32618")
        self.assertEqual(geography["crs_source"], "declared")

    def test_catalog_states_that_line_geometry_is_derived(self):
        """Otherwise every consumer rediscovers it by finding no coordinates."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp)
        derived = catalog["network_model"]["geography"]["derived_geometry"]
        self.assertEqual(derived["grid_lines"], ["from_bus", "to_bus"])
        self.assertEqual(derived["grid_transformers"], ["hv_bus", "lv_bus"])

    def test_every_bump_stays_additive_so_a_1_0_reader_still_works(self):
        """Pins the property, not the number.

        An earlier version of this test asserted ``== "1.1"`` and duly failed
        on the next additive bump, which is the wrong failure: the contract is
        that every 1.0 key keeps its name, shape and meaning, not that the
        version stops moving. The version is checked against the verifier's
        supported set so the two cannot drift apart.
        """
        from gridalyn.projects.workflows.scripts.verify_dashboard_consistency import (
            SUPPORTED_SCHEMA_VERSIONS,
        )

        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._catalog(tmp)
        self.assertIn(catalog["schema_version"], SUPPORTED_SCHEMA_VERSIONS)
        self.assertEqual(catalog["report_id"], "digital_twin_dashboard_catalog")
        for key in ("counts", "model_version_id", "model_version", "validation"):
            self.assertIn(key, catalog["network_model"])
        self.assertIn("paths", catalog["scenarios"][0])
        self.assertIn("metrics", catalog["scenarios"][0])


class DashboardCatalogSemanticTest(unittest.TestCase):
    """The catalog must publish the ontology, not leave it to a hardcoded path.

    Before schema 1.3 the catalog carried no ``semantic`` key at all, so the
    dashboard reached the twin's ontology through
    ``LEGACY_MANIFEST_PATHS.semanticManifest`` -- a path belonging to the
    pre-catalog fallback -- and rendered four scalars off it: profile, valid,
    node count, edge count. An ontology reduced to a node count is nothing a
    client can colour, filter or group by, which is what this block fixes.
    """

    def _twin(self, tmp, *, with_semantic=True, with_assets=True):
        """Write a small twin on disk and return its catalog-build arguments."""
        root = Path(tmp)
        base = root / "instances" / "default" / "digital_twin" / "base"
        base.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "bus_id": "bus:0",
                    "lat": 46.3,
                    "lon": -72.6,
                    "cim_class": "ConnectivityNode",
                }
            ]
        ).to_parquet(base / "grid_buses.parquet")
        pd.DataFrame(
            [
                {
                    "line_id": "line:0",
                    "from_bus_id": "bus:0",
                    "to_bus_id": "bus:0",
                    "cim_class": "ACLineSegment",
                }
            ]
        ).to_parquet(base / "grid_lines.parquet")
        pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "lat": 46.35,
                    "lon": -72.55,
                    "ontology_class": "Building",
                }
            ]
        ).to_parquet(base / "buildings.parquet")
        (base / "metadata.json").write_text(
            json.dumps({"model_version_id": "model:sha256:test"}), encoding="utf-8"
        )

        semantic_dir = None
        if with_semantic:
            semantic_dir = root / "instances" / "default" / "digital_twin" / "semantic"
            semantic_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"semantic_type": "brick:Building", "source_table": "buildings"},
                    {
                        "semantic_type": "cim:EnergyConsumer",
                        "source_table": "buildings",
                    },
                ]
            ).to_parquet(semantic_dir / "nodes.parquet")
            (semantic_dir / "edges.parquet").write_bytes(b"")
            (semantic_dir / "profile_north_america.json").write_text("{}", "utf-8")
            (semantic_dir / "graph_manifest.json").write_text(
                json.dumps(
                    {
                        "semantic_profile": "north_america",
                        "node_count": 2,
                        "edge_count": 3,
                        "validation": {
                            "valid": True,
                            "error_count": 0,
                            "warning_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

        assets = None
        if with_assets:
            scenarios = root / "instances" / "default" / "digital_twin" / "scenarios"
            scenarios.mkdir(parents=True)
            assets = scenarios / "asset_registry.parquet"
            pd.DataFrame(
                [
                    {
                        "scenario_id": "S0",
                        "lat": 46.3,
                        "lon": -72.6,
                        "ontology_class": "Building",
                    },
                    {
                        "scenario_id": "S0",
                        "lat": 46.4,
                        "lon": -72.5,
                        "ontology_class": "EVChargingAsset",
                    },
                ]
            ).to_parquet(assets)

        return build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
            optional_extensions={},
            root=root,
            network_repository=NetworkModelRepository.from_parquet(base),
            semantic_dir=semantic_dir,
            scenario_assets=assets,
        )

    def test_the_emitted_schema_is_one_the_sdk_verifier_accepts(self):
        """1.3 introduced this block; pinning the number here would go stale on
        the next additive bump, and the invariant that matters is that the
        emitted version is one the SDK's own verifier reads."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        self.assertIn(catalog["schema_version"], SUPPORTED_SCHEMA_VERSIONS)
        self.assertIn("semantic", catalog)

    def test_the_catalog_declares_the_semantic_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        self.assertEqual("north_america", catalog["semantic"]["profile"])

    def test_the_catalog_declares_the_graphs_validation_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        graph = catalog["semantic"]["graph"]
        self.assertEqual(2, graph["node_count"])
        self.assertEqual(3, graph["edge_count"])
        self.assertEqual(
            {"valid": True, "errors": 0, "warnings": 0}, graph["validation"]
        )

    def test_the_catalog_declares_the_semantic_artifact_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        paths = catalog["semantic"]["paths"]
        # `validation_report` is deliberately absent: the fixture writes no
        # such file, and the catalog names only artifacts that exist -- the
        # same rule `network_model.geography.paths` follows.
        self.assertEqual(
            ["asset_registry", "edges", "graph_manifest", "nodes", "profile"],
            sorted(paths),
        )
        for artifact, url in paths.items():
            with self.subTest(artifact=artifact):
                self.assertTrue(url.startswith("/instances/default/digital_twin/"), url)

    def test_the_catalog_declares_the_classes_with_a_count_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        classes = catalog["semantic"]["classes"]
        self.assertEqual(
            {
                ("base_snapshot", "ConnectivityNode", None, 1),
                ("base_snapshot", "ACLineSegment", None, 1),
                ("base_snapshot", "Building", None, 1),
                ("semantic_graph", "brick:Building", None, 1),
                ("semantic_graph", "cim:EnergyConsumer", None, 1),
                ("scenario_assets", "Building", "S0", 1),
                ("scenario_assets", "EVChargingAsset", "S0", 1),
            },
            {
                (
                    entry["population"],
                    entry["class"],
                    entry["scenario_id"],
                    entry["count"],
                )
                for entry in classes
            },
        )

    def test_each_class_names_the_population_it_belongs_to(self):
        """The three populations do not coincide, so the catalog says which."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        self.assertEqual(
            ["base_snapshot", "semantic_graph", "scenario_assets"],
            catalog["semantic"]["populations"],
        )

    def test_a_drawable_class_is_distinguishable_from_a_derived_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        located = {
            entry["artifact"]: entry["located"]
            for entry in catalog["semantic"]["classes"]
        }
        self.assertTrue(located["grid_buses"])
        self.assertTrue(located["asset_registry"])
        self.assertFalse(located["grid_lines"])

    def test_base_class_artifacts_are_named_in_the_geography_paths(self):
        """`classes[].artifact` resolves against the union of the two path
        blocks, in one canonical key namespace, without a special case."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        reachable = set(catalog["network_model"]["geography"]["paths"]) | set(
            catalog["semantic"]["paths"]
        )
        base_artifacts = {
            entry["artifact"]
            for entry in catalog["semantic"]["classes"]
            if entry["population"] == "base_snapshot"
        }
        self.assertTrue(base_artifacts <= reachable, base_artifacts - reachable)

    def test_a_twin_with_no_semantic_layer_carries_no_semantic_block(self):
        """Absent, not empty. An empty block claims the ontology was looked for
        and found empty, which is a different statement."""
        catalog = build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
            optional_extensions=None,
            root=Path("/nonexistent-workspace"),
        )
        self.assertNotIn("semantic", catalog)
        self.assertIn(catalog["schema_version"], SUPPORTED_SCHEMA_VERSIONS)

    def test_a_twin_with_only_a_scenario_registry_still_publishes_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp, with_semantic=False)
        self.assertIsNone(catalog["semantic"]["profile"])
        self.assertEqual(
            {"scenario_assets", "base_snapshot"},
            {entry["population"] for entry in catalog["semantic"]["classes"]},
        )

    def test_existing_consumers_keep_their_keys(self):
        """1.3 is additive: every key a 1.2 reader reads keeps its name."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self._twin(tmp)
        for key in ("network_model", "projects", "scenarios", "title", "report_id"):
            with self.subTest(key=key):
                self.assertIn(key, catalog)
        self.assertIn("geography", catalog["network_model"])


class DashboardCatalogObservationTest(unittest.TestCase):
    """The catalog must say whether this instance is a digital shadow.

    ``gridalyn.twin`` is a canonical digital MODEL; a deployment becomes a
    digital SHADOW when its operator feeds it measured data, and
    ``NetworkObservation.provenance`` is the required field carrying that
    distinction. Before schema 1.4 the catalog named no observation artifact
    and no scenario said where its numbers came from, so a deployment fed real
    data had no way to show it -- and one fed none looked identical.
    """

    def _catalog(self, observations_dir=None):
        return build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
            optional_extensions=None,
            root=Path("/nonexistent-workspace"),
            observations_dir=observations_dir,
        )

    def test_schema_version_moves_to_one_four(self):
        """Pinned, unlike the semantic block's: this is the version under
        test, and the SDK verifier's supported set must move with it."""
        self.assertEqual("1.4", self._catalog()["schema_version"])
        self.assertIn("1.4", SUPPORTED_SCHEMA_VERSIONS)

    def test_the_block_is_published_even_with_no_measured_data(self):
        """Absent would make "none" and "too old to say" the same observation.

        Deliberately unlike ``semantic``, which IS omitted for a twin with no
        ontology: "is anything here measured?" is a question every consumer
        must be able to ask of every instance.
        """
        observation = self._catalog()["observation"]
        self.assertIs(False, observation["measured"]["available"])
        self.assertIsNotNone(observation["measured"]["absent_reason"])

    def test_an_instance_with_none_is_declared_simulated_not_unknown(self):
        self.assertEqual("simulated", self._catalog()["observation"]["provenance"])

    def test_every_scenario_declares_where_its_numbers_came_from(self):
        for scenario in self._catalog()["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertEqual("simulated", scenario["provenance"])

    def test_the_directory_is_named_so_an_operator_knows_where_to_put_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "instances" / "default" / "digital_twin"
            directory.mkdir(parents=True)
            observations = directory / "observations"
            observations.mkdir()
            catalog = build_dashboard_catalog(
                scenario_index={"scenarios": [{"scenario_id": "S0"}]},
                powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
                optional_extensions=None,
                root=Path(tmp),
                observations_dir=observations,
            )
        self.assertEqual(
            "/instances/default/digital_twin/observations",
            catalog["observation"]["measured"]["directory"],
        )

    def test_a_caller_that_names_no_directory_has_none_invented_for_it(self):
        measured = self._catalog()["observation"]["measured"]
        self.assertIsNone(measured["directory"])

    def test_measured_data_flips_the_instance_to_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observations = root / "instances" / "default" / "digital_twin" / "obs"
            observations.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "entity_id": "meter:0",
                        "quantity": "voltage_pu",
                        "value": 0.98,
                    }
                ]
            ).to_csv(observations / "ami.csv", index=False)
            pd.DataFrame([{"entity_id": "meter:0", "bus_id": "bus:0"}]).to_csv(
                observations / "entity_join.csv", index=False
            )
            catalog = build_dashboard_catalog(
                scenario_index={"scenarios": [{"scenario_id": "S0"}]},
                powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
                optional_extensions=None,
                root=root,
                observations_dir=observations,
            )
        observation = catalog["observation"]
        self.assertIs(True, observation["measured"]["available"])
        self.assertEqual("measured", observation["provenance"])
        self.assertEqual(
            ["/instances/default/digital_twin/obs/ami.csv"],
            observation["measured"]["sources"],
        )
        self.assertEqual(
            "/instances/default/digital_twin/obs/entity_join.csv",
            observation["measured"]["entity_join"],
        )
        # The scenario's own numbers are still solver output; the instance
        # carrying measurements does not relabel them.
        self.assertEqual("simulated", catalog["scenarios"][0]["provenance"])

    def test_the_export_contract_travels_with_the_declaration(self):
        measured = self._catalog()["observation"]["measured"]
        self.assertEqual(
            ["timestamp", "entity_id", "quantity", "value"], measured["columns"]
        )
        self.assertEqual(["voltage_pu"], measured["quantities"])
        self.assertEqual(["entity_id", "bus_id"], measured["join_columns"])


class DashboardCatalogPathAnchoringTest(unittest.TestCase):
    """Declared parquet paths must reach the dashboard as servable URLs.

    Root cause of tracked-tree finding #40. Summaries written before the
    2026-05-19 instance-path unification (commit 25dbeb7a) declare their
    parquet locations relative to the *instance* -- ``digital_twin/...`` --
    while the dashboard mounts ``/instances/default/digital_twin``. Passing a
    declared path through verbatim emitted ``/digital_twin/...``, which 404s;
    and because the summary that carries them is git-ignored, regenerating the
    catalog silently rewrote the tracked ``catalog.json`` into that broken
    form. The consumers pin the served prefix: ``dashboard/src/useDuckDB.js``,
    ``dashboard/vite.config.js`` and ``dashboard/docker-compose.yml``.
    """

    def test_pre_unification_declared_paths_are_reanchored(self):
        catalog = build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={
                "scenarios": [
                    {
                        "scenario_id": "S0",
                        "paths": {
                            kind: f"digital_twin/timeseries/S0_{suffix}.parquet"
                            for kind, suffix in _FILE_KINDS.items()
                        },
                    }
                ]
            },
            optional_extensions=None,
            root=Path("/nonexistent-workspace"),
        )

        for kind, url in catalog["scenarios"][0]["paths"].items():
            with self.subTest(kind=kind):
                self.assertTrue(
                    url.startswith("/instances/default/digital_twin/"),
                    f"{kind} would 404 in the dashboard: {url!r}",
                )

    def test_current_form_declared_paths_are_unchanged(self):
        """Re-anchoring must be a no-op on paths already in the current form."""
        declared = {
            kind: f"instances/default/digital_twin/timeseries/S0_{suffix}.parquet"
            for kind, suffix in _FILE_KINDS.items()
        }
        catalog = build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0", "paths": declared}]},
            optional_extensions=None,
            root=Path("/nonexistent-workspace"),
        )

        self.assertEqual(
            {kind: "/" + value for kind, value in declared.items()},
            catalog["scenarios"][0]["paths"],
        )

    def test_fallback_paths_keep_the_served_prefix(self):
        """A summary with no declared paths still yields servable URLs."""
        catalog = build_dashboard_catalog(
            scenario_index={"scenarios": [{"scenario_id": "S0"}]},
            powerflow_summary={"scenarios": [{"scenario_id": "S0"}]},
            optional_extensions=None,
            root=Path("/nonexistent-workspace"),
        )

        for kind, url in catalog["scenarios"][0]["paths"].items():
            with self.subTest(kind=kind):
                self.assertTrue(url.startswith("/instances/default/digital_twin/"))


if __name__ == "__main__":
    unittest.main()

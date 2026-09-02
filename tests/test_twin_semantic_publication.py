"""The twin's ontology must reach a consumer as classes, not as a node count.

The semantic layer has shipped since Phase 9 and never reached a client in a
usable form: the dashboard read four scalars off ``graph_manifest.json`` by
hardcoded path. These tests pin what
:mod:`gridalyn.twin.semantic.publication` resolves instead -- the three class
populations, the fact that they do NOT coincide, and the honest renderings for
a twin that has none of it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.twin.network.schema import (
    BASE_TABLE_SCHEMAS,
    ROLE_ONTOLOGY_CLASS,
    table_schema,
)
from gridalyn.twin.semantic.publication import (
    CLASSES_ABSENT_REASON,
    POPULATION_BASE,
    POPULATION_GRAPH,
    POPULATION_SCENARIO,
    read_graph_manifest,
    resolve_base_ontology_classes,
    resolve_graph_ontology_classes,
    resolve_scenario_ontology_classes,
    resolve_semantic_publication,
    semantic_artifact_filenames,
)


def _base_frames() -> dict[str, pd.DataFrame]:
    """Return base tables in the shape the shipped adapters write them."""
    return {
        "grid_buses": pd.DataFrame(
            [
                {
                    "bus_id": "bus:0",
                    "lat": 46.3,
                    "lon": -72.6,
                    "cim_class": "ConnectivityNode",
                },
                {
                    "bus_id": "bus:1",
                    "lat": 46.4,
                    "lon": -72.5,
                    "cim_class": "ConnectivityNode",
                },
            ]
        ),
        "grid_lines": pd.DataFrame(
            [
                {
                    "line_id": "line:0",
                    "from_bus_id": "bus:0",
                    "to_bus_id": "bus:1",
                    "cim_class": "ACLineSegment",
                }
            ]
        ),
        "buildings": pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "lat": 46.35,
                    "lon": -72.55,
                    "ontology_class": "Building",
                }
            ]
        ),
    }


class DeclaredOntologyColumnTest(unittest.TestCase):
    """The class column is declared in the schema, not read by guess.

    ``gridalyn/twin/network/schema.py`` is the single place base columns are
    declared, and the class column was the one load-bearing column missing
    from it -- every consumer that wanted it had to hardcode a spelling.
    """

    def test_every_class_carrying_table_declares_the_role(self):
        for artifact in ("grid_buses", "grid_lines", "grid_transformers", "buildings"):
            with self.subTest(artifact=artifact):
                self.assertIn(ROLE_ONTOLOGY_CLASS, table_schema(artifact).roles)

    def test_connectivity_declares_no_class_because_no_producer_writes_one(self):
        """Absence is evidence too: neither adapter writes a class here."""
        self.assertNotIn(
            ROLE_ONTOLOGY_CLASS,
            table_schema("building_grid_connectivity").roles,
        )

    def test_buildings_accepts_both_producer_spellings(self):
        """SyntheticPandapowerAdapter writes one spelling, CimParquetAdapter another."""
        spellings = table_schema("buildings").spellings(ROLE_ONTOLOGY_CLASS)
        self.assertEqual(("ontology_class", "cim_class"), spellings)

    def test_cim_spelling_resolves_when_it_is_the_only_one_present(self):
        frame = pd.DataFrame(
            [{"building_id": "b:0", "load_id": "l:0", "cim_class": "EnergyConsumer"}]
        )
        self.assertEqual(
            "cim_class",
            table_schema("buildings").resolve(frame, ROLE_ONTOLOGY_CLASS),
        )
        classes = resolve_base_ontology_classes({"buildings": frame})
        self.assertEqual(["EnergyConsumer"], [entry.name for entry in classes])


class BaseOntologyClassTest(unittest.TestCase):
    def test_each_base_table_reports_its_class_with_a_count(self):
        classes = resolve_base_ontology_classes(_base_frames())
        self.assertEqual(
            [
                ("grid_buses", "ConnectivityNode", 2),
                ("grid_lines", "ACLineSegment", 1),
                ("buildings", "Building", 1),
            ],
            [(entry.artifact, entry.name, entry.count) for entry in classes],
        )
        self.assertEqual({POPULATION_BASE}, {entry.population for entry in classes})

    def test_a_drawable_class_names_the_columns_holding_its_position(self):
        """A client told only "drawable" would have to assume lat/lon."""
        by_artifact = {
            entry.artifact: entry
            for entry in resolve_base_ontology_classes(_base_frames())
        }
        self.assertEqual(
            {"latitude": "lat", "longitude": "lon"},
            dict(by_artifact["grid_buses"].coordinates),
        )
        self.assertIsNone(by_artifact["grid_lines"].coordinates)
        self.assertEqual("bus_id", by_artifact["grid_buses"].identity)
        self.assertEqual("building_id", by_artifact["buildings"].identity)

    def test_located_distinguishes_a_drawable_class_from_a_derived_one(self):
        by_artifact = {
            entry.artifact: entry
            for entry in resolve_base_ontology_classes(_base_frames())
        }
        self.assertTrue(by_artifact["grid_buses"].located)
        self.assertTrue(by_artifact["buildings"].located)
        # Lines carry endpoints, not positions -- the geography block already
        # declares their geometry as derived, and the class must agree.
        self.assertFalse(by_artifact["grid_lines"].located)

    def test_a_table_without_the_column_is_skipped_not_failed(self):
        frames = _base_frames()
        frames["buildings"] = frames["buildings"].drop(columns=["ontology_class"])
        artifacts = [entry.artifact for entry in resolve_base_ontology_classes(frames)]
        self.assertNotIn("buildings", artifacts)
        self.assertIn("grid_buses", artifacts)

    def test_an_empty_mapping_yields_no_classes(self):
        self.assertEqual((), resolve_base_ontology_classes({}))


class GraphOntologyClassTest(unittest.TestCase):
    def _nodes(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"semantic_type": "brick:Building", "source_table": "buildings"},
                {"semantic_type": "brick:Building", "source_table": "buildings"},
                {"semantic_type": "cim:EnergyConsumer", "source_table": "buildings"},
                {"semantic_type": "dt:SimulationRun", "source_table": "ev_load"},
                {"semantic_type": "dt:SimulationRun", "source_table": "powerflow"},
            ]
        )

    def test_classes_are_counted_from_the_node_table(self):
        classes = resolve_graph_ontology_classes(self._nodes())
        self.assertEqual(
            [("brick:Building", 2), ("cim:EnergyConsumer", 1), ("dt:SimulationRun", 2)],
            [(entry.name, entry.count) for entry in classes],
        )
        self.assertEqual({POPULATION_GRAPH}, {entry.population for entry in classes})

    def test_derived_from_links_a_graph_class_back_to_its_source_table(self):
        by_name = {
            entry.name: entry for entry in resolve_graph_ontology_classes(self._nodes())
        }
        self.assertEqual(("buildings",), by_name["brick:Building"].derived_from)
        self.assertEqual(
            ("ev_load", "powerflow"), by_name["dt:SimulationRun"].derived_from
        )

    def test_graph_nodes_are_not_located(self):
        """The node table carries no coordinate columns; claiming otherwise
        would promise a consumer a geometry it cannot query."""
        classes = resolve_graph_ontology_classes(self._nodes())
        self.assertFalse(any(entry.located for entry in classes))

    def test_a_node_table_without_the_class_column_yields_nothing(self):
        frame = pd.DataFrame([{"node_id": "n:0"}])
        self.assertEqual((), resolve_graph_ontology_classes(frame))


class ScenarioOntologyClassTest(unittest.TestCase):
    def _assets(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "scenario_id": "S0",
                    "lat": 46.3,
                    "lon": -72.6,
                    "ontology_class": "Building",
                },
                {
                    "scenario_id": "S1",
                    "lat": 46.3,
                    "lon": -72.6,
                    "ontology_class": "Building",
                },
                {
                    "scenario_id": "S1",
                    "lat": 46.4,
                    "lon": -72.5,
                    "ontology_class": "EVChargingAsset",
                },
            ]
        )

    def test_counts_are_scoped_to_a_scenario(self):
        classes = resolve_scenario_ontology_classes(self._assets())
        self.assertEqual(
            [
                ("S0", "Building", 1),
                ("S1", "Building", 1),
                ("S1", "EVChargingAsset", 1),
            ],
            [(entry.scenario_id, entry.name, entry.count) for entry in classes],
        )
        self.assertEqual({POPULATION_SCENARIO}, {entry.population for entry in classes})

    def test_the_registry_is_located_so_a_class_can_be_drawn(self):
        classes = resolve_scenario_ontology_classes(self._assets())
        self.assertTrue(all(entry.located for entry in classes))
        self.assertEqual(
            {"latitude": "lat", "longitude": "lon"}, dict(classes[0].coordinates)
        )

    def test_a_registry_without_coordinates_is_reported_as_undrawable(self):
        frame = self._assets().drop(columns=["lat", "lon"])
        classes = resolve_scenario_ontology_classes(frame)
        self.assertTrue(classes)
        self.assertFalse(any(entry.located for entry in classes))
        self.assertTrue(all(entry.coordinates is None for entry in classes))

    def test_the_scenario_column_is_declared_not_assumed(self):
        classes = resolve_scenario_ontology_classes(self._assets())
        self.assertEqual({"scenario_id"}, {e.scenario_column for e in classes})

    def test_a_registry_without_scenarios_reports_unscoped_classes(self):
        frame = self._assets().drop(columns=["scenario_id"])
        classes = resolve_scenario_ontology_classes(frame)
        self.assertEqual([None, None], [entry.scenario_id for entry in classes])
        self.assertEqual([None, None], [entry.scenario_column for entry in classes])
        self.assertEqual(
            [("Building", 2), ("EVChargingAsset", 1)],
            [(entry.name, entry.count) for entry in classes],
        )


class SemanticPublicationTest(unittest.TestCase):
    def _manifest(self) -> dict:
        return {
            "semantic_profile": "north_america",
            "node_count": 74286,
            "edge_count": 147065,
            "validation": {"valid": True, "error_count": 0, "warning_count": 2},
        }

    def test_the_three_populations_do_not_coincide_and_each_says_so(self):
        """The measured fact this module exists for.

        ``buildings.ontology_class`` says ``Building``; the graph says
        ``brick:Building`` *and* ``cim:EnergyConsumer`` for the same rows.
        Publishing one population as "the ontology classes" would leave the
        consumer to discover the rest by reading files.
        """
        publication = resolve_semantic_publication(
            manifest=self._manifest(),
            base_frames=_base_frames(),
            graph_nodes=pd.DataFrame(
                [
                    {"semantic_type": "brick:Building", "source_table": "buildings"},
                    {
                        "semantic_type": "cim:EnergyConsumer",
                        "source_table": "buildings",
                    },
                ]
            ),
            scenario_assets=pd.DataFrame(
                [{"scenario_id": "S1", "ontology_class": "EVChargingAsset"}]
            ),
        )
        self.assertEqual(
            (POPULATION_BASE, POPULATION_GRAPH, POPULATION_SCENARIO),
            publication.populations,
        )
        base_names = {entry.name for entry in publication.classes_in(POPULATION_BASE)}
        graph_names = {entry.name for entry in publication.classes_in(POPULATION_GRAPH)}
        self.assertIn("Building", base_names)
        self.assertNotIn("Building", graph_names)
        self.assertIn("brick:Building", graph_names)
        self.assertEqual(1, len(publication.classes_in(POPULATION_SCENARIO)))

    def test_graph_counts_and_verdict_come_from_the_manifest(self):
        publication = resolve_semantic_publication(manifest=self._manifest())
        self.assertEqual("north_america", publication.profile)
        self.assertEqual(74286, publication.node_count)
        self.assertEqual(147065, publication.edge_count)
        self.assertIs(True, publication.valid)
        self.assertEqual(0, publication.errors)
        self.assertEqual(2, publication.warnings)

    def test_an_unchecked_graph_reports_none_not_false(self):
        """``None`` is "not checked"; ``False`` is "checked and invalid"."""
        publication = resolve_semantic_publication(
            manifest={"semantic_profile": "north_america"}
        )
        self.assertIsNone(publication.valid)
        self.assertIsNone(publication.errors)

    def test_a_twin_with_no_ontology_states_why_rather_than_going_quiet(self):
        publication = resolve_semantic_publication()
        payload = publication.to_dict()
        self.assertEqual([], payload["classes"])
        self.assertEqual(CLASSES_ABSENT_REASON, payload["classes_absent_reason"])
        self.assertIsNone(payload["profile"])

    def test_a_populated_publication_carries_no_absent_reason(self):
        publication = resolve_semantic_publication(
            manifest=self._manifest(), base_frames=_base_frames()
        )
        self.assertIsNone(publication.to_dict()["classes_absent_reason"])

    def test_every_class_entry_names_where_it_was_read_from(self):
        payload = resolve_semantic_publication(
            manifest=self._manifest(), base_frames=_base_frames()
        ).to_dict()
        for entry in payload["classes"]:
            with self.subTest(entry=entry["class"]):
                self.assertEqual(
                    sorted(entry),
                    [
                        "artifact",
                        "class",
                        "column",
                        "coordinates",
                        "count",
                        "derived_from",
                        "identity",
                        "located",
                        "population",
                        "scenario_column",
                        "scenario_id",
                    ],
                )


class SemanticArtifactPathTest(unittest.TestCase):
    def test_the_profile_filename_carries_the_profile_id(self):
        names = semantic_artifact_filenames("north_america")
        self.assertEqual("profile_north_america.json", names["profile"])

    def test_no_profile_means_no_guessed_profile_path(self):
        self.assertNotIn("profile", semantic_artifact_filenames(None))

    def test_a_missing_manifest_reads_as_empty_not_as_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({}, read_graph_manifest(tmp))

    def test_an_unparseable_manifest_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "graph_manifest.json").write_text(
                "{not json", encoding="utf-8"
            )
            self.assertEqual({}, read_graph_manifest(tmp))

    def test_a_manifest_is_read_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "graph_manifest.json").write_text(
                json.dumps({"semantic_profile": "north_america"}), encoding="utf-8"
            )
            self.assertEqual(
                "north_america", read_graph_manifest(tmp)["semantic_profile"]
            )


class DeclaredScheduleCoverageTest(unittest.TestCase):
    def test_the_class_role_is_declared_on_exactly_the_measured_tables(self):
        """Pins the measurement rather than the intent.

        Four of the five base artifacts carry a class column; adding the role
        to the fifth would be tolerance, not evidence, and dropping it from one
        of the four would silently shrink what the catalog publishes.
        """
        declaring = sorted(
            artifact
            for artifact, schema in BASE_TABLE_SCHEMAS.items()
            if ROLE_ONTOLOGY_CLASS in schema.roles
        )
        self.assertEqual(
            ["buildings", "grid_buses", "grid_lines", "grid_transformers"], declaring
        )


if __name__ == "__main__":
    unittest.main()

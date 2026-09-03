"""A scenario is a declared contract, not a shape every consumer assumes.

The dashboard could show one source's scenarios: the twin's. It wrote the four
per-scenario artifact kinds into three separate files and synthesized the
twin's on-disk path layout in the client. A study's scenarios could not reach
it at all -- not because studies have none, but because `ieee_33_bus_demo`
partitions the other way: one artifact holding every scenario, discriminated by
a column, against the twin's one artifact per scenario and kind.

These tests pin the discriminator that lets one contract serve both.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gridalyn.projects.scenario_catalog import (
    BY_COLUMN,
    BY_FILE,
    DEFAULT_ID_COLUMN,
    SCENARIO_TOKEN,
    ScenarioContractError,
    read_scenario_contract,
    read_scenario_index,
)

_YAML = Path("project.yaml")


def _column_spec() -> dict:
    return {
        "scenarios": {
            "index": "outputs/data/scenarios.csv",
            "labelColumn": "description",
            "artifacts": {
                "results": {
                    "path": "outputs/data/scenario_results.csv",
                    "partitioning": "column",
                }
            },
        }
    }


def _file_spec() -> dict:
    return {
        "scenarios": {
            "index": "outputs/data/index.json",
            "artifacts": {
                "nodes": {
                    "path": "outputs/data/{scenario_id}_nodes.parquet",
                    "partitioning": "file",
                }
            },
        }
    }


class ScenarioContractTest(unittest.TestCase):
    def test_a_study_that_declares_none_gets_none(self) -> None:
        """The normal case. Most studies have no scenarios and are not broken."""
        self.assertIsNone(read_scenario_contract({}, path=_YAML))
        self.assertIsNone(read_scenario_contract(None, path=_YAML))

    def test_the_two_partitionings_are_both_first_class(self) -> None:
        column = read_scenario_contract(_column_spec(), path=_YAML)
        by_file = read_scenario_contract(_file_spec(), path=_YAML)
        assert column is not None and by_file is not None
        self.assertEqual(BY_COLUMN, column.artifacts[0].partitioning)
        self.assertEqual(BY_FILE, by_file.artifacts[0].partitioning)

    def test_a_file_partitioned_path_resolves_per_scenario(self) -> None:
        contract = read_scenario_contract(_file_spec(), path=_YAML)
        assert contract is not None
        self.assertEqual(
            "outputs/data/S0_nodes.parquet", contract.artifacts[0].resolve("S0")
        )

    def test_a_column_partitioned_path_is_the_same_for_every_scenario(self) -> None:
        """One artifact holds them all; a column selects, not the path."""
        contract = read_scenario_contract(_column_spec(), path=_YAML)
        assert contract is not None
        artifact = contract.artifacts[0]
        self.assertEqual(artifact.resolve("baseline"), artifact.resolve("pv_midday"))
        self.assertEqual(DEFAULT_ID_COLUMN, artifact.id_column)

    def test_kinds_are_whatever_the_study_names(self) -> None:
        """No fixed set anywhere -- that set was the coupling."""
        spec = _column_spec()
        spec["scenarios"]["artifacts"]["something_nobody_anticipated"] = {
            "path": "outputs/data/x.csv",
            "partitioning": "column",
        }
        contract = read_scenario_contract(spec, path=_YAML)
        assert contract is not None
        self.assertIn("something_nobody_anticipated", contract.kinds)

    def test_a_file_partition_without_the_token_is_refused(self) -> None:
        """Otherwise every scenario would resolve to the same file."""
        spec = _file_spec()
        spec["scenarios"]["artifacts"]["nodes"]["path"] = "outputs/data/nodes.parquet"
        with self.assertRaises(ScenarioContractError) as caught:
            read_scenario_contract(spec, path=_YAML)
        self.assertIn(SCENARIO_TOKEN, str(caught.exception))
        self.assertIn("every scenario would resolve to one file", str(caught.exception))

    def test_a_column_partition_carrying_the_token_is_refused(self) -> None:
        spec = _column_spec()
        spec["scenarios"]["artifacts"]["results"]["path"] = "d/{scenario_id}.csv"
        with self.assertRaises(ScenarioContractError) as caught:
            read_scenario_contract(spec, path=_YAML)
        self.assertIn("holds every scenario", str(caught.exception))

    def test_an_unknown_partitioning_names_the_valid_set(self) -> None:
        spec = _column_spec()
        spec["scenarios"]["artifacts"]["results"]["partitioning"] = "sharded"
        with self.assertRaises(ScenarioContractError) as caught:
            read_scenario_contract(spec, path=_YAML)
        message = str(caught.exception)
        self.assertIn("sharded", message)
        self.assertIn(BY_FILE, message)
        self.assertIn(BY_COLUMN, message)

    def test_a_contract_naming_no_artifact_is_refused(self) -> None:
        with self.assertRaises(ScenarioContractError) as caught:
            read_scenario_contract(
                {"scenarios": {"index": "i.csv", "artifacts": {}}}, path=_YAML
            )
        self.assertIn("tells a consumer nothing it can read", str(caught.exception))

    def test_every_error_locates_the_file(self) -> None:
        """The model_inputs posture: a message names where and what fixes it."""
        for spec in (
            {"scenarios": "not a mapping"},
            {"scenarios": {"artifacts": {"a": {"path": "x"}}}},
            {"scenarios": {"index": "i.csv", "artifacts": {"a": {}}}},
        ):
            with self.subTest(spec=spec):
                with self.assertRaises(ScenarioContractError) as caught:
                    read_scenario_contract(spec, path=Path("projects/x/project.yaml"))
                self.assertIn("projects/x/project.yaml", str(caught.exception))


class ScenarioIndexTest(unittest.TestCase):
    def test_an_absent_index_is_empty_not_an_error(self) -> None:
        """A study whose outputs were not produced is not a broken study."""
        self.assertEqual(
            (), read_scenario_index(Path("/nowhere.csv"), id_column="scenario_id")
        )

    def test_csv_and_json_indexes_read_alike(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.csv").write_text(
                "scenario_id,description\nS0,Base\nS1,Growth\n", encoding="utf-8"
            )
            (root / "b.json").write_text(
                json.dumps(
                    {
                        "scenarios": [
                            {"scenario_id": "S0", "description": "Base"},
                            {"scenario_id": "S1", "description": "Growth"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            expected = (
                {"scenario_id": "S0", "label": "Base"},
                {"scenario_id": "S1", "label": "Growth"},
            )
            for name in ("a.csv", "b.json"):
                with self.subTest(index=name):
                    self.assertEqual(
                        expected,
                        read_scenario_index(
                            root / name,
                            id_column="scenario_id",
                            label_column="description",
                        ),
                    )

    def test_a_missing_id_column_says_which_to_declare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "a.csv"
            index.write_text("name,value\nS0,1\n", encoding="utf-8")
            with self.assertRaises(ScenarioContractError) as caught:
                read_scenario_index(index, id_column="scenario_id")
        message = str(caught.exception)
        self.assertIn("scenario_id", message)
        self.assertIn("name, value", message)
        self.assertIn("spec.scenarios.idColumn", message)

    def test_duplicates_keep_the_first_and_order_is_the_files(self) -> None:
        """A column-partitioned index legitimately repeats ids per row."""
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "a.csv"
            index.write_text("scenario_id\nb\na\nb\n", encoding="utf-8")
            rows = read_scenario_index(index, id_column="scenario_id")
        self.assertEqual(["b", "a"], [row["scenario_id"] for row in rows])


class ShippedStudyTest(unittest.TestCase):
    """The grounding case: a real study whose scenarios the dashboard missed."""

    ROOT = Path(__file__).resolve().parent.parent / "projects" / "ieee_33_bus_demo"

    def test_it_declares_a_contract(self) -> None:
        import yaml

        spec = yaml.safe_load((self.ROOT / "project.yaml").read_text(encoding="utf-8"))[
            "spec"
        ]
        contract = read_scenario_contract(spec, path=self.ROOT / "project.yaml")
        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(("parameters", "results", "voltage_profiles"), contract.kinds)
        # Column, not file. Asserting the value is the point of the test: the
        # twin partitions the other way, and a consumer that assumed either
        # would misread the other.
        self.assertEqual({BY_COLUMN}, {a.partitioning for a in contract.artifacts})

    def test_its_five_scenarios_are_enumerable(self) -> None:
        rows = read_scenario_index(
            self.ROOT / "outputs" / "data" / "scenarios.csv",
            id_column="scenario_id",
            label_column="description",
        )
        if not rows:
            self.skipTest(
                "ieee_33_bus_demo outputs are absent; run the study to check this"
            )
        self.assertEqual(5, len(rows))
        self.assertEqual("baseline", rows[0]["scenario_id"])
        self.assertTrue(all(row["label"] for row in rows))


if __name__ == "__main__":
    unittest.main()

"""Gates for the declared base-table contract and fail-loud integrity checking.

The defect these pin: with no declared schema, ``_read_table`` returned an empty
frame for a missing file and every check opened ``if frame.empty: return``, so a
completely empty directory reported ``valid=True`` with zero errors. Absent,
empty and intact must be three distinct outcomes.
"""

import ast
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.twin import NetworkModelRepository
from gridalyn.twin.network.model import BASE_TABLE_FILENAMES
from gridalyn.twin.network.schema import (
    BASE_TABLE_SCHEMAS,
    BUILDING_GRID_CONNECTIVITY,
    GRID_BUSES,
    ROLE_BUS,
    ROLE_FEEDER,
    ROLE_FEEDER_CLUSTER,
    ROLE_IDENTITY,
    ROLE_TRANSFORMER,
    table_schema,
)

REPOSITORY_SOURCE = Path("gridalyn/twin/network/repository.py")
COMMITTED_BASE = Path("instances/default/digital_twin/base")


def _repository_identifiers() -> set[str]:
    """Return every live identifier in the repository module, via AST not grep.

    A grep for a removed name matches the docstring that documents the removal,
    forever (retrospective item #3). Only ``ast.Name`` (a read or write of a
    variable) and ``ast.arg`` (a declared parameter) count as *live*; a name
    that survives only inside a string or comment does not.
    """
    tree = ast.parse(REPOSITORY_SOURCE.read_text())
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    args = {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    keywords = {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg is not None
    }
    return names | args | attrs | keywords


def _write_base_model(base: Path, *, connectivity: pd.DataFrame | None = None) -> None:
    """Write a minimal but intact five-table base into ``base``."""
    base.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"bus_id": "bus:lv_0"}, {"bus_id": "bus:load_0"}]).to_parquet(
        base / "grid_buses.parquet"
    )
    pd.DataFrame(
        [{"line_id": "line:0", "from_bus_id": "bus:lv_0", "to_bus_id": "bus:load_0"}]
    ).to_parquet(base / "grid_lines.parquet")
    pd.DataFrame(
        [
            {
                "transformer_id": "transformer:0",
                "hv_bus_id": "bus:lv_0",
                "lv_bus_id": "bus:load_0",
            }
        ]
    ).to_parquet(base / "grid_transformers.parquet")
    pd.DataFrame(
        [{"building_id": "building:0", "load_id": "load:0", "lv_bus_id": "bus:load_0"}]
    ).to_parquet(base / "buildings.parquet")
    if connectivity is None:
        connectivity = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:load_0",
                    "lv_feeder_bus_id": "bus:lv_0",
                    "lv_cluster": 7,
                    "lv_transformer_id": "transformer:0",
                }
            ]
        )
    connectivity.to_parquet(base / "building_grid_connectivity.parquet")


class DeclaredSchemaTest(unittest.TestCase):
    def test_schema_covers_exactly_the_canonical_artifact_list(self):
        self.assertEqual(set(BASE_TABLE_SCHEMAS), set(BASE_TABLE_FILENAMES))
        for artifact, schema in BASE_TABLE_SCHEMAS.items():
            self.assertEqual(schema.filename, BASE_TABLE_FILENAMES[artifact])

    def test_schema_is_a_python_module_so_it_cannot_be_left_out_of_the_wheel(self):
        # Phase-2 lesson: gridalyn/projects/schemas/*.json were resolved at
        # runtime but not shipped, so an installed gridalyn raised
        # FileNotFoundError on its own core contract. A module cannot repeat it.
        import gridalyn.twin.network.schema as module

        self.assertTrue(module.__file__ is not None)
        self.assertTrue(module.__file__.endswith(".py"))
        source = Path(module.__file__).read_text()
        for reader in ("open(", "read_text(", "json.load", "importlib.resources"):
            self.assertNotIn(
                reader,
                source,
                f"the declared schema reads {reader!r} at runtime, which "
                "reintroduces the Phase-2 package-data bug class",
            )

    def test_unwritten_connectivity_spellings_are_dropped_not_carried(self):
        # No in-repo producer writes `transformer_id` or `constraint_zone_id`
        # into building_grid_connectivity; both were guesses, not aliases.
        spellings = table_schema(BUILDING_GRID_CONNECTIVITY).spellings(ROLE_TRANSFORMER)
        self.assertEqual(spellings, ("lv_transformer_id",))

    def test_feeder_resolution_order_is_the_historical_one(self):
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        ordered = schema.spellings(ROLE_FEEDER) + schema.spellings(ROLE_FEEDER_CLUSTER)
        self.assertEqual(ordered, ("feeder_id", "lv_feeder_bus_id", "lv_cluster"))
        # lv_cluster is a producer-local integer label, not an identifier.
        self.assertEqual(schema.spec(ROLE_FEEDER_CLUSTER).dtype, "integer")
        self.assertEqual(schema.spec(ROLE_FEEDER).dtype, "string")

    def test_bus_endpoint_columns_come_from_the_declaration(self):
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        self.assertEqual(
            schema.reference_spellings(GRID_BUSES),
            ("load_bus_id", "lv_bus_id", "bus_id", "lv_feeder_bus_id"),
        )

    def test_unknown_role_names_the_declared_roles(self):
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        with self.assertRaises(ValueError) as caught:
            schema.spec("substation")
        message = str(caught.exception)
        self.assertIn("building_grid_connectivity.parquet", message)
        self.assertIn("declared roles:", message)
        self.assertIn(ROLE_TRANSFORMER, message)

    def test_unknown_artifact_names_the_declared_artifacts(self):
        with self.assertRaises(ValueError) as caught:
            table_schema("grid_switches")
        self.assertIn("grid_switches", str(caught.exception))
        self.assertIn("grid_buses", str(caught.exception))


class ProducerConformanceTest(unittest.TestCase):
    """Both in-repo producers must satisfy the contract they are declared from."""

    def test_synthetic_producer_dialect_resolves(self):
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        frame = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:0",
                    "lv_cluster": 7,
                    "lv_feeder_bus_id": "bus:lv_0",
                    "lv_transformer_id": "transformer:0",
                    "connectivity_status": "ok",
                }
            ]
        )
        self.assertEqual(schema.absent_required_roles(frame), ())
        self.assertEqual(schema.resolve(frame, ROLE_BUS), "load_bus_id")
        self.assertEqual(schema.resolve(frame, ROLE_FEEDER), "lv_feeder_bus_id")
        self.assertEqual(schema.resolve(frame, ROLE_TRANSFORMER), "lv_transformer_id")

    def test_cim_producer_dialect_resolves(self):
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        frame = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:0",
                    "lv_bus_id": "bus:0",
                    "lv_transformer_id": "transformer:0",
                    "feeder_id": "feeder:demo",
                    "connectivity_status": "ok",
                }
            ]
        )
        self.assertEqual(schema.absent_required_roles(frame), ())
        # The CIM dialect is why `feeder_id` is kept rather than collapsed.
        self.assertEqual(schema.resolve(frame, ROLE_FEEDER), "feeder_id")

    def test_cim_adapter_really_writes_the_feeder_id_dialect(self):
        from gridalyn.twin.adapters.cim import CimParquetAdapter

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cim_source"
            source.mkdir(parents=True)
            pd.DataFrame([{"mRID": "cn-lv", "nominal_voltage_kv": 0.4}]).to_parquet(
                source / "connectivity_nodes.parquet", index=False
            )
            pd.DataFrame(
                [
                    {
                        "mRID": "ec-1",
                        "connectivity_node": "cn-lv",
                        "building_id": "building:cim:1",
                        "load_id": "load:cim:1",
                        "feeder_id": "feeder:demo",
                    }
                ]
            ).to_parquet(source / "energy_consumers.parquet", index=False)
            connectivity = CimParquetAdapter(source_dir=source).load_snapshot()

        self.assertIn("feeder_id", connectivity.connectivity.columns)
        self.assertIn("lv_transformer_id", connectivity.connectivity.columns)
        self.assertNotIn("lv_feeder_bus_id", connectivity.connectivity.columns)


class AbsentEmptyIntactTest(unittest.TestCase):
    def test_an_absent_base_fails_loudly_and_says_what_to_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = NetworkModelRepository.from_parquet(tmp, provenance="ignore")
            report = repo.validate_integrity()

        self.assertFalse(
            report.valid,
            "an empty directory must not report itself as an intact network",
        )
        self.assertEqual(len(report.errors), len(BASE_TABLE_FILENAMES))
        joined = "\n".join(report.errors)
        for filename in BASE_TABLE_FILENAMES.values():
            self.assertIn(filename, joined)
        self.assertIn("is absent", joined)
        self.assertIn("gridalyn twin base", joined)
        self.assertIn(str(tmp), joined)

    def test_a_present_but_empty_artifact_is_a_warning_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(base)
            pd.DataFrame({"transformer_id": []}).to_parquet(
                base / "grid_transformers.parquet"
            )
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            report = repo.validate_integrity()

        self.assertTrue(report.valid, report.errors)
        joined = "\n".join(report.warnings)
        self.assertIn("grid_transformers.parquet", joined)
        self.assertIn("zero rows", joined)

    def test_an_intact_base_is_valid_with_no_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(base)
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            report = repo.validate_integrity()

        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.warnings, ())

    def test_the_three_states_are_distinguishable_from_the_report_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(base)
            intact = NetworkModelRepository.from_parquet(
                base, provenance="ignore"
            ).validate_integrity()
            pd.DataFrame({"line_id": []}).to_parquet(base / "grid_lines.parquet")
            empty = NetworkModelRepository.from_parquet(
                base, provenance="ignore"
            ).validate_integrity()
            (base / "grid_lines.parquet").unlink()
            absent = NetworkModelRepository.from_parquet(
                base, provenance="ignore"
            ).validate_integrity()

        self.assertEqual(
            (intact.valid, len(intact.warnings)),
            (True, 0),
            "intact",
        )
        self.assertEqual((empty.valid, len(empty.warnings)), (True, 1), "empty")
        self.assertFalse(absent.valid, "absent")
        self.assertEqual(absent.warnings, ())

    def test_a_row_bearing_artifact_missing_a_required_column_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(
                base,
                connectivity=pd.DataFrame(
                    [{"building_id": "building:0", "load_id": "load:0"}]
                ),
            )
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            report = repo.validate_integrity()

        self.assertFalse(report.valid)
        joined = "\n".join(report.errors)
        self.assertIn("building_grid_connectivity.parquet", joined)
        self.assertIn("load_bus_id", joined)
        self.assertIn("present columns: building_id, load_id", joined)


class DeclaredDtypeEnforcementTest(unittest.TestCase):
    """``ColumnSpec.dtype="integer"`` is enforced by ``validate_integrity``.

    Milestone-6 leftover: the dtype field was declared but had zero enforcement
    reads, so a connectivity table carrying strings under ``lv_cluster`` --
    the single integer-declared column -- validated as intact.
    """

    def _report_for_lv_cluster(self, values):
        """Validate an otherwise-intact base whose ``lv_cluster`` holds ``values``."""
        connectivity = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:load_0",
                    "lv_feeder_bus_id": "bus:lv_0",
                    "lv_cluster": value,
                    "lv_transformer_id": "transformer:0",
                }
                for value in values
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(base, connectivity=connectivity)
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            return repo.validate_integrity()

    def test_integer_declared_column_with_uncastable_values_is_an_integrity_error(
        self,
    ):
        report = self._report_for_lv_cluster(["a", "b"])

        self.assertFalse(
            report.valid,
            "an integer-declared column full of uncastable strings must not "
            "validate as an intact base",
        )
        joined = "\n".join(report.errors)
        self.assertIn("building_grid_connectivity.parquet", joined)
        self.assertIn("'lv_cluster'", joined)
        self.assertIn("2 value(s)", joined)

    def test_integer_declared_column_with_non_integral_values_is_an_integrity_error(
        self,
    ):
        # "integer" means integral, not merely numeric-castable: 1.5 coerces
        # cleanly with pd.to_numeric but is not an integer label.
        report = self._report_for_lv_cluster([1.5, 2.0])

        self.assertFalse(
            report.valid,
            "a numeric but non-integral lv_cluster must not validate",
        )
        joined = "\n".join(report.errors)
        self.assertIn("building_grid_connectivity.parquet", joined)
        self.assertIn("'lv_cluster'", joined)
        self.assertIn("1 value(s)", joined)


class QueryVocabularyTest(unittest.TestCase):
    def test_constraint_id_is_gone_as_a_live_identifier(self):
        identifiers = _repository_identifiers()
        self.assertNotIn("constraint_id", identifiers)
        self.assertNotIn("constraint_zone_id", identifiers)
        # ...and the replacement really is live, so the check cannot pass
        # vacuously against a module that lost the concept altogether.
        self.assertIn("upstream_id", identifiers)

    def test_column_guessing_helper_is_gone_as_a_live_identifier(self):
        self.assertNotIn("_first_existing_column", _repository_identifiers())

    def test_queries_key_their_result_by_the_element_they_were_asked_about(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(base)
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            downstream = repo.get_downstream("transformer:0")
            feeder = repo.get_feeder("bus:lv_0")

        self.assertEqual(downstream.upstream_id, "transformer:0")
        self.assertEqual(feeder.upstream_id, "bus:lv_0")
        self.assertEqual(downstream.building_ids, ("building:0",))
        self.assertEqual(feeder.building_ids, ("building:0",))

    def test_a_connectivity_table_without_a_feeder_column_says_what_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_base_model(
                base,
                connectivity=pd.DataFrame(
                    [
                        {
                            "building_id": "building:0",
                            "load_id": "load:0",
                            "load_bus_id": "bus:load_0",
                            "lv_transformer_id": "transformer:0",
                        }
                    ]
                ),
            )
            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            with self.assertRaises(ValueError) as caught:
                repo.get_feeder("bus:lv_0")

        message = str(caught.exception)
        self.assertIn("building_grid_connectivity.parquet", message)
        self.assertIn("feeder_id, lv_feeder_bus_id, lv_cluster", message)
        self.assertIn("present columns: building_id, load_id", message)
        self.assertIn("gridalyn twin base", message)


class CommittedBaseConformanceTest(unittest.TestCase):
    """The committed base is gitignored, so this is operator-verified."""

    @unittest.skipUnless(
        (COMMITTED_BASE / "building_grid_connectivity.parquet").exists(),
        "instances/default/digital_twin/base/*.parquet are untracked local "
        "artifacts; this conformance check is operator-verified, not CI-gated",
    )
    def test_the_committed_base_satisfies_the_declared_contract(self):
        for artifact, schema in BASE_TABLE_SCHEMAS.items():
            frame = pd.read_parquet(COMMITTED_BASE / schema.filename)
            self.assertEqual(
                schema.absent_required_roles(frame),
                (),
                f"{artifact} does not satisfy its declared required columns",
            )
            identity = schema.resolve(frame, ROLE_IDENTITY)
            assert identity is not None
            self.assertEqual(
                frame[identity].dtype.kind,
                "O",
                f"{artifact}.{identity} is declared a string identifier",
            )

    @unittest.skipUnless(
        (COMMITTED_BASE / "building_grid_connectivity.parquet").exists(),
        "operator-verified: the committed base parquet files are untracked",
    )
    def test_the_committed_base_uses_the_synthetic_dialect(self):
        frame = pd.read_parquet(COMMITTED_BASE / "building_grid_connectivity.parquet")
        self.assertIn("lv_transformer_id", frame.columns)
        self.assertIn("lv_feeder_bus_id", frame.columns)
        self.assertNotIn("feeder_id", frame.columns)
        self.assertNotIn("transformer_id", frame.columns)
        self.assertNotIn("constraint_zone_id", frame.columns)
        # lv_cluster really is an integer label, which is why it resolves last.
        self.assertEqual(frame["lv_cluster"].dtype.kind, "i")


if __name__ == "__main__":
    unittest.main()

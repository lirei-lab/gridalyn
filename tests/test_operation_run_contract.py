import json
import tempfile
import unittest
from pathlib import Path

from gridalyn.operations.runs import (
    OperationRun,
    build_operation_run,
    validate_operation_run,
    write_operation_run,
)


class OperationRunContractTest(unittest.TestCase):
    def test_build_operation_run_captures_governance_artifacts_and_kpis(self):
        run = build_operation_run(
            operation_id="operation:S4:surrogate:sha256:test",
            operation_type="flexibility_clearing",
            scenario_id="S4",
            network_model_version_id="model:sha256:test",
            study_run_id="run:ev:test",
            clearing_method="surrogate",
            status="completed",
            input_artifacts={
                "provider_registry": "instances/default/digital_twin/flexibility/provider_registry.parquet",
            },
            output_artifacts={
                "dispatch_instructions": "projects/ev_hosting_flex/outputs/operations/dispatch_instructions.parquet",
            },
            kpi_report="projects/ev_hosting_flex/outputs/reports/operational_kpi_report.json",
            validation={"valid": True, "errors": [], "warnings": []},
            metrics={"delivered_mwh": 1.25, "shortfall_mwh": 0.0},
        )

        payload = run.to_dict()

        self.assertIsInstance(run, OperationRun)
        self.assertEqual(payload["report_id"], "operation_run")
        self.assertEqual(payload["operation_id"], "operation:S4:surrogate:sha256:test")
        self.assertEqual(payload["operation_type"], "flexibility_clearing")
        self.assertEqual(payload["scenario_id"], "S4")
        self.assertEqual(payload["governance"]["network_model_version_id"], "model:sha256:test")
        self.assertEqual(payload["governance"]["study_run_id"], "run:ev:test")
        self.assertEqual(payload["input_artifacts"]["provider_registry"], "instances/default/digital_twin/flexibility/provider_registry.parquet")
        self.assertEqual(payload["output_artifacts"]["dispatch_instructions"], "projects/ev_hosting_flex/outputs/operations/dispatch_instructions.parquet")
        self.assertEqual(payload["kpi_report"], "projects/ev_hosting_flex/outputs/reports/operational_kpi_report.json")
        self.assertTrue(validate_operation_run(payload).valid)

    def test_validate_operation_run_rejects_missing_core_lineage(self):
        result = validate_operation_run(
            {
                "report_id": "operation_run",
                "operation_id": "",
                "operation_type": "flexibility_clearing",
                "scenario_id": "S4",
                "governance": {},
                "input_artifacts": {},
                "output_artifacts": {},
            }
        )

        self.assertFalse(result.valid)
        self.assertIn("operation_id is required", result.errors)
        self.assertIn("governance.network_model_version_id is required", result.errors)
        self.assertIn("kpi_report is required", result.errors)

    def test_write_operation_run_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operations" / "operation_run.json"
            run = build_operation_run(
                operation_id="operation:S4:surrogate:sha256:test",
                operation_type="flexibility_clearing",
                scenario_id="S4",
                network_model_version_id="model:sha256:test",
                study_run_id=None,
                input_artifacts={"requirements": "instances/default/digital_twin/flexibility/locational_clearing_events.parquet"},
                output_artifacts={"settlement_records": "projects/ev_hosting_flex/outputs/operations/settlement_records.parquet"},
                kpi_report="projects/ev_hosting_flex/outputs/reports/operational_kpi_report.json",
            )

            written = write_operation_run(path, run)

            self.assertEqual(written, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["operation_id"], run.operation_id)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.operations.artifacts import (
    materialize_flexibility_operation_artifacts,
)


# The study that used to wrap this materialiser was retired; the wrapper only
# bound ``project_id``, so the SDK entry point is exercised directly against
# the project that ships it today.
PROJECT_ID = "ev_hosting_flex"


class EvProjectOperationalArtifactsTest(unittest.TestCase):
    def test_materializer_writes_operation_tables_and_kpi_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "instances" / "default" / "digital_twin" / "flexibility"
            input_dir.mkdir(parents=True)
            base_dir = root / "instances" / "default" / "digital_twin" / "base"
            base_dir.mkdir(parents=True)
            manifests_dir = root / "projects" / PROJECT_ID / "outputs" / "manifests"
            manifests_dir.mkdir(parents=True)

            (base_dir / "metadata.json").write_text(
                json.dumps({"model_version_id": "model:sha256:test"}),
                encoding="utf-8",
            )
            (manifests_dir / "project_run_manifest.json").write_text(
                json.dumps({"study_run": {"run_id": "run:ev:test"}}),
                encoding="utf-8",
            )

            providers = pd.DataFrame(
                [
                    {
                        "provider_id": "provider:S4:building:0:soft_cls",
                        "scenario_id": "S4",
                        "provider_type": "soft_cls_building",
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "constraint_zone_id": "transformer:64",
                        "available_capacity_kw": 5.0,
                        "base_cost_per_kw_h": 3.0,
                        "selection_priority": 1,
                        "aggregator_id": "aggregator:S4:north",
                    },
                    {
                        "provider_id": "provider:S4:ev:S4:1:hard_cls",
                        "scenario_id": "S4",
                        "provider_type": "hard_cls_ev",
                        "building_id": "building:1",
                        "load_id": "load:1",
                        "constraint_zone_id": "transformer:64",
                        "available_capacity_kw": 4.0,
                        "base_cost_per_kw_h": 10.0,
                        "selection_priority": 2,
                        "aggregator_id": "aggregator:S4:south",
                    },
                ]
            )
            events = pd.DataFrame(
                [
                    {
                        "event_id": "S4:transformer:64:0",
                        "scenario_id": "S4",
                        "timestep": 0,
                        "timestamp": "2024-01-01 19:00:00",
                        "constraint_id": "transformer:64",
                        "required_kw": 8.0,
                        "selected_relief_kw": 8.0,
                        "selected_soft_kw": 5.0,
                        "selected_hard_kw": 3.0,
                        "shortfall_kw": 0.0,
                        "selected_provider_count": 2,
                        "estimated_cost": 11.25,
                        "overload_pctpt": 2.0,
                        "clearing_method": "surrogate",
                    }
                ]
            )
            selections = pd.DataFrame(
                [
                    {
                        "event_id": "S4:transformer:64:0",
                        "scenario_id": "S4",
                        "timestep": 0,
                        "timestamp": "2024-01-01 19:00:00",
                        "constraint_id": "transformer:64",
                        "provider_id": "provider:S4:building:0:soft_cls",
                        "provider_type": "soft_cls_building",
                        "selected_kw": 5.0,
                        "expected_relief_kw": 5.0,
                        "deliverability_factor": 1.0,
                        "rank_score": 3.0,
                        "effective_cost_per_relief_kw_h": 3.0,
                        "estimated_cost": 3.75,
                    },
                    {
                        "event_id": "S4:transformer:64:0",
                        "scenario_id": "S4",
                        "timestep": 0,
                        "timestamp": "2024-01-01 19:00:00",
                        "constraint_id": "transformer:64",
                        "provider_id": "provider:S4:ev:S4:1:hard_cls",
                        "provider_type": "hard_cls_ev",
                        "selected_kw": 3.0,
                        "expected_relief_kw": 3.0,
                        "deliverability_factor": 1.0,
                        "rank_score": 1.0,
                        "effective_cost_per_relief_kw_h": 10.0,
                        "estimated_cost": 7.5,
                    },
                ]
            )
            impact = pd.DataFrame(
                [
                    {
                        "provider_id": "provider:S4:building:0:soft_cls",
                        "scenario_id": "S4",
                        "constraint_id": "transformer:64",
                    }
                ]
            )
            providers.to_parquet(input_dir / "provider_registry.parquet", index=False)
            events.to_parquet(input_dir / "locational_clearing_events.parquet", index=False)
            selections.to_parquet(input_dir / "locational_clearing_selections.parquet", index=False)
            impact.to_parquet(input_dir / "network_impact_predictions.parquet", index=False)

            result = materialize_flexibility_operation_artifacts(
                root=root, project_id=PROJECT_ID, scenario_id="S4"
            )

            operations_dir = root / "projects" / PROJECT_ID / "outputs" / "operations"
            report_path = root / "projects" / PROJECT_ID / "outputs" / "reports" / "operational_kpi_report.json"
            catalog_path = operations_dir / "operations_catalog.json"
            operation_run_path = operations_dir / "operation_run.json"
            for name in [
                "network_constraints.parquet",
                "flexibility_offers.parquet",
                "dispatch_instructions.parquet",
                "settlement_records.parquet",
            ]:
                self.assertTrue((operations_dir / name).exists(), name)
            self.assertTrue(report_path.exists())
            self.assertTrue(catalog_path.exists())
            self.assertTrue(operation_run_path.exists())

            report = json.loads(report_path.read_text(encoding="utf-8"))
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            operation_run = json.loads(operation_run_path.read_text(encoding="utf-8"))
            self.assertEqual(result["report"], report_path)
            self.assertEqual(result["operations_catalog"], catalog_path)
            self.assertEqual(result["operation_run"], operation_run_path)
            self.assertEqual(report["report_id"], "operational_kpi_report")
            self.assertEqual(report["governance"]["model_version_id"], "model:sha256:test")
            self.assertEqual(report["governance"]["study_run_id"], "run:ev:test")
            self.assertAlmostEqual(report["summary"]["delivered_mwh"], 0.002)
            self.assertEqual(len(pd.read_parquet(operations_dir / "dispatch_instructions.parquet")), 2)
            self.assertEqual(operation_run["report_id"], "operation_run")
            self.assertEqual(operation_run["operation_id"], report["operation_context"]["operation_id"])
            self.assertEqual(operation_run["operation_type"], "flexibility_clearing")
            self.assertEqual(operation_run["scenario_id"], "S4")
            self.assertEqual(operation_run["status"], "completed")
            self.assertEqual(operation_run["governance"]["network_model_version_id"], "model:sha256:test")
            self.assertEqual(operation_run["governance"]["study_run_id"], "run:ev:test")
            self.assertEqual(catalog["report_id"], "operations_catalog")
            self.assertEqual(catalog["scenarios"]["S4"]["status"], "available")
            self.assertEqual(
                catalog["scenarios"]["S4"]["reports"]["operationRun"],
                "/projects/ev_hosting_flex/outputs/operations/operation_run.json",
            )
            self.assertEqual(
                catalog["scenarios"]["S4"]["reports"]["operationalKpis"],
                "/projects/ev_hosting_flex/outputs/reports/operational_kpi_report.json",
            )
            self.assertEqual(
                catalog["scenarios"]["S4"]["artifacts"]["dispatchInstructions"],
                "/projects/ev_hosting_flex/outputs/operations/dispatch_instructions.parquet",
            )
            self.assertEqual(catalog["scenarios"]["S4"]["summary"]["delivered_mwh"], 0.002)


if __name__ == "__main__":
    unittest.main()

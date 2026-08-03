import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.foundation.platform.reports import (
    ReportMetadata,
    build_report,
    file_reference,
    validate_report,
    write_manifest,
    write_report,
)
from gridalyn.interfaces.reporting.digital_twin import build_digital_twin_reports
from gridalyn.interfaces.reporting.schemas import report_input


class PlatformReportContractTest(unittest.TestCase):
    def test_file_reference_includes_path_size_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "inputs" / "sample.json"
            source.parent.mkdir()
            source.write_text('{"ok": true}\n', encoding="utf-8")

            item = file_reference(source, root=root)

        self.assertEqual(item["path"], "inputs/sample.json")
        self.assertEqual(item["bytes"], 13)
        self.assertEqual(len(item["sha256"]), 64)

    def test_write_report_adds_contract_fields_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "inputs" / "sample.json"
            source.parent.mkdir()
            source.write_text('{"ok": true}\n', encoding="utf-8")
            out = root / "outputs" / "reports" / "sample_report.json"

            payload = write_report(
                out,
                metadata=ReportMetadata(
                    report_id="sample_report",
                    source_domain="unit_test",
                    project={"name": "sample_project"},
                ),
                inputs=[file_reference(source, root=root)],
                artifacts=[],
                summary={"ok": True},
                validation={"valid": True, "errors": [], "warnings": []},
            )

            self.assertTrue(out.exists())
            self.assertEqual(payload["report_id"], "sample_report")
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["source_domain"], "unit_test")
            self.assertTrue(payload["created_at"].endswith("+00:00"))
            self.assertEqual(validate_report(payload), [])

    def test_write_report_can_include_governance_traceability(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "outputs" / "reports" / "traceable_report.json"

            payload = write_report(
                out,
                metadata=ReportMetadata(
                    report_id="traceable_report",
                    source_domain="unit_test",
                    model_version_id="model:sha256:abc",
                    study_run_id="run:sample:123",
                ),
            )

        self.assertEqual(payload["governance"]["model_version_id"], "model:sha256:abc")
        self.assertEqual(payload["governance"]["study_run_id"], "run:sample:123")
        self.assertEqual(validate_report(payload), [])

    def test_validate_report_requires_standard_contract_fields(self):
        errors = validate_report({"report_id": "broken"})

        self.assertIn("missing required field: schema_version", errors)
        self.assertIn("missing required field: validation", errors)

    def test_write_manifest_indexes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_a = build_report(
                metadata=ReportMetadata(report_id="a", source_domain="test"),
                summary={"value": 1},
            )
            report_b = build_report(
                metadata=ReportMetadata(report_id="b", source_domain="test"),
                summary={"value": 2},
            )
            path = root / "outputs" / "manifests" / "reports.json"

            manifest = write_manifest(
                path,
                reports=[report_a, report_b],
                root=root,
                report_paths={
                    "a": root / "outputs" / "reports" / "a.json",
                    "b": root / "outputs" / "reports" / "b.json",
                },
            )

            self.assertEqual(manifest["report_count"], 2)
            self.assertEqual(
                manifest["reports"]["a"],
                "outputs/reports/a.json",
            )
            self.assertTrue(path.exists())


class CanonicalReportsTest(unittest.TestCase):
    def test_report_input_includes_path_size_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            path.write_text('{"ok": true}\n')

            item = report_input(path, root=Path(tmp))

        self.assertEqual(item["path"], "sample.json")
        self.assertEqual(item["bytes"], 13)
        self.assertEqual(len(item["sha256"]), 64)

    def test_build_digital_twin_reports_standardizes_network_and_semantic_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            twin_dir = root / "instances" / "default" / "digital_twin"
            reports_dir = twin_dir / "reports"
            semantic_dir = twin_dir / "semantic"
            scenarios_dir = twin_dir / "scenarios"
            out_dir = twin_dir / "reports" / "canonical"
            reports_dir.mkdir(parents=True)
            semantic_dir.mkdir(parents=True)
            scenarios_dir.mkdir(parents=True)
            (reports_dir / "mv_lv_transformer_overload_report.json").write_text(
                """{
                  "overall": {"any_overloaded_mv_lv_transformer": true, "max_loading_percent": 113.4},
                  "scenarios": [{"scenario_id": "S4", "overloaded_transformers_count": 2}]
                }"""
            )
            (semantic_dir / "graph_manifest.json").write_text(
                '{"semantic_profile": "north_america", "node_count": 10, "edge_count": 20, "validation": {"valid": true}}'
            )
            (semantic_dir / "validation_report.json").write_text(
                '{"valid": true, "error_count": 0, "warning_count": 0}'
            )
            (scenarios_dir / "asset_registry_summary.json").write_text(
                '{"n_scenarios": 1, "scenarios": [{"scenario_id": "S4", "n_ev": 1294, "n_soft_participants": 970, "n_hard_preferred": 905}]}'
            )

            manifest = build_digital_twin_reports(root=root, out_dir=out_dir)

            self.assertTrue((out_dir / "network_capacity_report.json").exists())
            self.assertTrue((out_dir / "semantic_graph_report.json").exists())
            self.assertEqual(manifest["reports"]["semantic_graph"], "instances/default/digital_twin/reports/canonical/semantic_graph_report.json")


if __name__ == "__main__":
    unittest.main()

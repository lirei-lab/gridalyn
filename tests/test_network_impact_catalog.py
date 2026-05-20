import json
import tempfile
import unittest
from pathlib import Path

from gridalyn.simulation.analytics.network_impact.catalog import (
    build_network_impact_catalog,
    write_network_impact_catalog,
)


class NetworkImpactCatalogTest(unittest.TestCase):
    def test_build_catalog_groups_reports_by_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labels = root / "instances" / "default" / "digital_twin" / "flexibility" / "labels.json"
            verification = root / "projects" / "flexibility_cls" / "outputs" / "reports" / "verification.json"
            labels.parent.mkdir(parents=True)
            verification.parent.mkdir(parents=True)
            labels.write_text(json.dumps({"scenario_id": "S4", "summary": {"n_samples": 10}}))
            verification.write_text(json.dumps({"scenario_id": "S4", "dispatch": {}}))

            catalog = build_network_impact_catalog(
                {
                    "physicsLabels": labels,
                    "physicsVerification": verification,
                },
                expected_scenarios=["S0", "S4"],
                root=root,
            )

        self.assertEqual(catalog["report_id"], "network_impact_catalog")
        self.assertEqual(catalog["scenarios"]["S0"]["status"], "not_generated")
        self.assertEqual(catalog["scenarios"]["S4"]["status"], "available")
        self.assertEqual(
            catalog["scenarios"]["S4"]["reports"]["physicsLabels"],
            "/instances/default/digital_twin/flexibility/labels.json",
        )
        self.assertEqual(
            catalog["scenarios"]["S4"]["reports"]["physicsVerification"],
            "/projects/flexibility_cls/outputs/reports/verification.json",
        )

    def test_write_catalog_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "instances" / "default" / "digital_twin" / "flexibility" / "network_impact_catalog.json"

            written = write_network_impact_catalog(
                path,
                {
                    "report_id": "network_impact_catalog",
                    "scenarios": {},
                },
            )

            self.assertEqual(written, path)
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["report_id"], "network_impact_catalog")


if __name__ == "__main__":
    unittest.main()

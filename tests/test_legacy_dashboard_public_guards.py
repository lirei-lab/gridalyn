import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from examples.tutorials import create_grid_with_datagen_parallel
from gridalyn.projects.workflows.scripts import verify_dashboard_consistency


class DashboardCatalogContractTest(unittest.TestCase):
    def test_datagen_parallel_runs_without_dashboard_public_export(self):
        with (
            patch.object(create_grid_with_datagen_parallel, "datasets") as datasets,
            patch.object(create_grid_with_datagen_parallel.simulation, "build_synthetic_network_from_geojson") as build_network,
        ):
            datasets.get_dataset_path.return_value = "demo_buildings.geojson"
            build_network.return_value.validation_report = {"counts": {"buildings": 4, "pandapower_buses": 6}}

            create_grid_with_datagen_parallel.main(["--output-dir", "examples/generated/outputs/test"])

        build_network.assert_called_once()

    def test_dashboard_catalog_accepts_current_instance_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "instances" / "default" / "digital_twin"
            for relative in [
                "timeseries/base/nodes.parquet",
                "timeseries/base/lines.parquet",
                "timeseries/base/power.parquet",
                "timeseries/base/transformers.parquet",
            ]:
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")
            catalog = base / "dashboard" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                """{
  "report_id": "digital_twin_dashboard_catalog",
  "schema_version": "1.0",
  "scenarios": [
    {
      "scenario_id": "base",
      "paths": {
        "nodes": "/instances/default/digital_twin/timeseries/base/nodes.parquet",
        "lines": "/instances/default/digital_twin/timeseries/base/lines.parquet",
        "power": "/instances/default/digital_twin/timeseries/base/power.parquet",
        "transformers": "/instances/default/digital_twin/timeseries/base/transformers.parquet"
      }
    }
  ]
}
""",
                encoding="utf-8",
            )

            with patch.object(verify_dashboard_consistency, "ROOT", root):
                report = verify_dashboard_consistency.verify_dashboard_catalog(catalog)

        self.assertTrue(report["valid"], report)
        self.assertEqual(report["scenario_count"], 1)

    def test_dashboard_catalog_rejects_removed_dashboard_public_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "instances" / "default" / "digital_twin" / "dashboard" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                """{
  "report_id": "digital_twin_dashboard_catalog",
  "schema_version": "1.0",
  "scenarios": [
    {
      "scenario_id": "legacy",
      "paths": {
        "nodes": "/dashboard/public/data/nodes.parquet",
        "lines": "/dashboard/public/data/lines.parquet",
        "power": "/dashboard/public/data/power.parquet",
        "transformers": "/dashboard/public/data/transformers.parquet"
      }
    }
  ]
}
""",
                encoding="utf-8",
            )

            with patch.object(verify_dashboard_consistency, "ROOT", root):
                report = verify_dashboard_consistency.verify_dashboard_catalog(catalog)

        self.assertFalse(report["valid"], report)
        self.assertTrue(
            any("dashboard/public" in error for error in report["errors"]),
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()

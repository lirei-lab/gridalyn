import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.tutorials import create_grid_with_datagen_parallel
from gridalyn.projects.workflows.scripts import verify_dashboard_consistency


class DashboardCatalogContractTest(unittest.TestCase):
    def test_datagen_parallel_runs_without_dashboard_public_export(self):
        with (
            patch.object(create_grid_with_datagen_parallel, "datasets") as datasets,
            patch.object(
                create_grid_with_datagen_parallel.simulation,
                "build_synthetic_network_from_geojson",
            ) as build_network,
        ):
            datasets.get_dataset_path.return_value = "demo_buildings.geojson"
            build_network.return_value.validation_report = {
                "counts": {"buildings": 4, "pandapower_buses": 6}
            }

            create_grid_with_datagen_parallel.main(
                ["--output-dir", "examples/generated/outputs/test"]
            )

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

    def test_dashboard_catalog_accepts_an_additively_bumped_schema_version(self):
        """An additive bump must not read as a broken catalog.

        The verifier pinned `schema_version == "1.0"` by equality, so 1.1 --
        which only *adds* `network_model.geography` and changes nothing this
        function reads -- would have been reported invalid. Nothing caught it,
        because the on-disk catalog this verifier defaults to is gitignored and
        no test generated one.
        """
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
            served = "/instances/default/digital_twin/timeseries/base"
            catalog.write_text(
                json.dumps(
                    {
                        "report_id": "digital_twin_dashboard_catalog",
                        "schema_version": "1.1",
                        "network_model": {
                            "geography": {"crs": "EPSG:4326", "located": True}
                        },
                        "scenarios": [
                            {
                                "scenario_id": "base",
                                "paths": {
                                    kind: f"{served}/{kind}.parquet"
                                    for kind in (
                                        "nodes",
                                        "lines",
                                        "power",
                                        "transformers",
                                    )
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(verify_dashboard_consistency, "ROOT", root):
                report = verify_dashboard_consistency.verify_dashboard_catalog(catalog)

        self.assertTrue(report["valid"], report)

    def test_dashboard_catalog_rejects_an_unknown_schema_version(self):
        """The supported set is a gate, not a formality."""
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "report_id": "digital_twin_dashboard_catalog",
                        "schema_version": "9.9",
                        "scenarios": [{"scenario_id": "base", "paths": {}}],
                    }
                ),
                encoding="utf-8",
            )
            report = verify_dashboard_consistency.verify_dashboard_catalog(catalog)

        self.assertFalse(report["valid"])
        self.assertTrue(
            any("schema_version" in error for error in report["errors"]),
            report["errors"],
        )

    def test_dashboard_catalog_rejects_removed_dashboard_public_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = (
                root
                / "instances"
                / "default"
                / "digital_twin"
                / "dashboard"
                / "catalog.json"
            )
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

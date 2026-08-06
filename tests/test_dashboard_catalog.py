import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.projects.dashboard_catalog import (
    build_dashboard_catalog,
    write_dashboard_catalog,
)
from gridalyn.projects.workflows.scripts.generate_digital_twin_dashboard_catalog import (
    DEFAULT_EXTENSIONS,
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


if __name__ == "__main__":
    unittest.main()

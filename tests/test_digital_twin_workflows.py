import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from gridalyn.interfaces.cli import digital_twin
from gridalyn.workflows.digital_twin import ev_scenarios, ev_timeseries


class DigitalTwinWorkflowExtractionTest(unittest.TestCase):
    def test_scenarios_wrapper_imports_workflow_main(self):
        import examples.compat.generate_digital_twin_ev_scenarios as wrapper

        self.assertIs(wrapper.main, ev_scenarios.main)

    def test_timeseries_wrapper_imports_workflow_main(self):
        import examples.compat.generate_digital_twin_ev_timeseries as wrapper

        self.assertIs(wrapper.main, ev_timeseries.main)

    def test_digital_twin_cli_routes_scenarios_to_workflow(self):
        with patch.object(ev_scenarios, "main", return_value=0) as main:
            result = digital_twin.main(["scenarios", "--assignment-seed", "123"])

        self.assertEqual(result, 0)
        main.assert_called_once_with(["--assignment-seed", "123"])

    def test_digital_twin_cli_routes_timeseries_to_workflow(self):
        with patch.object(ev_timeseries, "main", return_value=0) as main:
            result = digital_twin.main(["timeseries", "--resolution-minutes", "15"])

        self.assertEqual(result, 0)
        main.assert_called_once_with(["--resolution-minutes", "15"])

    def test_workflow_relpath_accepts_external_paths(self):
        self.assertEqual(
            ev_scenarios._relpath(Path("/tmp/gridalyn-external/file.json")),
            "/tmp/gridalyn-external/file.json",
        )
        self.assertEqual(
            ev_timeseries._relpath(Path("/tmp/gridalyn-external/file.parquet")),
            "/tmp/gridalyn-external/file.parquet",
        )

    def test_scenarios_load_base_model_through_network_repository(self):
        class FakeReport:
            valid = True
            errors = ()

        class FakeModel:
            buildings = pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "pandapower_load": 0,
                    }
                ]
            )

        class FakeRepository:
            @classmethod
            def from_parquet(cls, base_dir):
                self = cls()
                self.base_dir = base_dir
                return self

            def load_model(self):
                return FakeModel()

            def validate_integrity(self):
                return FakeReport()

        with patch(
            "gridalyn.workflows.digital_twin.ev_scenarios.NetworkModelRepository",
            FakeRepository,
            create=True,
        ), patch.object(ev_scenarios, "_load_json", return_value={}):
            with patch.object(pd, "read_parquet", side_effect=AssertionError("raw parquet read")):
                with self.subTest("scenario generation uses repository instead of pd.read_parquet"):
                    import tempfile

                    with tempfile.TemporaryDirectory() as tmp:
                        ev_scenarios.generate_ev_scenarios(
                            base_dir=Path(tmp) / "base",
                            out_dir=Path(tmp) / "scenarios",
                            config_path=Path(tmp) / "config.json",
                            assignment_seed=123,
                            charger_kw=7.2,
                            c_soft_fraction=0.65,
                        )


if __name__ == "__main__":
    unittest.main()

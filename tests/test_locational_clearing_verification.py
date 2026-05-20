import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gridalyn.operations.market.locational_verification import (
    apply_locational_selections,
    build_locational_clearing_verification_report,
    write_locational_verification_outputs,
)


class LocationalClearingVerificationTest(unittest.TestCase):
    def test_apply_locational_selections_builds_dispatch_matrices_and_summary(self):
        building_kw = np.array([[10.0, 8.0, 6.0], [9.0, 7.0, 5.0]])
        ev_kw = np.array([[0.0, 0.0, 4.0], [0.0, 0.0, 3.0]])
        selections = pd.DataFrame(
            [
                {
                    "event_id": "S4:transformer:64:0",
                    "scenario_id": "S4",
                    "timestep": 0,
                    "constraint_id": "transformer:64",
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "provider_type": "soft_cls_building",
                    "selected_kw": 6.0,
                    "expected_relief_kw": 6.0,
                },
                {
                    "event_id": "S4:transformer:64:0",
                    "scenario_id": "S4",
                    "timestep": 0,
                    "constraint_id": "transformer:64",
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "provider_type": "hard_cls_ev",
                    "selected_kw": 2.0,
                    "expected_relief_kw": 2.0,
                },
                {
                    "event_id": "S4:transformer:64:1",
                    "scenario_id": "S4",
                    "timestep": 1,
                    "constraint_id": "transformer:64",
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "provider_type": "soft_cls_building",
                    "selected_kw": 10.0,
                    "expected_relief_kw": 10.0,
                },
            ]
        )
        providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "pandapower_load": 0,
                    "provider_type": "soft_cls_building",
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "pandapower_load": 1,
                    "provider_type": "soft_cls_building",
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "pandapower_load": 2,
                    "provider_type": "hard_cls_ev",
                },
            ]
        )

        result = apply_locational_selections(
            building_kw=building_kw,
            ev_kw=ev_kw,
            selections=selections,
            providers=providers,
            dt_h=0.25,
        )

        self.assertAlmostEqual(result["managed_building_kw"][0, 0], 4.0)
        self.assertAlmostEqual(result["managed_ev_kw"][0, 2], 2.0)
        self.assertAlmostEqual(result["managed_building_kw"][1, 1], 0.0)
        self.assertAlmostEqual(result["soft_delivered_kw"][0], 6.0)
        self.assertAlmostEqual(result["soft_delivered_kw"][1], 7.0)
        self.assertAlmostEqual(result["soft_shortfall_kw"][1], 3.0)
        self.assertAlmostEqual(result["hard_delivered_kw"][0], 2.0)
        self.assertAlmostEqual(result["summary"]["total_delivered_mwh"], 15.0 * 0.25 / 1000.0)
        self.assertAlmostEqual(result["summary"]["total_shortfall_mwh"], 3.0 * 0.25 / 1000.0)

    def test_build_report_compares_locational_clearing_to_unmanaged(self):
        report = build_locational_clearing_verification_report(
            scenario_id="S4",
            clearing_summary={
                "total_delivered_mwh": 0.02,
                "total_shortfall_mwh": 0.0,
                "soft_delivered_mwh": 0.02,
                "hard_delivered_mwh": 0.0,
            },
            case_metrics={
                "unmanaged": {
                    "trafo_max_loading_percent": 120.0,
                    "line_max_loading_percent": 105.0,
                    "v_min_pu": 0.91,
                    "n_trafo_overloads": 2,
                    "n_line_overloads": 1,
                    "ext_grid_peak_mw": 22.0,
                },
                "locational_clearing": {
                    "trafo_max_loading_percent": 110.0,
                    "line_max_loading_percent": 100.0,
                    "v_min_pu": 0.92,
                    "n_trafo_overloads": 1,
                    "n_line_overloads": 0,
                    "ext_grid_peak_mw": 21.5,
                },
            },
            constraint_ids=["transformer:64"],
        )

        self.assertEqual(report["report_id"], "locational_clearing_verification")
        self.assertEqual(report["validation"]["authority"], "pandapower_ac_powerflow")
        comparison = report["comparisons"]["locational_clearing_vs_unmanaged"]
        self.assertAlmostEqual(comparison["trafo_max_loading_reduction_pctpt"], 10.0)
        self.assertAlmostEqual(comparison["v_min_improvement_pu"], 0.01)
        self.assertEqual(comparison["line_overload_delta"], -1)

    def test_write_outputs_creates_dispatch_and_report_files(self):
        dispatch = pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "soft_delivered_kw": 6.0,
                    "hard_delivered_kw": 2.0,
                    "total_shortfall_kw": 0.0,
                }
            ]
        )
        report = build_locational_clearing_verification_report(
            scenario_id="S4",
            clearing_summary={"total_delivered_mwh": 0.002, "total_shortfall_mwh": 0.0},
            case_metrics={
                "unmanaged": {
                    "trafo_max_loading_percent": 100.0,
                    "line_max_loading_percent": 90.0,
                    "v_min_pu": 0.95,
                    "n_trafo_overloads": 0,
                    "n_line_overloads": 0,
                    "ext_grid_peak_mw": 20.0,
                },
                "locational_clearing": {
                    "trafo_max_loading_percent": 99.0,
                    "line_max_loading_percent": 89.0,
                    "v_min_pu": 0.96,
                    "n_trafo_overloads": 0,
                    "n_line_overloads": 0,
                    "ext_grid_peak_mw": 19.9,
                },
            },
            constraint_ids=["transformer:64"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_locational_verification_outputs(
                dispatch=dispatch,
                report=report,
                dispatch_path=Path(tmp) / "dispatch.parquet",
                report_path=Path(tmp) / "report.json",
            )

            self.assertTrue(outputs["dispatch"].exists())
            self.assertTrue(outputs["report"].exists())
            self.assertEqual(len(pd.read_parquet(outputs["dispatch"])), 1)


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from gridalyn.operations import build_shadow_report


class ProviderSelectionShadowReportTest(unittest.TestCase):
    def test_shadow_report_compares_aggregate_dispatch_with_local_selection(self):
        dispatch = pd.DataFrame(
            [
                {
                    "t_hours": 18.0,
                    "p_soft_cls_mw": 0.004,
                    "p_hard_cls_mw": 0.002,
                    "p_limit_trace_mw": 20.0,
                    "p_security_mw": 20.006,
                }
            ]
        )
        providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "available_capacity_kw": 5.0,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                },
                {
                    "provider_id": "provider:S4:ev:S4:0:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "available_capacity_kw": 7.2,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                },
            ]
        )
        sensitivity = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:0",
                    "sensitivity_kw_per_kw": 1.0,
                },
                {
                    "provider_id": "provider:S4:ev:S4:0:hard_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:0",
                    "sensitivity_kw_per_kw": 1.0,
                },
            ]
        )

        report = build_shadow_report(
            dispatch,
            providers,
            sensitivity,
            scenario_id="S4",
            constraint_ids=["transformer:0"],
        )

        self.assertEqual(report["scenario_id"], "S4")
        self.assertEqual(report["n_events"], 1)
        self.assertAlmostEqual(report["summary"]["aggregate_required_mwh"], 0.0005)
        self.assertAlmostEqual(report["summary"]["local_selected_mwh"], 0.0005)
        self.assertAlmostEqual(report["summary"]["local_shortfall_mwh"], 0.0)
        event = report["events"][0]
        self.assertEqual(event["constraint_id"], "transformer:0")
        self.assertAlmostEqual(event["required_kw"], 6.0)
        self.assertAlmostEqual(event["selected_soft_kw"], 5.0)
        self.assertAlmostEqual(event["selected_hard_kw"], 1.0)
        self.assertEqual(
            [row["provider_id"] for row in event["selected_providers"]],
            ["provider:S4:building:0:soft_cls", "provider:S4:ev:S4:0:hard_cls"],
        )


if __name__ == "__main__":
    unittest.main()

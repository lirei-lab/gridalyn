import unittest

import numpy as np
import pandas as pd

from gridalyn.simulation.analytics.network_impact.verification_report import (
    build_constraint_aware_dispatch,
    build_constraint_requirements,
    build_locational_dispatch,
    build_network_impact_verification_report,
    build_provider_ranking,
    summarize_dispatch,
)


class NetworkImpactVerificationReportTest(unittest.TestCase):
    def setUp(self):
        self.providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "pandapower_load": 0,
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "pandapower_load": 1,
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 10.0,
                    "base_cost_per_kw_h": 4.0,
                    "selection_priority": 1,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "pandapower_load": 2,
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 3.84,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                },
            ]
        )
        self.predictions = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 6.5,
                    "selection_score": 2.0,
                    "effective_cost_per_predicted_kw_h": 3.0,
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 10.0,
                    "selection_score": 1.0,
                    "effective_cost_per_predicted_kw_h": 4.0,
                    "available_capacity_kw": 10.0,
                    "base_cost_per_kw_h": 4.0,
                    "selection_priority": 1,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 3.84,
                    "selection_score": 0.2,
                    "effective_cost_per_predicted_kw_h": 10.0,
                    "available_capacity_kw": 3.84,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                },
            ]
        )

    def test_surrogate_ranking_preserves_provider_metadata(self):
        ranking = build_provider_ranking(
            self.providers,
            predictions=self.predictions,
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            method="surrogate",
        )

        self.assertEqual(ranking.iloc[0]["provider_id"], "provider:S4:building:0:soft_cls")
        self.assertIn("pandapower_load", ranking.columns)
        self.assertAlmostEqual(ranking.iloc[0]["rank_score"], 2.0)
        self.assertEqual(set(ranking["constraint_id"]), {"transformer:64"})

    def test_locational_dispatch_uses_ranking_and_reports_shortfall(self):
        ranking = build_provider_ranking(
            self.providers,
            predictions=self.predictions,
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            method="surrogate",
        )
        result = build_locational_dispatch(
            building_kw=np.array([[10.0, 10.0, 10.0]]),
            ev_kw=np.array([[4.0, 4.0, 4.0]]),
            soft_target_kw=np.array([8.0]),
            hard_target_kw=np.array([5.0]),
            provider_ranking=ranking,
        )

        self.assertAlmostEqual(result["soft_delivered_kw"][0], 8.0)
        self.assertAlmostEqual(result["hard_delivered_kw"][0], 3.84)
        self.assertAlmostEqual(result["soft_shortfall_kw"][0], 0.0)
        self.assertAlmostEqual(result["hard_shortfall_kw"][0], 1.16)
        self.assertAlmostEqual(result["managed_building_kw"][0, 0], 3.5)
        self.assertAlmostEqual(result["managed_building_kw"][0, 1], 8.5)
        self.assertAlmostEqual(result["managed_ev_kw"][0, 2], 0.16)

    def test_constraint_requirements_convert_transformer_overload_to_kw(self):
        requirements = build_constraint_requirements(
            transformer_timeseries=pd.DataFrame(
                [
                    {
                        "timestamp": "2024-01-01 00:00:00",
                        "trafo_idx": 64,
                        "loading_percent": 110.0,
                        "sn_mva": 0.21,
                    },
                    {
                        "timestamp": "2024-01-01 00:05:00",
                        "trafo_idx": 64,
                        "loading_percent": 98.0,
                        "sn_mva": 0.21,
                    },
                ]
            ),
            transformer_id_by_idx={64: "transformer:64"},
            constraint_ids=["transformer:64"],
            limit_percent=100.0,
        )

        self.assertEqual(len(requirements), 2)
        self.assertAlmostEqual(requirements.iloc[0]["required_kw"], 21.0)
        self.assertAlmostEqual(requirements.iloc[1]["required_kw"], 0.0)

    def test_constraint_aware_dispatch_clears_local_requirements_soft_first(self):
        ranking = build_provider_ranking(
            self.providers,
            predictions=self.predictions,
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            method="surrogate",
        )
        requirements = pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "timestamp": "2024-01-01 00:00:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 18.0,
                    "overload_pctpt": 8.0,
                }
            ]
        )

        result = build_constraint_aware_dispatch(
            building_kw=np.array([[10.0, 10.0, 10.0]]),
            ev_kw=np.array([[4.0, 4.0, 4.0]]),
            requirements=requirements,
            provider_ranking=ranking,
        )

        self.assertAlmostEqual(result["soft_delivered_kw"][0], 16.5)
        self.assertAlmostEqual(result["hard_delivered_kw"][0], 1.5)
        self.assertAlmostEqual(result["shortfall_kw"][0], 0.0)
        self.assertAlmostEqual(result["managed_building_kw"][0, 0], 3.5)
        self.assertAlmostEqual(result["managed_building_kw"][0, 1], 0.0)
        self.assertAlmostEqual(result["managed_ev_kw"][0, 2], 2.5)
        self.assertEqual(result["events"][0]["constraint_id"], "transformer:64")

    def test_report_compares_cases_against_unmanaged_baseline(self):
        dispatch_summary = summarize_dispatch(
            soft_delivered_kw=np.array([8.0, 4.0]),
            hard_delivered_kw=np.array([3.0, 2.0]),
            soft_shortfall_kw=np.array([0.0, 1.0]),
            hard_shortfall_kw=np.array([0.0, 0.0]),
            dt_h=0.25,
        )
        report = build_network_impact_verification_report(
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            case_metrics={
                "unmanaged": {
                    "trafo_max_loading_percent": 120.0,
                    "line_max_loading_percent": 105.0,
                    "v_min_pu": 0.91,
                    "n_trafo_overloads": 2,
                    "n_line_overloads": 1,
                    "ext_grid_peak_mw": 22.0,
                },
                "surrogate_locational": {
                    "trafo_max_loading_percent": 110.0,
                    "line_max_loading_percent": 101.0,
                    "v_min_pu": 0.93,
                    "n_trafo_overloads": 1,
                    "n_line_overloads": 1,
                    "ext_grid_peak_mw": 21.0,
                },
            },
            dispatch_summaries={"surrogate_locational": dispatch_summary},
        )

        self.assertEqual(report["report_id"], "network_impact_verification")
        self.assertEqual(report["validation"]["authority"], "pandapower_ac_powerflow")
        delta = report["comparisons"]["surrogate_locational_vs_unmanaged"]
        self.assertAlmostEqual(delta["trafo_max_loading_reduction_pctpt"], 10.0)
        self.assertAlmostEqual(delta["v_min_improvement_pu"], 0.02)
        self.assertAlmostEqual(
            report["dispatch"]["surrogate_locational"]["total_shortfall_mwh"],
            0.25 / 1000.0,
        )


if __name__ == "__main__":
    unittest.main()

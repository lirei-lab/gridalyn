import unittest

from gridalyn.market.scorecard import (
    build_flexibility_clearing_scorecard,
)


class FlexibilityClearingBenchmarkTest(unittest.TestCase):
    def test_build_scorecard_compares_delivery_and_network_impact(self):
        topology_report = {
            "report_id": "network_impact_verification",
            "scenario_id": "S4",
            "constraint_ids": ["transformer:64"],
            "cases": {
                "unmanaged": {
                    "ext_grid_peak_mw": 22.0,
                    "line_max_loading_percent": 110.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 4,
                    "trafo_max_loading_percent": 150.0,
                    "v_min_pu": 0.90,
                },
                "aggregate_cls": {
                    "ext_grid_peak_mw": 20.0,
                    "line_max_loading_percent": 102.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 2,
                    "trafo_max_loading_percent": 138.0,
                    "v_min_pu": 0.91,
                },
                "topology_locational": {
                    "ext_grid_peak_mw": 21.7,
                    "line_max_loading_percent": 108.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 1,
                    "trafo_max_loading_percent": 148.0,
                    "v_min_pu": 0.907,
                },
                "constraint_aware_clearing": {
                    "ext_grid_peak_mw": 21.4,
                    "line_max_loading_percent": 106.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 1,
                    "trafo_max_loading_percent": 144.0,
                    "v_min_pu": 0.909,
                },
            },
            "dispatch": {
                "aggregate_cls": {
                    "total_delivered_mwh": 6.0,
                    "total_shortfall_mwh": 0.0,
                    "soft_delivered_mwh": 2.0,
                    "hard_delivered_mwh": 4.0,
                    "shortfall_event_count": 0,
                },
                "topology_locational": {
                    "total_delivered_mwh": 1.0,
                    "total_shortfall_mwh": 5.0,
                    "soft_delivered_mwh": 0.4,
                    "hard_delivered_mwh": 0.6,
                    "shortfall_event_count": 3,
                },
                "constraint_aware_clearing": {
                    "total_delivered_mwh": 2.0,
                    "total_shortfall_mwh": 1.0,
                    "soft_delivered_mwh": 1.2,
                    "hard_delivered_mwh": 0.8,
                    "shortfall_event_count": 1,
                },
            },
            "comparisons": {
                "aggregate_cls_vs_unmanaged": {
                    "trafo_max_loading_reduction_pctpt": 12.0,
                    "line_max_loading_reduction_pctpt": 8.0,
                    "trafo_overload_delta": -2,
                    "line_overload_delta": 0,
                    "v_min_improvement_pu": 0.01,
                    "ext_grid_peak_reduction_mw": 2.0,
                },
                "topology_locational_vs_unmanaged": {
                    "trafo_max_loading_reduction_pctpt": 2.0,
                    "line_max_loading_reduction_pctpt": 2.0,
                    "trafo_overload_delta": -3,
                    "line_overload_delta": 0,
                    "v_min_improvement_pu": 0.007,
                    "ext_grid_peak_reduction_mw": 0.3,
                },
                "constraint_aware_clearing_vs_unmanaged": {
                    "trafo_max_loading_reduction_pctpt": 6.0,
                    "line_max_loading_reduction_pctpt": 4.0,
                    "trafo_overload_delta": -3,
                    "line_overload_delta": 0,
                    "v_min_improvement_pu": 0.009,
                    "ext_grid_peak_reduction_mw": 0.6,
                },
            },
        }
        physics_report = {
            "report_id": "network_impact_verification",
            "scenario_id": "S4",
            "cases": {
                "surrogate_locational": {
                    "ext_grid_peak_mw": 21.6,
                    "line_max_loading_percent": 107.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 1,
                    "trafo_max_loading_percent": 147.0,
                    "v_min_pu": 0.908,
                },
            },
            "dispatch": {
                "surrogate_locational": {
                    "total_delivered_mwh": 1.5,
                    "total_shortfall_mwh": 4.5,
                    "soft_delivered_mwh": 0.7,
                    "hard_delivered_mwh": 0.8,
                    "shortfall_event_count": 2,
                },
            },
            "comparisons": {
                "surrogate_locational_vs_unmanaged": {
                    "trafo_max_loading_reduction_pctpt": 3.0,
                    "line_max_loading_reduction_pctpt": 3.0,
                    "trafo_overload_delta": -3,
                    "line_overload_delta": 0,
                    "v_min_improvement_pu": 0.008,
                    "ext_grid_peak_reduction_mw": 0.4,
                },
            },
        }
        locational_report = {
            "report_id": "locational_clearing_verification",
            "scenario_id": "S4",
            "cases": {
                "locational_clearing": {
                    "ext_grid_peak_mw": 21.5,
                    "line_max_loading_percent": 105.0,
                    "n_line_overloads": 1,
                    "n_trafo_overloads": 1,
                    "trafo_max_loading_percent": 145.0,
                    "v_min_pu": 0.9095,
                },
            },
            "dispatch": {
                "locational_clearing": {
                    "total_delivered_mwh": 2.5,
                    "total_shortfall_mwh": 0.5,
                    "soft_delivered_mwh": 2.5,
                    "hard_delivered_mwh": 0.0,
                    "shortfall_event_count": 1,
                },
            },
            "comparisons": {
                "locational_clearing_vs_unmanaged": {
                    "trafo_max_loading_reduction_pctpt": 5.0,
                    "line_max_loading_reduction_pctpt": 5.0,
                    "trafo_overload_delta": -3,
                    "line_overload_delta": 0,
                    "v_min_improvement_pu": 0.0095,
                    "ext_grid_peak_reduction_mw": 0.5,
                },
            },
        }

        scorecard = build_flexibility_clearing_scorecard(
            topology_report=topology_report,
            physics_report=physics_report,
            locational_report=locational_report,
        )

        self.assertEqual(scorecard["report_id"], "flexibility_clearing_scorecard")
        self.assertEqual(scorecard["scenario_id"], "S4")
        policy_ids = [policy["policy_id"] for policy in scorecard["policies"]]
        self.assertEqual(
            policy_ids,
            [
                "unmanaged",
                "aggregate_cls",
                "constraint_aware_clearing",
                "locational_clearing_verified",
                "topology_locational",
                "physics_surrogate_locational",
            ],
        )
        aggregate = scorecard["policy_index"]["aggregate_cls"]
        constraint_aware = scorecard["policy_index"]["constraint_aware_clearing"]
        locational = scorecard["policy_index"]["locational_clearing_verified"]
        topology = scorecard["policy_index"]["topology_locational"]
        physics = scorecard["policy_index"]["physics_surrogate_locational"]

        self.assertEqual(aggregate["delivery_ratio"], 1.0)
        self.assertAlmostEqual(constraint_aware["delivery_ratio"], 2.0 / 3.0)
        self.assertAlmostEqual(locational["delivery_ratio"], 2.5 / 3.0)
        self.assertEqual(locational["source_report"], "locational_clearing_verification")
        self.assertAlmostEqual(topology["delivery_ratio"], 1.0 / 6.0)
        self.assertEqual(topology["overload_reduction_count"], 3)
        self.assertEqual(physics["comparison_vs_aggregate"]["shortfall_delta_mwh"], 4.5)
        self.assertEqual(scorecard["summary"]["best_delivery_policy_id"], "aggregate_cls")
        self.assertEqual(scorecard["summary"]["best_delivery_ratio_policy_id"], "aggregate_cls")
        self.assertEqual(scorecard["summary"]["best_overload_policy_id"], "topology_locational")


if __name__ == "__main__":
    unittest.main()

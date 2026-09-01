import unittest

import pandas as pd

from gridalyn.simulation.analytics.network_impact.physics_model import (
    build_physics_surrogate_report,
    fit_physics_surrogate,
    predict_physics_impact,
)


class NetworkImpactPhysicsModelTest(unittest.TestCase):
    def setUp(self):
        self.training = pd.DataFrame(
            [
                {
                    "provider_id": "p-soft-a",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "constraint_type": "cim:PowerTransformer",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                    "feature_provider_type_code": 1.0,
                    "feature_same_constraint_zone": 1.0,
                    "feature_available_capacity_kw": 6.5,
                    "feature_base_cost_per_kw_h": 3.0,
                    "feature_selection_priority": 1.0,
                    "feature_topology_sensitivity": 1.0,
                },
                {
                    "provider_id": "p-hard-b",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "constraint_type": "cim:PowerTransformer",
                    "available_capacity_kw": 3.84,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                    "feature_provider_type_code": 0.0,
                    "feature_same_constraint_zone": 1.0,
                    "feature_available_capacity_kw": 3.84,
                    "feature_base_cost_per_kw_h": 10.0,
                    "feature_selection_priority": 2.0,
                    "feature_topology_sensitivity": 1.0,
                },
                {
                    "provider_id": "p-remote",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:99",
                    "constraint_type": "cim:PowerTransformer",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                    "feature_provider_type_code": 1.0,
                    "feature_same_constraint_zone": 0.0,
                    "feature_available_capacity_kw": 6.5,
                    "feature_base_cost_per_kw_h": 3.0,
                    "feature_selection_priority": 1.0,
                    "feature_topology_sensitivity": 0.0,
                },
            ]
        )
        self.labels = pd.DataFrame(
            [
                {
                    "provider_id": "p-soft-a",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "actual_perturbation_kw": 5.0,
                    "relief_pct_per_kw": 0.50,
                    "delta_v_min_pu": 0.0010,
                    "delta_global_line_max_loading_pct": -0.8,
                    "delta_global_trafo_max_loading_pct": -2.5,
                },
                {
                    "provider_id": "p-soft-a",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "actual_perturbation_kw": 5.0,
                    "relief_pct_per_kw": 0.60,
                    "delta_v_min_pu": 0.0012,
                    "delta_global_line_max_loading_pct": -0.7,
                    "delta_global_trafo_max_loading_pct": -2.7,
                },
                {
                    "provider_id": "p-hard-b",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "actual_perturbation_kw": 3.0,
                    "relief_pct_per_kw": 0.20,
                    "delta_v_min_pu": 0.0002,
                    "delta_global_line_max_loading_pct": -0.1,
                    "delta_global_trafo_max_loading_pct": -0.6,
                },
            ]
        )

    def test_fit_physics_surrogate_summarizes_positive_labels_by_provider_constraint(
        self,
    ):
        model = fit_physics_surrogate(self.training, self.labels)

        self.assertEqual(model["model_family"], "tabular_physics_lookup_v1")
        self.assertEqual(model["n_label_rows"], 3)
        self.assertEqual(model["n_supervised_pairs"], 2)
        pair = (
            model["pair_labels"]
            .loc[model["pair_labels"]["provider_id"] == "p-soft-a"]
            .iloc[0]
        )
        self.assertAlmostEqual(pair["target_relief_pct_per_kw"], 0.55)
        self.assertAlmostEqual(pair["target_delta_v_min_pu"], 0.0011)

    def test_predict_physics_impact_outputs_selector_compatible_predictions(self):
        model = fit_physics_surrogate(self.training, self.labels)
        predictions = predict_physics_impact(self.training, model)

        self.assertIn("predicted_deliverability_factor", predictions.columns)
        self.assertIn("selection_score", predictions.columns)
        soft = predictions.loc[predictions["provider_id"] == "p-soft-a"].iloc[0]
        hard = predictions.loc[predictions["provider_id"] == "p-hard-b"].iloc[0]
        remote = predictions.loc[predictions["provider_id"] == "p-remote"].iloc[0]

        self.assertGreater(soft["selection_score"], hard["selection_score"])
        self.assertGreater(soft["predicted_relief_kw"], hard["predicted_relief_kw"])
        self.assertEqual(remote["predicted_deliverability_factor"], 0.0)
        self.assertEqual(remote["predicted_relief_kw"], 0.0)

    def test_report_describes_training_coverage_and_fallback(self):
        model = fit_physics_surrogate(self.training, self.labels)
        predictions = predict_physics_impact(self.training, model)
        report = build_physics_surrogate_report(
            model,
            predictions,
            scenario_id="S4",
        )

        self.assertEqual(report["report_id"], "network_impact_physics_surrogate")
        self.assertEqual(report["model"]["model_family"], "tabular_physics_lookup_v1")
        self.assertEqual(
            report["model"]["fallback_policy"],
            "provider_type_constraint_mean_then_topology_zero",
        )
        self.assertEqual(report["summary"]["n_prediction_rows"], 3)
        self.assertEqual(report["summary"]["n_positive_predictions"], 2)


if __name__ == "__main__":
    unittest.main()

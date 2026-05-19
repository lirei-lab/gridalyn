import unittest

import numpy as np
import pandas as pd

from gridalyn.analytics.network_impact.perturbation_sampler import (
    build_physics_labels,
    build_perturbation_matrices,
    select_perturbation_samples,
)


class NetworkImpactPerturbationSamplerTest(unittest.TestCase):
    def setUp(self):
        self.predictions = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "available_capacity_kw": 6.5,
                    "predicted_deliverability_factor": 1.0,
                    "selection_score": 3.0,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "available_capacity_kw": 3.84,
                    "predicted_deliverability_factor": 1.0,
                    "selection_score": 1.0,
                },
                {
                    "provider_id": "provider:S4:building:3:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:99",
                    "available_capacity_kw": 6.5,
                    "predicted_deliverability_factor": 1.0,
                    "selection_score": 2.0,
                },
            ]
        )
        self.providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "pandapower_load": 1,
                    "available_capacity_kw": 6.5,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "pandapower_load": 2,
                    "available_capacity_kw": 3.84,
                },
                {
                    "provider_id": "provider:S4:building:3:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "pandapower_load": 3,
                    "available_capacity_kw": 6.5,
                },
            ]
        )
        self.dispatch = pd.DataFrame(
            {
                "t_hours": [0.0, 0.083333, 0.166667],
                "p_soft_cls_mw": [0.0, 0.01, 0.02],
                "p_hard_cls_mw": [0.0, 0.0, 0.01],
            }
        )

    def test_select_perturbation_samples_uses_active_timesteps_and_top_ranked_providers(self):
        samples = select_perturbation_samples(
            self.providers,
            self.predictions,
            self.dispatch,
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            perturbation_kw=5.0,
            max_providers_per_constraint=2,
            max_timesteps=2,
        )

        self.assertEqual(len(samples), 4)
        self.assertEqual(set(samples["timestep"]), {1, 2})
        self.assertEqual(samples.iloc[0]["provider_id"], "provider:S4:building:1:soft_cls")
        self.assertIn("pandapower_load", samples.columns)
        self.assertTrue((samples["requested_perturbation_kw"] == 5.0).all())

    def test_select_perturbation_samples_accepts_multiple_perturbation_sizes(self):
        samples = select_perturbation_samples(
            self.providers,
            self.predictions,
            self.dispatch,
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            perturbation_kw=[2.0, 5.0],
            max_providers_per_constraint=1,
            max_timesteps=2,
        )

        self.assertEqual(len(samples), 4)
        self.assertEqual(set(samples["requested_perturbation_kw"]), {2.0, 5.0})
        self.assertEqual(samples["sample_id"].nunique(), 4)

    def test_build_perturbation_matrices_reduces_correct_load_type_and_q(self):
        samples = pd.DataFrame(
            [
                {
                    "sample_id": "s0",
                    "timestep": 0,
                    "provider_id": "p-soft",
                    "provider_type": "soft_cls_building",
                    "pandapower_load": 1,
                    "requested_perturbation_kw": 5.0,
                    "available_capacity_kw": 6.5,
                },
                {
                    "sample_id": "s1",
                    "timestep": 1,
                    "provider_id": "p-hard",
                    "provider_type": "hard_cls_ev",
                    "pandapower_load": 2,
                    "requested_perturbation_kw": 4.0,
                    "available_capacity_kw": 3.84,
                },
            ]
        )
        matrices = build_perturbation_matrices(
            building_kw=np.array([[10.0, 20.0, 30.0], [10.0, 20.0, 30.0]]),
            ev_kw=np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 5.0]]),
            samples=samples,
        )

        self.assertEqual(matrices["p_total_mw"].shape, (2, 3))
        self.assertAlmostEqual(matrices["actual_perturbation_kw"][0], 5.0)
        self.assertAlmostEqual(matrices["actual_perturbation_kw"][1], 3.84)
        self.assertAlmostEqual(matrices["p_total_mw"][0, 1], (20.0 + 2.0 - 5.0) / 1000.0)
        self.assertAlmostEqual(matrices["q_total_mvar"][0, 1], (20.0 - 5.0) / 1000.0 * 0.1)
        self.assertAlmostEqual(matrices["p_total_mw"][1, 2], (30.0 + 5.0 - 3.84) / 1000.0)
        self.assertAlmostEqual(matrices["q_total_mvar"][1, 2], 30.0 / 1000.0 * 0.1)

    def test_build_physics_labels_computes_constraint_and_global_deltas(self):
        samples = pd.DataFrame(
            [
                {
                    "sample_id": "s0",
                    "scenario_id": "S4",
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "timestep": 4,
                    "requested_perturbation_kw": 5.0,
                    "actual_perturbation_kw": 5.0,
                }
            ]
        )
        baseline = {
            "spatial_trafo": np.array([[120.0, 80.0]]),
            "spatial_line": np.array([[90.0, 70.0]]),
            "spatial_v": np.array([[0.92, 0.96]]),
            "ext_p_mw": np.array([20.0]),
        }
        perturbed = {
            "spatial_trafo": np.array([[118.0, 79.5]]),
            "spatial_line": np.array([[89.0, 70.0]]),
            "spatial_v": np.array([[0.921, 0.961]]),
            "ext_p_mw": np.array([19.995]),
        }
        labels = build_physics_labels(
            samples,
            baseline_results=baseline,
            perturbed_results=perturbed,
            baseline_row_by_timestep={4: 0},
            transformer_lookup={"transformer:64": 0},
        )

        self.assertEqual(len(labels), 1)
        row = labels.iloc[0]
        self.assertAlmostEqual(row["delta_constraint_trafo_loading_pct"], -2.0)
        self.assertAlmostEqual(row["delta_global_line_max_loading_pct"], -1.0)
        self.assertAlmostEqual(row["delta_v_min_pu"], 0.001)
        self.assertAlmostEqual(row["relief_pct_per_kw"], 0.4)


if __name__ == "__main__":
    unittest.main()

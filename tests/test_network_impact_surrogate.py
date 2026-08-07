import json
import unittest

import pandas as pd

from gridalyn.simulation.analytics.network_impact.surrogate import (
    build_edge_features,
    build_graph_snapshot,
    build_node_features,
    build_provider_impact_predictions,
    build_surrogate_report,
    build_training_dataset,
)


class NetworkImpactSurrogateTest(unittest.TestCase):
    def setUp(self):
        self.providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "ev_id": None,
                    "pandapower_load": 1,
                    "load_bus_id": "bus:10",
                    "feeder_bus_id": "bus:100",
                    "constraint_zone_id": "transformer:64",
                    "constraint_zone_type": "cim:PowerTransformer",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                    "source_standard": "EFOnt_CLS_CIM",
                    "source_table": "asset_registry+building_grid_connectivity",
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "building_id": "building:2",
                    "load_id": "load:2",
                    "ev_id": "ev:S4:2",
                    "pandapower_load": 2,
                    "load_bus_id": "bus:20",
                    "feeder_bus_id": "bus:200",
                    "constraint_zone_id": "transformer:99",
                    "constraint_zone_type": "cim:PowerTransformer",
                    "available_capacity_kw": 3.84,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                    "source_standard": "EFOnt_CLS_CIM",
                    "source_table": "asset_registry+building_grid_connectivity",
                },
            ]
        )
        self.sensitivity = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:64",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 1.0,
                    "deliverability_factor": 1.0,
                    "method": "downstream_transformer_topology",
                    "available_relief_kw": 6.5,
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:99",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 0.0,
                    "deliverability_factor": 0.0,
                    "method": "downstream_transformer_topology",
                    "available_relief_kw": 0.0,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:64",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 0.0,
                    "deliverability_factor": 0.0,
                    "method": "downstream_transformer_topology",
                    "available_relief_kw": 0.0,
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:99",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 1.0,
                    "deliverability_factor": 1.0,
                    "method": "downstream_transformer_topology",
                    "available_relief_kw": 3.84,
                },
            ]
        )

    def test_build_graph_snapshot_exports_gnn_ready_nodes_and_edges(self):
        nodes, edges = build_graph_snapshot(
            self.providers, self.sensitivity, scenario_id="S4"
        )

        node_types = set(nodes["node_type"])
        self.assertIn("provider", node_types)
        self.assertIn("building", node_types)
        self.assertIn("bus", node_types)
        self.assertIn("constraint", node_types)
        self.assertIn("scenario", node_types)

        edge_types = set(edges["edge_type"])
        self.assertIn("offers_flexibility", edge_types)
        self.assertIn("connected_to", edge_types)
        self.assertIn("constrains", edge_types)
        self.assertIn("scenario_includes", edge_types)

        self.assertTrue(nodes["node_id"].is_unique)
        self.assertTrue(edges["edge_id"].is_unique)
        self.assertTrue(set(edges["source_id"]).issubset(set(nodes["node_id"])))
        self.assertTrue(set(edges["target_id"]).issubset(set(nodes["node_id"])))

        provider_node = nodes.loc[
            nodes["node_id"] == "provider:S4:building:1:soft_cls"
        ].iloc[0]
        features = json.loads(provider_node["features_json"])
        self.assertEqual(features["available_capacity_kw"], 6.5)
        self.assertEqual(provider_node["semantic_type"], "cls:FlexibilityProvider")

    def test_feature_tables_have_stable_indices_for_future_gnn_tensors(self):
        nodes, edges = build_graph_snapshot(
            self.providers, self.sensitivity, scenario_id="S4"
        )

        node_features = build_node_features(nodes)
        edge_features = build_edge_features(edges)

        self.assertEqual(
            node_features["node_index"].tolist(), list(range(len(node_features)))
        )
        self.assertEqual(
            edge_features["edge_index"].tolist(), list(range(len(edge_features)))
        )
        self.assertIn("feature_available_capacity_kw", node_features.columns)
        self.assertIn("source_index", edge_features.columns)
        self.assertIn("target_index", edge_features.columns)
        self.assertFalse(
            edge_features[["source_index", "target_index"]].isna().any().any()
        )

    def test_training_and_predictions_rank_local_soft_provider_first(self):
        training = build_training_dataset(
            self.providers, self.sensitivity, scenario_id="S4"
        )
        predictions = build_provider_impact_predictions(training)

        self.assertEqual(len(training), 4)
        self.assertIn("target_delta_loading_pct_per_kw", training.columns)
        self.assertIn("predicted_relief_kw", predictions.columns)

        local = (
            predictions.loc[
                predictions["provider_id"] == "provider:S4:building:1:soft_cls"
            ]
            .sort_values("constraint_id")
            .reset_index(drop=True)
        )
        self.assertEqual(local.loc[0, "constraint_id"], "transformer:64")
        self.assertAlmostEqual(local.loc[0, "predicted_relief_kw"], 6.5)
        self.assertGreater(
            local.loc[0, "selection_score"],
            local.loc[1, "selection_score"],
        )

        ranked = predictions.loc[
            (predictions["constraint_id"] == "transformer:64")
            & (predictions["predicted_relief_kw"] > 0.0)
        ].sort_values("selection_rank")
        self.assertEqual(ranked.iloc[0]["provider_type"], "soft_cls_building")

    def test_report_summarizes_model_scope_and_validation_role(self):
        nodes, edges = build_graph_snapshot(
            self.providers, self.sensitivity, scenario_id="S4"
        )
        training = build_training_dataset(
            self.providers, self.sensitivity, scenario_id="S4"
        )
        predictions = build_provider_impact_predictions(training)
        report = build_surrogate_report(
            nodes, edges, training, predictions, scenario_id="S4"
        )

        self.assertEqual(report["report_id"], "network_impact_surrogate")
        self.assertEqual(report["scenario_id"], "S4")
        self.assertEqual(report["model"]["model_family"], "tabular_deterministic_v1")
        self.assertEqual(report["model"]["future_backend"], "heterogeneous_gnn")
        self.assertEqual(report["validation"]["authority"], "pandapower_ac_powerflow")
        self.assertEqual(report["summary"]["n_training_rows"], 4)
        self.assertGreater(report["summary"]["positive_prediction_count"], 0)


if __name__ == "__main__":
    unittest.main()

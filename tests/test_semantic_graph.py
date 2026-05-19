import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.db.federated_graph_adapter import FederatedGraphAdapter
from gridalyn.semantic.mappings import build_semantic_graph, north_america_profile
from gridalyn.semantic.validation import validate_semantic_graph


class SemanticGraphTest(unittest.TestCase):
    def _fixtures(self):
        buses = pd.DataFrame(
            [
                {
                    "bus_id": "bus:0",
                    "pandapower_bus": 0,
                    "name": "lv_bus_0",
                    "voltage_kv": 0.4,
                    "category": "LV",
                    "lat": 46.0,
                    "lon": -72.0,
                    "in_service": True,
                },
                {
                    "bus_id": "bus:1",
                    "pandapower_bus": 1,
                    "name": "mv_bus_0",
                    "voltage_kv": 25.0,
                    "category": "MV",
                    "lat": 46.1,
                    "lon": -72.1,
                    "in_service": True,
                },
            ]
        )
        lines = pd.DataFrame(
            [
                {
                    "line_id": "line:0",
                    "pandapower_line": 0,
                    "name": "line_0",
                    "from_bus_id": "bus:0",
                    "to_bus_id": "bus:1",
                    "length_km": 0.1,
                    "max_i_ka": 0.35,
                    "category": "LV",
                    "in_service": True,
                }
            ]
        )
        transformers = pd.DataFrame(
            [
                {
                    "transformer_id": "transformer:0",
                    "pandapower_trafo": 0,
                    "name": "trafo_0",
                    "hv_bus_id": "bus:1",
                    "lv_bus_id": "bus:0",
                    "sn_mva": 0.21,
                    "vn_hv_kv": 25.0,
                    "vn_lv_kv": 0.4,
                    "in_service": True,
                }
            ]
        )
        buildings = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "pandapower_load": 0,
                    "lv_bus_id": "bus:0",
                    "lat": 46.0,
                    "lon": -72.0,
                    "area_m2": 120.0,
                    "static_p_mw": 0.01,
                    "static_q_mvar": 0.001,
                }
            ]
        )
        connectivity = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:0",
                    "lv_transformer_id": "transformer:0",
                }
            ]
        )
        assets = pd.DataFrame(
            [
                {
                    "scenario_id": "S4",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "has_ev": True,
                    "ev_id": "ev:S4:0",
                    "charger_kw": 3.84,
                    "soft_cls_participant": True,
                    "hard_cls_enabled": True,
                    "contract_type": "soft+hard_ev",
                    "max_soft_kw": 6.5,
                    "max_hard_kw": 3.84,
                }
            ]
        )
        providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "ev_id": None,
                    "pandapower_load": 0,
                    "load_bus_id": "bus:0",
                    "feeder_bus_id": "bus:1",
                    "constraint_zone_id": "transformer:0",
                    "constraint_zone_type": "cim:PowerTransformer",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                    "source_standard": "EFOnt_CLS_CIM",
                    "source_table": "asset_registry+building_grid_connectivity",
                    "scenario_device_ids": "scenario_device:S4:device:building:0:hvac_cooling;scenario_device:S4:device:building:0:hvac_heating",
                    "device_ids": "device:building:0:hvac_cooling;device:building:0:hvac_heating",
                    "building_model_id": "building_model:building:0",
                    "device_types": "hvac_cooling;hvac_heating",
                    "scenario_device_count": 2,
                },
                {
                    "provider_id": "provider:S4:ev:S4:0:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "ev_id": "ev:S4:0",
                    "pandapower_load": 0,
                    "load_bus_id": "bus:0",
                    "feeder_bus_id": "bus:1",
                    "constraint_zone_id": "transformer:0",
                    "constraint_zone_type": "cim:PowerTransformer",
                    "available_capacity_kw": 3.84,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                    "source_standard": "EFOnt_CLS_CIM",
                    "source_table": "asset_registry+building_grid_connectivity",
                    "scenario_device_ids": "scenario_device:S4:device:building:0:evse_l2",
                    "device_ids": "device:building:0:evse_l2",
                    "building_model_id": "building_model:building:0",
                    "device_types": "evse_l2",
                    "scenario_device_count": 1,
                },
            ]
        )
        timeseries = {
            "powerflow_summary": {
                "scenarios": [
                    {
                        "scenario_id": "S4",
                        "paths": {"nodes": "instances/default/digital_twin/timeseries/S4_powerflow_nodes.parquet"},
                    }
                ]
            },
            "ev_load_summary": {
                "scenarios": [
                    {
                        "scenario_id": "S4",
                        "path": "instances/default/digital_twin/timeseries/S4_ev_load.parquet",
                    }
                ]
            },
        }
        return {
            "buses": buses,
            "lines": lines,
            "transformers": transformers,
            "buildings": buildings,
            "connectivity": connectivity,
            "assets": assets,
            "providers": providers,
            "timeseries": timeseries,
        }

    def test_build_semantic_graph_maps_north_america_classes_and_relationships(self):
        data = self._fixtures()

        nodes, edges, manifest = build_semantic_graph(
            buses=data["buses"],
            lines=data["lines"],
            transformers=data["transformers"],
            buildings=data["buildings"],
            connectivity=data["connectivity"],
            asset_registry=data["assets"],
            provider_registry=data["providers"],
            timeseries_manifests=data["timeseries"],
        )

        self.assertEqual(manifest["semantic_profile"], "north_america")
        self.assertIn("node_count", manifest)
        self.assertIn("edge_count", manifest)
        node_types = dict(zip(nodes["node_id"], nodes["semantic_type"], strict=True))
        self.assertEqual(node_types["bus:0"], "cim:ConnectivityNode")
        self.assertEqual(node_types["line:0"], "cim:ACLineSegment")
        self.assertEqual(node_types["transformer:0"], "cim:PowerTransformer")
        self.assertEqual(node_types["building:0"], "brick:Building")
        self.assertEqual(node_types["load:0"], "cim:EnergyConsumer")
        self.assertEqual(node_types["ev:S4:0"], "ieee2030_5:EVSE")
        self.assertEqual(node_types["contract:S4:building:0:soft_cls"], "cls:SoftCLSContract")
        self.assertEqual(node_types["contract:S4:ev:S4:0:hard_cls"], "cls:HardCLSContract")
        self.assertEqual(node_types["aggregator:S4:soft_cls"], "cls:FlexibilityAggregator")
        self.assertEqual(node_types["portfolio:S4:soft_cls"], "cls:FlexibilityPortfolio")
        self.assertEqual(node_types["provider:S4:building:0:soft_cls"], "cls:FlexibilityProvider")
        self.assertEqual(
            node_types["scenario_device:S4:device:building:0:hvac_heating"],
            "dt:ScenarioDevice",
        )
        self.assertEqual(node_types["offer:S4:building:0:soft_cls"], "cls:FlexibilityOffer")
        self.assertEqual(node_types["constraint-zone:S4:transformer:0"], "cls:ConstraintZone")
        self.assertEqual(
            node_types["efont:flexibility:S4:building:0:soft_cls"],
            "efont:EnergyFlexibility",
        )
        self.assertEqual(
            node_types["efont:resource:S4:building:0:thermal"],
            "efont:ThermallyActivatedBuildingSystem",
        )
        self.assertEqual(
            node_types["efont:operation:S4:building:0:soft_cls"],
            "efont:FlexibleOperation",
        )
        self.assertEqual(
            node_types["efont:kpi:S4:building:0:maximum_reduced_demand"],
            "efont:EnergyFlexibilityKPI",
        )
        self.assertIn("efont", manifest["namespaces"])
        self.assertIn("s223", manifest["namespaces"])
        self.assertNotIn("saref", nodes["semantic_type"].str.cat(sep=" "))

        rels = set(
            zip(edges["source_id"], edges["relationship_type"], edges["target_id"], strict=True)
        )
        self.assertIn(("building:0", "HAS_LOAD", "load:0"), rels)
        self.assertIn(("load:0", "CONNECTED_TO", "bus:0"), rels)
        self.assertIn(("line:0", "CONNECTS", "bus:0"), rels)
        self.assertIn(("transformer:0", "FEEDS", "bus:0"), rels)
        self.assertIn(("building:0", "HAS_EVSE", "ev:S4:0"), rels)
        self.assertIn(("building:0", "PARTICIPATES_IN", "contract:S4:building:0:soft_cls"), rels)
        self.assertIn(("ev:S4:0", "ENABLES", "contract:S4:ev:S4:0:hard_cls"), rels)
        self.assertIn(("aggregator:S4:soft_cls", "MANAGES_PORTFOLIO", "portfolio:S4:soft_cls"), rels)
        self.assertIn(("aggregator:S4:soft_cls", "AGGREGATES", "provider:S4:building:0:soft_cls"), rels)
        self.assertIn(("portfolio:S4:soft_cls", "INCLUDES_PROVIDER", "provider:S4:building:0:soft_cls"), rels)
        self.assertIn(("provider:S4:building:0:soft_cls", "OFFERS", "offer:S4:building:0:soft_cls"), rels)
        self.assertIn(("provider:S4:building:0:soft_cls", "IMPLEMENTS_CONTRACT", "contract:S4:building:0:soft_cls"), rels)
        self.assertIn(
            (
                "provider:S4:building:0:soft_cls",
                "HAS_FLEXIBILITY_RESOURCE",
                "scenario_device:S4:device:building:0:hvac_heating",
            ),
            rels,
        )
        self.assertIn(("provider:S4:building:0:soft_cls", "LOCATED_IN_CONSTRAINT_ZONE", "constraint-zone:S4:transformer:0"), rels)
        self.assertIn(("offer:S4:building:0:soft_cls", "TARGETS_CONSTRAINT", "constraint-zone:S4:transformer:0"), rels)
        self.assertIn(("constraint-zone:S4:transformer:0", "CONSTRAINT_ZONE_FOR", "transformer:0"), rels)
        self.assertIn(
            ("building:0", "HAS_FLEXIBILITY_RESOURCE", "efont:resource:S4:building:0:thermal"),
            rels,
        )
        self.assertIn(
            (
                "efont:resource:S4:building:0:thermal",
                "ALLOWS",
                "efont:operation:S4:building:0:soft_cls",
            ),
            rels,
        )
        self.assertIn(
            (
                "efont:operation:S4:building:0:soft_cls",
                "ENABLES",
                "efont:flexibility:S4:building:0:soft_cls",
            ),
            rels,
        )
        self.assertIn(
            (
                "efont:kpi:S4:building:0:maximum_reduced_demand",
                "QUANTIFIES",
                "efont:flexibility:S4:building:0:soft_cls",
            ),
            rels,
        )
        self.assertIn(
            (
                "contract:S4:building:0:soft_cls",
                "DESCRIBES_FLEXIBILITY",
                "efont:flexibility:S4:building:0:soft_cls",
            ),
            rels,
        )

    def test_north_america_profile_includes_efont_as_building_flexibility_crosswalk(self):
        profile = north_america_profile()

        self.assertIn("efont", profile["namespaces"])
        self.assertIn("EFOnt", profile["primary_standards"]["building_flexibility"])
        self.assertIn("efont:EnergyFlexibility", profile["allowed_semantic_types"])
        self.assertIn("efont:FlexibleOperation", profile["allowed_semantic_types"])
        self.assertIn("efont:ThermallyActivatedBuildingSystem", profile["allowed_semantic_types"])
        self.assertIn("efont:EnergyFlexibilityKPI", profile["allowed_semantic_types"])
        self.assertIn("cls:FlexibilityAggregator", profile["allowed_semantic_types"])
        self.assertIn("cls:FlexibilityPortfolio", profile["allowed_semantic_types"])
        self.assertIn("cls:FlexibilityProvider", profile["allowed_semantic_types"])
        self.assertIn("cls:FlexibilityOffer", profile["allowed_semantic_types"])
        self.assertIn("cls:ConstraintZone", profile["allowed_semantic_types"])
        self.assertIn("dt:ScenarioDevice", profile["allowed_semantic_types"])
        self.assertIn("HAS_FLEXIBILITY_RESOURCE", profile["relationship_types"])
        self.assertIn("QUANTIFIES", profile["relationship_types"])
        self.assertIn("AGGREGATES", profile["relationship_types"])
        self.assertIn("IMPLEMENTS_CONTRACT", profile["relationship_types"])
        self.assertIn("LOCATED_IN_CONSTRAINT_ZONE", profile["relationship_types"])
        self.assertIn("MANAGES_PORTFOLIO", profile["relationship_types"])
        self.assertIn("OFFERS", profile["relationship_types"])
        self.assertIn("TARGETS_CONSTRAINT", profile["relationship_types"])

    def test_validate_semantic_graph_reports_integrity_and_scenario_counts(self):
        data = self._fixtures()
        nodes, edges, _manifest = build_semantic_graph(
            buses=data["buses"],
            lines=data["lines"],
            transformers=data["transformers"],
            buildings=data["buildings"],
            connectivity=data["connectivity"],
            asset_registry=data["assets"],
            provider_registry=data["providers"],
            timeseries_manifests=data["timeseries"],
        )

        report = validate_semantic_graph(
            nodes,
            edges,
            north_america_profile(),
            expected_scenario_counts={
                "S4": {
                    "n_ev": 1,
                    "n_soft_participants": 1,
                    "n_hard_preferred": 0,
                }
            },
        )

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["node_count"], len(nodes))
        self.assertEqual(report["edge_count"], len(edges))

        broken_edges = edges.copy()
        broken_edges.loc[0, "target_id"] = "missing:node"
        broken_report = validate_semantic_graph(
            nodes,
            broken_edges,
            north_america_profile(),
        )
        self.assertFalse(broken_report["valid"])
        self.assertTrue(any("missing endpoint" in error for error in broken_report["errors"]))

    def test_federated_graph_adapter_reads_parquet_and_prepares_cypher_batches(self):
        data = self._fixtures()
        nodes, edges, _manifest = build_semantic_graph(
            buses=data["buses"],
            lines=data["lines"],
            transformers=data["transformers"],
            buildings=data["buildings"],
            connectivity=data["connectivity"],
            asset_registry=data["assets"],
            provider_registry=data["providers"],
            timeseries_manifests=data["timeseries"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nodes.to_parquet(tmp_path / "nodes.parquet", index=False)
            edges.to_parquet(tmp_path / "edges.parquet", index=False)

            adapter = FederatedGraphAdapter.from_parquet(tmp_path)
            self.assertEqual(adapter.get_node("building:0")["semantic_type"], "brick:Building")
            self.assertIn("load:0", adapter.neighbors("building:0", "HAS_LOAD"))
            batches = adapter.to_falkor_batches(batch_size=2)

        self.assertGreaterEqual(len(batches["nodes"]), 1)
        self.assertGreaterEqual(len(batches["edges"]), 1)
        self.assertTrue(all("UNWIND $props AS p" in batch["cypher"] for batch in batches["nodes"]))


if __name__ == "__main__":
    unittest.main()

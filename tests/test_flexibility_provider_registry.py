import unittest

import pandas as pd

from gridalyn.operations.market.providers import (
    build_network_sensitivity,
    build_provider_registry,
    select_providers_for_constraint,
    summarize_provider_registry,
)


class FlexibilityProviderRegistryTest(unittest.TestCase):
    def _fixtures(self):
        connectivity = pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:0",
                    "lv_feeder_bus_id": "bus:f0",
                    "lv_transformer_id": "transformer:0",
                },
                {
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "load_bus_id": "bus:1",
                    "lv_feeder_bus_id": "bus:f1",
                    "lv_transformer_id": "transformer:1",
                },
            ]
        )
        asset_registry = pd.DataFrame(
            [
                {
                    "scenario_id": "S4",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "pandapower_load": 0,
                    "lv_bus_id": "bus:0",
                    "has_ev": True,
                    "ev_id": "ev:S4:0",
                    "charger_kw": 7.2,
                    "soft_cls_participant": True,
                    "hard_cls_enabled": True,
                    "max_soft_kw": 5.0,
                    "max_hard_kw": 7.2,
                },
                {
                    "scenario_id": "S4",
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "pandapower_load": 1,
                    "lv_bus_id": "bus:1",
                    "has_ev": True,
                    "ev_id": "ev:S4:1",
                    "charger_kw": 7.2,
                    "soft_cls_participant": False,
                    "hard_cls_enabled": True,
                    "max_soft_kw": 0.0,
                    "max_hard_kw": 7.2,
                },
            ]
        )
        return asset_registry, connectivity

    def _scenario_devices(self):
        return pd.DataFrame(
            [
                {
                    "scenario_id": "S4",
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_device_id": "scenario_device:S4:device:building:0:hvac_heating",
                    "device_id": "device:building:0:hvac_heating",
                    "building_model_id": "building_model:building:0",
                    "building_id": "building:0",
                    "device_type": "hvac_heating",
                    "aggregator_id": "aggregator:S4:default",
                    "available_kw": 3.5,
                },
                {
                    "scenario_id": "S4",
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_device_id": "scenario_device:S4:device:building:0:hvac_cooling",
                    "device_id": "device:building:0:hvac_cooling",
                    "building_model_id": "building_model:building:0",
                    "building_id": "building:0",
                    "device_type": "hvac_cooling",
                    "aggregator_id": "aggregator:S4:default",
                    "available_kw": 1.5,
                },
                {
                    "scenario_id": "S4",
                    "provider_id": "provider:S4:ev:S4:0:hard_cls",
                    "scenario_device_id": "scenario_device:S4:device:building:0:evse_l2",
                    "device_id": "device:building:0:evse_l2",
                    "building_model_id": "building_model:building:0",
                    "building_id": "building:0",
                    "device_type": "evse_l2",
                    "aggregator_id": "aggregator:S4:default",
                    "available_kw": 7.2,
                },
                {
                    "scenario_id": "S4",
                    "provider_id": "provider:S4:ev:S4:1:hard_cls",
                    "scenario_device_id": "scenario_device:S4:device:building:1:evse_l2",
                    "device_id": "device:building:1:evse_l2",
                    "building_model_id": "building_model:building:1",
                    "building_id": "building:1",
                    "device_type": "evse_l2",
                    "aggregator_id": "aggregator:S4:default",
                    "available_kw": 7.2,
                },
            ]
        )

    def test_build_provider_registry_keeps_grid_zone_for_soft_and_hard_assets(self):
        asset_registry, connectivity = self._fixtures()

        providers = build_provider_registry(asset_registry, connectivity)

        self.assertEqual(len(providers), 3)
        by_id = providers.set_index("provider_id").to_dict("index")
        self.assertEqual(
            by_id["provider:S4:building:0:soft_cls"]["constraint_zone_id"],
            "transformer:0",
        )
        self.assertEqual(
            by_id["provider:S4:ev:S4:1:hard_cls"]["constraint_zone_id"],
            "transformer:1",
        )
        self.assertEqual(
            by_id["provider:S4:building:0:soft_cls"]["source_standard"],
            "EFOnt_CLS_CIM",
        )

    def test_provider_registry_can_attach_scenario_device_lineage(self):
        asset_registry, connectivity = self._fixtures()

        providers = build_provider_registry(
            asset_registry,
            connectivity,
            scenario_device_registry=self._scenario_devices(),
        )

        by_id = providers.set_index("provider_id").to_dict("index")
        soft = by_id["provider:S4:building:0:soft_cls"]
        hard = by_id["provider:S4:ev:S4:0:hard_cls"]
        self.assertEqual(soft["building_model_id"], "building_model:building:0")
        self.assertEqual(soft["scenario_device_count"], 2)
        self.assertEqual(soft["device_types"], "hvac_cooling;hvac_heating")
        self.assertIn("scenario_device:S4:device:building:0:hvac_heating", soft["scenario_device_ids"])
        self.assertEqual(hard["scenario_device_ids"], "scenario_device:S4:device:building:0:evse_l2")
        self.assertEqual(hard["device_ids"], "device:building:0:evse_l2")
        self.assertEqual(hard["aggregator_id"], "aggregator:S4:default")

    def test_network_sensitivity_and_selection_prioritize_local_effective_cost(self):
        asset_registry, connectivity = self._fixtures()
        providers = build_provider_registry(asset_registry, connectivity)
        sensitivity = build_network_sensitivity(providers)

        local = sensitivity.loc[
            lambda df: (df["provider_id"] == "provider:S4:building:0:soft_cls")
            & (df["constraint_id"] == "transformer:0")
        ].iloc[0]
        remote = sensitivity.loc[
            lambda df: (df["provider_id"] == "provider:S4:building:0:soft_cls")
            & (df["constraint_id"] == "transformer:1")
        ].iloc[0]
        self.assertEqual(local["sensitivity_kw_per_kw"], 1.0)
        self.assertEqual(remote["sensitivity_kw_per_kw"], 0.0)

        selected = select_providers_for_constraint(
            providers,
            sensitivity,
            scenario_id="S4",
            constraint_id="transformer:0",
            required_kw=6.0,
        )

        self.assertEqual(
            list(selected["provider_id"]),
            [
                "provider:S4:building:0:soft_cls",
                "provider:S4:ev:S4:0:hard_cls",
            ],
        )
        self.assertAlmostEqual(selected["selected_kw"].sum(), 6.0)
        self.assertTrue((selected["effective_cost_per_kw_h"] > 0).all())

    def test_provider_summary_reports_capacity_by_scenario_and_type(self):
        asset_registry, connectivity = self._fixtures()
        providers = build_provider_registry(asset_registry, connectivity)

        summary = summarize_provider_registry(providers)

        s4 = summary["scenarios"][0]
        self.assertEqual(s4["scenario_id"], "S4")
        self.assertEqual(s4["n_providers"], 3)
        self.assertEqual(s4["n_soft_building_providers"], 1)
        self.assertEqual(s4["n_hard_ev_providers"], 2)
        self.assertAlmostEqual(s4["available_capacity_kw"], 19.4)


if __name__ == "__main__":
    unittest.main()

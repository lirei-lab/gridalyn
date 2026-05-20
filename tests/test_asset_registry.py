import unittest

import pandas as pd

from gridalyn.assets.modeling.assets import build_asset_registry, summarize_asset_registry


class AssetRegistryTest(unittest.TestCase):
    def test_build_asset_registry_preserves_assets_and_cls_roles(self):
        buildings = pd.DataFrame(
            [
                {
                    "building_id": "b0",
                    "load_id": "load-0",
                    "pandapower_load": 0,
                    "lv_bus_id": 10,
                    "lat": 4.0,
                    "lon": -74.0,
                    "area_m2": 100.0,
                    "static_p_mw": 0.01,
                },
                {
                    "building_id": "b1",
                    "load_id": "load-1",
                    "pandapower_load": 1,
                    "lv_bus_id": 11,
                    "lat": 4.1,
                    "lon": -74.1,
                    "area_m2": 120.0,
                    "static_p_mw": 0.02,
                },
                {
                    "building_id": "b2",
                    "load_id": "load-2",
                    "pandapower_load": 2,
                    "lv_bus_id": 12,
                    "lat": 4.2,
                    "lon": -74.2,
                    "area_m2": 80.0,
                    "static_p_mw": 0.03,
                },
                {
                    "building_id": "b3",
                    "load_id": "load-3",
                    "pandapower_load": 3,
                    "lv_bus_id": 13,
                    "lat": 4.3,
                    "lon": -74.3,
                    "area_m2": 90.0,
                    "static_p_mw": 0.04,
                },
            ]
        )
        assignments = pd.DataFrame(
            [
                {
                    "scenario_id": "S4",
                    "building_id": "b0",
                    "load_id": "load-0",
                    "pandapower_load": 0,
                    "has_ev": True,
                    "ev_id": "ev:S4:0",
                    "charger_kw": 7.2,
                    "c_soft_fraction": 0.65,
                },
                {
                    "scenario_id": "S4",
                    "building_id": "b1",
                    "load_id": "load-1",
                    "pandapower_load": 1,
                    "has_ev": False,
                    "ev_id": None,
                    "charger_kw": 0.0,
                    "c_soft_fraction": 0.0,
                },
                {
                    "scenario_id": "S4",
                    "building_id": "b2",
                    "load_id": "load-2",
                    "pandapower_load": 2,
                    "has_ev": True,
                    "ev_id": "ev:S4:1",
                    "charger_kw": 7.2,
                    "c_soft_fraction": 0.65,
                },
                {
                    "scenario_id": "S4",
                    "building_id": "b3",
                    "load_id": "load-3",
                    "pandapower_load": 3,
                    "has_ev": False,
                    "ev_id": None,
                    "charger_kw": 0.0,
                    "c_soft_fraction": 0.0,
                },
            ]
        )

        registry = build_asset_registry(
            buildings,
            assignments,
            soft_participation_rate=0.5,
            soft_assignment_seed=7,
        )

        self.assertEqual(len(registry), 4)
        self.assertEqual(int(registry["soft_cls_participant"].sum()), 2)
        self.assertEqual(int(registry["has_ev"].sum()), 2)
        self.assertEqual(int(registry["hard_cls_enabled"].sum()), 2)
        self.assertTrue(
            registry.loc[registry["building_id"] == "b0", "contract_type"].iloc[0]
            in {"soft+hard_ev", "hard_ev"}
        )
        self.assertEqual(
            registry.loc[registry["building_id"] == "b1", "max_hard_kw"].iloc[0],
            0.0,
        )
        self.assertEqual(
            registry.loc[registry["building_id"] == "b2", "max_hard_kw"].iloc[0],
            7.2,
        )
        self.assertAlmostEqual(
            registry.loc[registry["building_id"] == "b2", "max_soft_kw"].iloc[0],
            19.5,
        )

    def test_summarize_asset_registry_reports_overlap_by_scenario(self):
        buildings = pd.DataFrame(
            [
                {"building_id": "b0", "load_id": "l0", "pandapower_load": 0},
                {"building_id": "b1", "load_id": "l1", "pandapower_load": 1},
            ]
        )
        assignments = pd.DataFrame(
            [
                {
                    "scenario_id": "S0",
                    "building_id": "b0",
                    "load_id": "l0",
                    "pandapower_load": 0,
                    "has_ev": False,
                    "ev_id": None,
                    "charger_kw": 0.0,
                    "c_soft_fraction": 0.0,
                },
                {
                    "scenario_id": "S0",
                    "building_id": "b1",
                    "load_id": "l1",
                    "pandapower_load": 1,
                    "has_ev": True,
                    "ev_id": "ev:S0:0",
                    "charger_kw": 7.2,
                    "c_soft_fraction": 0.65,
                },
            ]
        )

        registry = build_asset_registry(
            buildings,
            assignments,
            soft_participation_rate=0.5,
            soft_assignment_seed=1,
        )
        summary = summarize_asset_registry(registry)

        self.assertEqual(summary["n_scenarios"], 1)
        self.assertEqual(summary["scenarios"][0]["scenario_id"], "S0")
        self.assertEqual(summary["scenarios"][0]["n_ev"], 1)
        self.assertEqual(summary["scenarios"][0]["n_hard_cls_enabled"], 1)
        self.assertEqual(summary["scenarios"][0]["n_soft_participants"], 1)


if __name__ == "__main__":
    unittest.main()

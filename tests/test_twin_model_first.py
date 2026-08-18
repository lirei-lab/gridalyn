"""Phase 21 R7 proof: the digital twin is model-first with capability layers.

The twin's semantic graph is model-first by default: the generic CIM/Brick
core is always emitted, and the flexibility layer (CLS/EFOnt/market ontology,
EVSE/DER nodes, provider registry) is an **on-demand capability** a project
declares. These tests prove:

* a core-only graph (``capabilities=set()``) carries **zero** flexibility
  triples;
* with the ``flexibility`` capability ON the graph is **value-identical** to
  the pre-Phase-21 graph (R7) and to the legacy ``capabilities=None`` default;
* the generic twin build excludes the EV-hosting/flexibility stages unless the
  capability is declared.

This mirrors the "no assert True guards" discipline — every assertion checks
actual graph/profiles/steps.
"""

from __future__ import annotations

import unittest

import pandas as pd

from gridalyn.projects.workflows.digital_twin.build import build_digital_twin_steps
from gridalyn.twin.semantic.mappings import (
    build_semantic_graph,
    north_america_profile,
    profile_with_capabilities,
)

_FLEX_PREFIXES = ("cls:", "efont:", "ieee2030_5:")


def _fixtures() -> dict[str, pd.DataFrame]:
    """A minimal grid with one soft-CLS building and one hard-CLS EV provider."""
    buses = pd.DataFrame(
        [
            {"bus_id": "bus:0", "name": "lv_bus_0", "pandapower_bus": 0},
            {"bus_id": "bus:1", "name": "lv_bus_1", "pandapower_bus": 1},
        ]
    )
    lines = pd.DataFrame(
        [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
    )
    transformers = pd.DataFrame(
        [
            {
                "transformer_id": "transformer:0",
                "hv_bus_id": "bus:0",
                "lv_bus_id": "bus:1",
            }
        ]
    )
    buildings = pd.DataFrame(
        [
            {
                "building_id": "building:0",
                "load_id": "load:0",
                "lv_bus_id": "bus:1",
            }
        ]
    )
    connectivity = pd.DataFrame(
        [{"building_id": "building:0", "load_id": "load:0", "load_bus_id": "bus:1"}]
    )
    assets = pd.DataFrame(
        [
            {
                "scenario_id": "S4",
                "building_id": "building:0",
                "load_id": "load:0",
                "has_ev": True,
                "ev_id": "ev:S4:0",
                "soft_cls_participant": True,
                "hard_cls_enabled": True,
                "max_soft_kw": 4.0,
                "max_hard_kw": 3.5,
                "charger_kw": 7.2,
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
                "load_bus_id": "bus:1",
                "feeder_bus_id": "bus:0",
                "constraint_zone_id": "transformer:0",
                "constraint_zone_type": "transformer",
                "available_capacity_kw": 4.0,
                "base_cost_per_kw_h": 0.05,
                "selection_priority": 1,
                "scenario_device_ids": "sd:S4:0",
                "device_ids": "dev:0",
                "device_types": "building",
            },
            {
                "provider_id": "provider:S4:ev:S4:0:hard_cls",
                "scenario_id": "S4",
                "provider_type": "hard_cls_ev",
                "building_id": "building:0",
                "load_id": "load:0",
                "ev_id": "ev:S4:0",
                "pandapower_load": 1,
                "load_bus_id": "bus:1",
                "feeder_bus_id": "bus:0",
                "constraint_zone_id": "transformer:0",
                "constraint_zone_type": "transformer",
                "available_capacity_kw": 3.5,
                "base_cost_per_kw_h": 0.06,
                "selection_priority": 2,
                "scenario_device_ids": "sd:S4:1",
                "device_ids": "dev:1",
                "device_types": "ev",
            },
        ]
    )
    return {
        "buses": buses,
        "lines": lines,
        "transformers": transformers,
        "buildings": buildings,
        "connectivity": connectivity,
        "assets": assets,
        "providers": providers,
        "timeseries": {},
    }


class TwinModelFirstTest(unittest.TestCase):
    def _build(self, capabilities):
        data = _fixtures()
        nodes, edges, _manifest = build_semantic_graph(
            buses=data["buses"],
            lines=data["lines"],
            transformers=data["transformers"],
            buildings=data["buildings"],
            connectivity=data["connectivity"],
            asset_registry=data["assets"],
            provider_registry=data["providers"],
            timeseries_manifests=data["timeseries"],
            capabilities=capabilities,
        )
        return nodes, edges

    def test_model_first_core_has_zero_flexibility_triples(self) -> None:
        nodes, _edges = self._build(set())
        flex_nodes = nodes.loc[nodes["semantic_type"].str.startswith(_FLEX_PREFIXES)]
        self.assertEqual(len(flex_nodes), 0)
        # The model-first core still carries the generic grid/observation types.
        remaining = set(nodes["semantic_type"].unique())
        self.assertLessEqual(
            remaining,
            {
                "brick:Building",
                "cim:ACLineSegment",
                "cim:ConnectivityNode",
                "cim:EnergyConsumer",
                "cim:PowerTransformer",
                "dt:Scenario",
                "dt:SimulationRun",
                "dt:TimeSeriesDataset",
            },
        )

    def test_flexibility_capability_on_emits_the_flex_ontology(self) -> None:
        nodes, _edges = self._build({"flexibility"})
        flex_nodes = nodes.loc[nodes["semantic_type"].str.startswith(_FLEX_PREFIXES)]
        semantic_types = set(flex_nodes["semantic_type"].unique())
        self.assertIn("cls:FlexibilityProvider", semantic_types)
        self.assertIn("cls:SoftCLSContract", semantic_types)
        self.assertIn("cls:HardCLSContract", semantic_types)
        self.assertIn("cls:FlexibilityAggregator", semantic_types)
        self.assertIn("ieee2030_5:EVSE", semantic_types)
        self.assertTrue(
            any(t.startswith("efont:") for t in semantic_types),
            semantic_types,
        )

    def test_legacy_default_matches_explicit_flexibility_capability(self) -> None:
        nodes_default, _ = self._build(None)
        nodes_flex, _ = self._build({"flexibility"})
        # R7: ``None`` (legacy callers) is value-identical to declaring the
        # flexibility capability explicitly.
        self.assertTrue(nodes_default.equals(nodes_flex))

    def test_profile_core_vs_combined(self) -> None:
        core = north_america_profile()
        combined = profile_with_capabilities({"flexibility"})
        self.assertNotIn("cls:FlexibilityProvider", core["allowed_semantic_types"])
        self.assertIn("cls:FlexibilityProvider", combined["allowed_semantic_types"])
        self.assertIn("cim:ConnectivityNode", core["allowed_semantic_types"])
        self.assertIn("cim:ConnectivityNode", combined["allowed_semantic_types"])
        # The combined profile is a superset of the core.
        self.assertLessEqual(
            set(core["allowed_semantic_types"]),
            set(combined["allowed_semantic_types"]),
        )

    def test_generic_build_excludes_ev_and_flexibility_stages(self) -> None:
        generic_names = {
            step["name"] for step in build_digital_twin_steps(capabilities=set())
        }
        self.assertNotIn("generate_scenarios", generic_names)
        self.assertNotIn("generate_ev_timeseries", generic_names)
        self.assertNotIn("run_powerflow", generic_names)
        self.assertNotIn("generate_flexibility_providers", generic_names)
        # Generic build still has the model-first core.
        self.assertIn("export_base", generic_names)
        self.assertIn("generate_building_models", generic_names)
        self.assertIn("generate_semantic_graph", generic_names)
        self.assertIn("generate_dashboard_catalog", generic_names)

    def test_default_build_preserves_full_legacy_plan(self) -> None:
        default_names = {step["name"] for step in build_digital_twin_steps()}
        # The legacy default (capabilities=None) keeps the EV/flexibility
        # stages so existing callers are unchanged (R7).
        self.assertIn("generate_scenarios", default_names)
        self.assertIn("run_powerflow", default_names)
        self.assertIn("generate_flexibility_providers", default_names)
        self.assertIn("generate_dashboard_catalog", default_names)


if __name__ == "__main__":
    unittest.main()

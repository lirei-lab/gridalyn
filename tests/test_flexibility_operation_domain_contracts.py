import unittest

import pandas as pd

from gridalyn.operations.flexibility import (
    build_aggregator_portfolios,
    build_dispatch_instructions,
    build_operation_context,
    build_provider_offers,
    build_settlement_records,
    run_flexibility_clearing_operation,
)
from gridalyn.operations import (
    build_aggregator_portfolios as public_build_aggregator_portfolios,
    build_dispatch_instructions as public_build_dispatch_instructions,
    build_provider_offers as public_build_provider_offers,
    build_settlement_records as public_build_settlement_records,
)


class FlexibilityOperationDomainContractsTest(unittest.TestCase):
    def _providers(self):
        return pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 5.0,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                    "aggregator_id": "aggregator:S4:north",
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 4.0,
                    "base_cost_per_kw_h": 4.0,
                    "selection_priority": 1,
                    "aggregator_id": "aggregator:S4:north",
                },
                {
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "building_id": "building:2",
                    "load_id": "load:2",
                    "constraint_zone_id": "transformer:99",
                    "available_capacity_kw": 7.2,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                    "aggregator_id": "aggregator:S4:south",
                },
            ]
        )

    def _requirements(self):
        return pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "timestamp": "2024-01-01 19:00:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 7.0,
                    "overload_pctpt": 2.0,
                }
            ]
        )

    def _impact(self):
        return pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 5.0,
                    "selection_score": 3.0,
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 4.0,
                    "selection_score": 2.0,
                },
            ]
        )

    def test_provider_registry_builds_aggregator_portfolios_and_offer_book(self):
        providers = self._providers()

        portfolios = build_aggregator_portfolios(providers, scenario_id="S4")
        offers = build_provider_offers(providers, scenario_id="S4")

        north = portfolios.set_index("aggregator_id").loc["aggregator:S4:north"]
        self.assertEqual(north["provider_count"], 2)
        self.assertEqual(north["soft_provider_count"], 2)
        self.assertEqual(north["hard_provider_count"], 0)
        self.assertAlmostEqual(north["available_capacity_kw"], 9.0)
        self.assertEqual(north["constraint_zone_ids"], "transformer:64")
        self.assertIn("provider:S4:building:0:soft_cls", north["provider_ids"])

        offer = offers.set_index("offer_id").loc[
            "offer:S4:provider:S4:building:0:soft_cls"
        ]
        self.assertEqual(offer["aggregator_id"], "aggregator:S4:north")
        self.assertEqual(offer["quantity_kw"], 5.0)
        self.assertEqual(offer["price_per_kw_h"], 3.0)
        self.assertEqual(offer["constraint_zone_id"], "transformer:64")

    def test_clearing_outputs_can_be_promoted_to_dispatch_and_settlement_records(self):
        requirements = self._requirements()
        providers = self._providers()
        impact = self._impact()
        context = build_operation_context(
            scenario_id="S4",
            clearing_method="surrogate",
            dt_h=0.25,
            requirements=requirements,
            providers=providers,
            impact=impact,
            model_version_id="model:sha256:test",
            study_run_id="run:S4:test",
        )

        events, selections, report = run_flexibility_clearing_operation(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id="S4",
            dt_h=0.25,
            clearing_method="surrogate",
            model_version_id="model:sha256:test",
            study_run_id="run:S4:test",
        )
        dispatch = build_dispatch_instructions(
            selections=selections,
            providers=providers,
            context=context,
        )
        settlement = build_settlement_records(dispatch, dt_h=0.25)

        self.assertEqual(len(events), 1)
        self.assertEqual(len(dispatch), 2)
        first = dispatch.iloc[0]
        self.assertTrue(first["instruction_id"].startswith("dispatch:"))
        self.assertEqual(first["operation_id"], context.operation_id)
        self.assertEqual(first["aggregator_id"], "aggregator:S4:north")
        self.assertEqual(first["dispatch_action"], "soft_cls_limit")
        self.assertEqual(first["model_version_id"], "model:sha256:test")
        self.assertEqual(first["study_run_id"], "run:S4:test")

        self.assertEqual(len(settlement), 2)
        self.assertTrue(settlement["settlement_id"].str.startswith("settlement:").all())
        self.assertAlmostEqual(
            settlement["payment_usd"].sum(),
            dispatch["estimated_cost_usd"].sum(),
        )
        self.assertEqual(report["operation_domain"]["dispatch_instruction_count"], 2)
        self.assertEqual(report["operation_domain"]["settlement_record_count"], 2)
        self.assertAlmostEqual(report["operation_domain"]["settlement_usd"], 5.75)

    def test_operations_api_exports_operation_domain_contracts(self):
        self.assertIs(public_build_aggregator_portfolios, build_aggregator_portfolios)
        self.assertIs(public_build_provider_offers, build_provider_offers)
        self.assertIs(public_build_dispatch_instructions, build_dispatch_instructions)
        self.assertIs(public_build_settlement_records, build_settlement_records)


if __name__ == "__main__":
    unittest.main()

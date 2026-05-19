import unittest

import pandas as pd

from gridalyn.operations.flexibility import (
    build_operation_context,
    run_flexibility_clearing_operation,
    validate_flexibility_operation_inputs,
)
from gridalyn.platform import (
    build_operation_context as platform_build_operation_context,
    run_flexibility_clearing_operation as platform_run_flexibility_clearing_operation,
)


class FlexibilityOperationContractsTest(unittest.TestCase):
    def _fixtures(self):
        providers = pd.DataFrame(
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
                    "provider_id": "provider:S4:ev:S4:1:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 7.2,
                    "base_cost_per_kw_h": 10.0,
                    "selection_priority": 2,
                    "aggregator_id": "aggregator:S4:south",
                },
            ]
        )
        impact = pd.DataFrame(
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
                    "provider_id": "provider:S4:ev:S4:1:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 0.8,
                    "predicted_relief_kw": 5.76,
                    "selection_score": 1.0,
                },
            ]
        )
        requirements = pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "timestamp": "2024-01-01 19:00:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 8.0,
                    "overload_pctpt": 2.0,
                }
            ]
        )
        return requirements, providers, impact

    def test_operation_context_is_stable_and_describes_governance_scope(self):
        requirements, providers, impact = self._fixtures()

        first = build_operation_context(
            scenario_id="S4",
            clearing_method="surrogate",
            dt_h=0.25,
            requirements=requirements,
            providers=providers,
            impact=impact,
            model_version_id="model:sha256:abc",
            study_run_id="run:S4:abc",
        )
        second = build_operation_context(
            scenario_id="S4",
            clearing_method="surrogate",
            dt_h=0.25,
            requirements=requirements,
            providers=providers,
            impact=impact,
            model_version_id="model:sha256:abc",
            study_run_id="run:S4:abc",
        )

        self.assertEqual(first.operation_id, second.operation_id)
        self.assertTrue(first.operation_id.startswith("operation:S4:surrogate:sha256:"))
        self.assertEqual(first.model_version_id, "model:sha256:abc")
        self.assertEqual(first.study_run_id, "run:S4:abc")
        self.assertEqual(first.market_role, "dso_flexibility_clearing")
        self.assertEqual(first.ontology_profile, "north_america")

    def test_validation_requires_method_specific_impact_columns(self):
        requirements, providers, impact = self._fixtures()
        context = build_operation_context(
            scenario_id="S4",
            clearing_method="surrogate",
            dt_h=0.25,
            requirements=requirements,
            providers=providers,
            impact=impact.drop(columns=["selection_score"]),
        )

        validation = validate_flexibility_operation_inputs(
            requirements=requirements,
            providers=providers,
            impact=impact.drop(columns=["selection_score"]),
            context=context,
        )

        self.assertFalse(validation.valid)
        self.assertIn("impact is missing required columns: selection_score", validation.errors)

    def test_clearing_operation_wraps_market_result_with_context_and_traceability(self):
        requirements, providers, impact = self._fixtures()

        events, selections, report = run_flexibility_clearing_operation(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id="S4",
            dt_h=0.25,
            clearing_method="surrogate",
            model_version_id="model:sha256:abc",
            study_run_id="run:S4:abc",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(len(selections), 2)
        self.assertEqual(report["operation_context"]["scenario_id"], "S4")
        self.assertEqual(report["operation_context"]["clearing_method"], "surrogate")
        self.assertEqual(report["governance"]["model_version_id"], "model:sha256:abc")
        self.assertEqual(report["governance"]["study_run_id"], "run:S4:abc")
        self.assertTrue(report["validation"]["valid"])
        self.assertEqual(report["input_summary"]["provider_count"], 2)
        self.assertEqual(report["input_summary"]["aggregator_count"], 2)

    def test_platform_api_exports_flexibility_operation_facade(self):
        self.assertIs(platform_build_operation_context, build_operation_context)
        self.assertIs(
            platform_run_flexibility_clearing_operation,
            run_flexibility_clearing_operation,
        )


if __name__ == "__main__":
    unittest.main()

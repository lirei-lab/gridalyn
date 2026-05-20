import unittest

import pandas as pd

from gridalyn.operations.flexibility import (
    build_dispatch_instructions,
    build_network_constraint_set,
    build_operation_context,
    build_operational_kpi_report,
    build_settlement_records,
    run_flexibility_clearing_operation,
)
from gridalyn.operations import (
    build_network_constraint_set as public_build_network_constraint_set,
    build_operational_kpi_report as public_build_operational_kpi_report,
)


class FlexibilityOperationKpiTest(unittest.TestCase):
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
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "building_id": "building:2",
                    "load_id": "load:2",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 4.0,
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
                    "required_kw": 8.0,
                    "overload_pctpt": 2.0,
                    "loading_percent": 102.0,
                    "limit_percent": 100.0,
                },
                {
                    "timestep": 1,
                    "timestamp": "2024-01-01 19:15:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 0.0,
                    "overload_pctpt": 0.0,
                    "loading_percent": 99.0,
                    "limit_percent": 100.0,
                },
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
                    "provider_id": "provider:S4:ev:S4:2:hard_cls",
                    "scenario_id": "S4",
                    "provider_type": "hard_cls_ev",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 4.0,
                    "selection_score": 1.0,
                },
            ]
        )

    def test_build_network_constraint_set_normalizes_active_constraints(self):
        constraints = build_network_constraint_set(
            self._requirements(),
            scenario_id="S4",
            source="pandapower_transformer_loading",
            model_version_id="model:sha256:test",
            study_run_id="run:S4:test",
        )

        self.assertEqual(len(constraints), 1)
        row = constraints.iloc[0]
        self.assertTrue(row["constraint_uid"].startswith("constraint:sha256:"))
        self.assertEqual(row["constraint_id"], "transformer:64")
        self.assertEqual(row["constraint_type"], "cim:PowerTransformer")
        self.assertEqual(row["severity_kw"], 8.0)
        self.assertEqual(row["severity_pctpt"], 2.0)
        self.assertEqual(row["limit_value"], 100.0)
        self.assertEqual(row["observed_value"], 102.0)
        self.assertEqual(row["model_version_id"], "model:sha256:test")
        self.assertEqual(row["study_run_id"], "run:S4:test")

    def test_operational_kpi_report_summarizes_delivery_cost_and_concentration(self):
        requirements = self._requirements()
        providers = self._providers()
        impact = self._impact()
        dt_h = 0.25
        context = build_operation_context(
            scenario_id="S4",
            clearing_method="surrogate",
            dt_h=dt_h,
            requirements=requirements,
            providers=providers,
            impact=impact,
            model_version_id="model:sha256:test",
            study_run_id="run:S4:test",
        )
        constraints = build_network_constraint_set(
            requirements,
            scenario_id="S4",
            model_version_id=context.model_version_id,
            study_run_id=context.study_run_id,
        )
        events, selections, _ = run_flexibility_clearing_operation(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id="S4",
            dt_h=dt_h,
            clearing_method="surrogate",
            model_version_id=context.model_version_id,
            study_run_id=context.study_run_id,
        )
        dispatch = build_dispatch_instructions(
            selections=selections,
            providers=providers,
            context=context,
        )
        settlement = build_settlement_records(dispatch, dt_h=dt_h)

        report = build_operational_kpi_report(
            events=events,
            dispatch_instructions=dispatch,
            settlement_records=settlement,
            constraints=constraints,
            context=context,
            dt_h=dt_h,
        )

        self.assertEqual(report["report_id"], "operational_kpi_report")
        self.assertEqual(report["operation_id"], context.operation_id)
        self.assertAlmostEqual(report["summary"]["required_mwh"], 0.002)
        self.assertAlmostEqual(report["summary"]["delivered_mwh"], 0.002)
        self.assertAlmostEqual(report["summary"]["shortfall_mwh"], 0.0)
        self.assertAlmostEqual(report["summary"]["settlement_usd"], 11.25)
        self.assertAlmostEqual(report["summary"]["cost_per_mwh_delivered"], 5625.0)
        self.assertAlmostEqual(report["summary"]["soft_selected_mwh"], 0.00125)
        self.assertAlmostEqual(report["summary"]["hard_selected_mwh"], 0.00075)
        self.assertEqual(report["summary"]["selected_provider_count"], 2)
        self.assertEqual(report["summary"]["selected_aggregator_count"], 2)
        self.assertAlmostEqual(report["summary"]["aggregator_concentration_top1_pct"], 0.625)
        self.assertAlmostEqual(report["summary"]["topological_concentration_top1_pct"], 1.0)
        self.assertEqual(report["constraint_summary"][0]["constraint_id"], "transformer:64")

    def test_clearing_operation_report_includes_constraints_and_kpis(self):
        events, selections, report = run_flexibility_clearing_operation(
            requirements=self._requirements(),
            providers=self._providers(),
            impact=self._impact(),
            scenario_id="S4",
            dt_h=0.25,
            clearing_method="surrogate",
            model_version_id="model:sha256:test",
            study_run_id="run:S4:test",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(len(selections), 2)
        self.assertEqual(report["network_constraints"]["active_constraint_count"], 1)
        self.assertEqual(report["operational_kpis"]["report_id"], "operational_kpi_report")
        self.assertAlmostEqual(
            report["operational_kpis"]["summary"]["delivered_mwh"],
            0.002,
        )

    def test_operations_api_exports_constraint_and_kpi_builders(self):
        self.assertIs(public_build_network_constraint_set, build_network_constraint_set)
        self.assertIs(public_build_operational_kpi_report, build_operational_kpi_report)


if __name__ == "__main__":
    unittest.main()

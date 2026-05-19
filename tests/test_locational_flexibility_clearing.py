import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.market.locational_clearing import (
    build_locational_clearing,
    write_locational_clearing_outputs,
)
from gridalyn.workflows.scripts.generate_locational_flexibility_clearing import _infer_dt_h


class LocationalFlexibilityClearingTest(unittest.TestCase):
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
                },
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 5.0,
                    "base_cost_per_kw_h": 4.0,
                    "selection_priority": 1,
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
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_id": "transformer:64",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 5.0,
                    "selection_score": 2.0,
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
        requirements = pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "timestamp": "2024-01-01 19:00:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 12.0,
                    "overload_pctpt": 5.7,
                },
                {
                    "timestep": 1,
                    "timestamp": "2024-01-01 19:05:00",
                    "constraint_id": "transformer:64",
                    "required_kw": 3.0,
                    "overload_pctpt": 1.4,
                },
            ]
        )
        return requirements, providers, impact

    def test_build_locational_clearing_selects_soft_first_and_reports_metrics(self):
        requirements, providers, impact = self._fixtures()

        events, selections, report = build_locational_clearing(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id="S4",
            dt_h=0.25,
        )

        self.assertEqual(report["report_id"], "locational_flexibility_clearing")
        self.assertEqual(report["scenario_id"], "S4")
        self.assertEqual(report["summary"]["constraint_event_count"], 2)
        self.assertAlmostEqual(report["summary"]["required_mwh"], 15.0 * 0.25 / 1000.0)
        self.assertAlmostEqual(report["summary"]["selected_relief_mwh"], 15.0 * 0.25 / 1000.0)
        self.assertAlmostEqual(report["summary"]["shortfall_mwh"], 0.0)
        self.assertEqual(report["summary"]["unique_provider_count"], 3)

        first_event = events.loc[events["event_id"] == "S4:transformer:64:0"].iloc[0]
        self.assertAlmostEqual(first_event["selected_soft_kw"], 10.0)
        self.assertAlmostEqual(first_event["selected_hard_kw"], 2.0)
        self.assertAlmostEqual(first_event["shortfall_kw"], 0.0)

        first_ids = selections.loc[
            selections["event_id"] == "S4:transformer:64:0", "provider_id"
        ].tolist()
        self.assertEqual(
            first_ids,
            [
                "provider:S4:building:0:soft_cls",
                "provider:S4:building:1:soft_cls",
                "provider:S4:ev:S4:2:hard_cls",
            ],
        )

    def test_write_locational_clearing_outputs_writes_report_and_parquet_tables(self):
        requirements, providers, impact = self._fixtures()
        events, selections, report = build_locational_clearing(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id="S4",
            dt_h=0.25,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = write_locational_clearing_outputs(
                out_dir=Path(tmp),
                events=events,
                selections=selections,
                report=report,
            )

            self.assertTrue(out["events"].exists())
            self.assertTrue(out["selections"].exists())
            self.assertTrue(out["report"].exists())
            self.assertEqual(len(pd.read_parquet(out["events"])), 2)
            self.assertEqual(len(pd.read_parquet(out["selections"])), 4)
            summary = json.loads(out["report"].read_text(encoding="utf-8"))
            self.assertEqual(
                summary["artifacts"],
                {
                    "events": "locational_clearing_events.parquet",
                    "selections": "locational_clearing_selections.parquet",
                    "summary": "locational_clearing_summary.json",
                },
            )

    def test_infer_dt_h_accepts_timestamp_series(self):
        dt_h = _infer_dt_h(
            pd.DataFrame(
                {
                    "timestamp": [
                        "2024-01-01 00:00:00",
                        "2024-01-01 00:05:00",
                        "2024-01-01 00:10:00",
                    ]
                }
            )
        )

        self.assertAlmostEqual(dt_h, 5.0 / 60.0)

    def test_build_locational_clearing_reports_shortfall_when_no_candidates_exist(self):
        requirements, providers, impact = self._fixtures()

        events, selections, report = build_locational_clearing(
            requirements=requirements,
            providers=providers,
            impact=impact.loc[impact["constraint_id"] == "missing:constraint"],
            scenario_id="S4",
            dt_h=0.25,
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(len(selections), 0)
        self.assertAlmostEqual(report["summary"]["selected_relief_mwh"], 0.0)
        self.assertAlmostEqual(report["summary"]["shortfall_mwh"], 15.0 * 0.25 / 1000.0)


if __name__ == "__main__":
    unittest.main()

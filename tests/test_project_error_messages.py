"""Tests for located, remediating project error messages."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gridalyn.projects import init_project, validate_project
from gridalyn.projects.loader import read_yaml
from gridalyn.projects.model_inputs import (
    load_numeric_profile_array,
    load_radial_feeder_spec,
    project_input,
)


def _make_project(tmp: str) -> Path:
    target = Path(tmp) / "my_case"
    init_project(target, name="my_case")
    return target


class TestModelInputErrorMessages(unittest.TestCase):
    def test_missing_input_lists_available_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_project(tmp)

            with self.assertRaises(ValueError) as ctx:
                project_input(target, "sourceNetwork")

            message = str(ctx.exception)
            self.assertIn("project.yaml", message)
            self.assertIn("spec.inputs.sourceNetwork not found", message)
            self.assertIn("available inputs:", message)

    def test_missing_model_field_lists_present_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_project(tmp)
            project_file = target / "project.yaml"
            text = project_file.read_text(encoding="utf-8")
            project_file.write_text(
                text.replace(
                    "  inputs:\n    raw: inputs",
                    "  inputs:\n"
                    "    raw: inputs\n"
                    "    sourceNetwork:\n"
                    "      model:\n"
                    "        type: radial_feeder\n"
                    "        name: test_feeder",
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                load_radial_feeder_spec(target)

            message = str(ctx.exception)
            self.assertIn("spec.inputs.sourceNetwork.model.busCount", message)
            self.assertIn("present fields:", message)
            self.assertIn("name", message)

    def test_missing_profile_array_lists_available_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_project(tmp)

            with self.assertRaises(ValueError) as ctx:
                load_numeric_profile_array(target, "loadProfile")

            message = str(ctx.exception)
            self.assertIn("spec.inputs.loadProfile not found", message)
            self.assertIn("available inputs:", message)


class TestSchemaErrorHints(unittest.TestCase):
    def test_missing_required_field_includes_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_project(tmp)
            project_file = target / "project.yaml"
            text = project_file.read_text(encoding="utf-8")
            project_file.write_text(
                text.replace("  version: 0.1.0\n", ""),
                encoding="utf-8",
            )

            report = validate_project(target)

            self.assertFalse(report.valid)
            joined = "\n".join(report.errors)
            self.assertIn("version", joined)
            self.assertIn("add 'version:'", joined)


class TestYamlErrorLocation(unittest.TestCase):
    def test_invalid_yaml_reports_line_and_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.yaml"
            broken.write_text("metadata:\n  name: [unclosed\n", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                read_yaml(broken)

            message = str(ctx.exception)
            self.assertIn("broken.yaml", message)
            self.assertIn("invalid YAML", message)
            self.assertIn("line", message)


class TestStandardPowerflowScenarioLoader(unittest.TestCase):
    def test_loads_scenarios_with_parameters_from_problem_contract(self) -> None:
        from gridalyn.projects.model_inputs import load_standard_powerflow_scenarios

        scenarios = load_standard_powerflow_scenarios(
            Path("projects/ieee_33_bus_demo/project.yaml")
        )

        by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        self.assertEqual(len(scenarios), 5)
        self.assertEqual(by_id["baseline"].load_multiplier, 1.0)
        self.assertEqual(by_id["load_growth_20"].load_multiplier, 1.2)
        self.assertEqual(by_id["pv_midday"].pv_buses, (6, 14, 24, 30))
        self.assertEqual(by_id["pv_midday"].pv_mw_per_bus, 0.25)
        self.assertEqual(by_id["ev_evening_peak"].ev_buses, (17, 18, 25, 30, 32))
        self.assertEqual(by_id["pv_plus_ev"].ev_mw_per_bus, 0.12)

    def test_unsupported_parameter_key_is_reported(self) -> None:
        from gridalyn.projects.model_inputs import load_standard_powerflow_scenarios

        with tempfile.TemporaryDirectory() as tmp:
            target = _make_project(tmp)
            project_file = target / "project.yaml"
            text = project_file.read_text(encoding="utf-8")
            project_file.write_text(
                text.replace(
                    "        role: template_baseline\n",
                    "        role: template_baseline\n"
                    "        parameters:\n"
                    "          notAThing: 1\n",
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                load_standard_powerflow_scenarios(target)

            message = str(ctx.exception)
            self.assertIn("unsupported keys: notAThing", message)
            self.assertIn("supported:", message)


if __name__ == "__main__":
    unittest.main()

"""Tests for the project template registry and the powerflow-demo template."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gridalyn.projects import init_project, run_workflow, validate_project
from gridalyn.projects.api import project_verify
from gridalyn.projects.templates import TEMPLATES


class TestTemplateRegistry(unittest.TestCase):
    def test_registry_contains_expected_templates(self) -> None:
        self.assertEqual(
            sorted(TEMPLATES),
            ["grid-study", "minimal", "powerflow-demo"],
        )
        for template in TEMPLATES.values():
            self.assertTrue(template.description)

    def test_unknown_template_lists_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                init_project(Path(tmp) / "case", name="case", template="nope")
            message = str(ctx.exception)
            self.assertIn("available:", message)
            self.assertIn("powerflow-demo", message)

    def test_every_template_initializes_valid_project(self) -> None:
        for template in TEMPLATES:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "case"
                init_project(target, name="case", template=template)
                report = validate_project(target)
                self.assertTrue(
                    report.valid,
                    f"{template}: " + "\n".join(report.errors),
                )


class TestPowerflowDemoTemplate(unittest.TestCase):
    def test_init_and_run_produces_figure_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo_case"
            init_project(target, name="demo_case", template="powerflow-demo")

            executed = run_workflow(target)

            self.assertEqual(executed, ["prepare_workspace", "run_powerflow_study"])
            figure = target / "outputs/figures/powerflow_demo_voltage_profile.png"
            report = target / "outputs/reports/powerflow_demo_report.json"
            self.assertTrue(figure.exists())
            self.assertTrue(report.exists())

            verification = project_verify(target, write=False)
            self.assertTrue(verification["valid"], verification)


if __name__ == "__main__":
    unittest.main()

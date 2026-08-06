import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gridalyn.projects.workflows.digital_twin.build import (
    build_digital_twin_steps,
    run_digital_twin_build,
)


class DigitalTwinBuildOrchestratorTest(unittest.TestCase):
    def test_core_steps_end_with_dashboard_catalog(self):
        steps = build_digital_twin_steps(skip_heavy=False, include_network_impact=False)
        names = [step["name"] for step in steps]
        command_by_name = {step["name"]: step["command"] for step in steps}

        self.assertIn("export_base", names)
        self.assertIn("generate_building_models", names)
        self.assertIn("generate_scenarios", names)
        self.assertIn("generate_scenario_models", names)
        self.assertIn("run_powerflow", names)
        self.assertIn("generate_dashboard_catalog", names)
        self.assertLess(
            names.index("export_base"), names.index("generate_building_models")
        )
        self.assertLess(
            names.index("generate_building_models"), names.index("generate_scenarios")
        )
        self.assertLess(names.index("export_base"), names.index("generate_scenarios"))
        self.assertLess(
            names.index("generate_asset_registry"),
            names.index("generate_scenario_models"),
        )
        self.assertLess(
            names.index("generate_scenario_models"),
            names.index("generate_flexibility_providers"),
        )
        self.assertLess(
            names.index("run_powerflow"), names.index("generate_dashboard_catalog")
        )
        self.assertEqual(names[-1], "generate_dashboard_catalog")
        self.assertEqual(
            command_by_name["generate_building_models"][:3],
            ["-m", "gridalyn.interfaces.cli.digital_twin", "building-models"],
        )
        self.assertEqual(
            command_by_name["generate_scenario_models"][:3],
            ["-m", "gridalyn.interfaces.cli.digital_twin", "scenario-models"],
        )
        self.assertEqual(
            command_by_name["generate_scenarios"][:3],
            ["-m", "gridalyn.interfaces.cli.digital_twin", "scenarios"],
        )
        self.assertEqual(
            command_by_name["generate_semantic_graph"][:3],
            ["-m", "gridalyn.interfaces.cli.semantic", "build"],
        )
        self.assertEqual(
            command_by_name["generate_dashboard_catalog"][:3],
            ["-m", "gridalyn.interfaces.cli.dashboard", "catalog"],
        )

    def test_skip_heavy_removes_powerflow_and_physics_sampling(self):
        steps = build_digital_twin_steps(skip_heavy=True, include_network_impact=True)
        names = [step["name"] for step in steps]

        self.assertNotIn("run_powerflow", names)
        self.assertNotIn("generate_network_impact_perturbation_samples", names)
        self.assertNotIn("generate_network_impact_verification_report", names)
        self.assertNotIn("generate_network_impact_physics_verification_report", names)
        self.assertNotIn("generate_locational_clearing_verification_report", names)
        self.assertIn("generate_network_impact_surrogate", names)
        self.assertIn("generate_locational_flexibility_clearing", names)
        self.assertLess(
            names.index("generate_network_impact_surrogate"),
            names.index("generate_locational_flexibility_clearing"),
        )
        self.assertIn("generate_dashboard_catalog", names)

    def test_orphaned_input_steps_are_retired(self):
        """The five orphan-blocked steps are gone from every build variant.

        Each invoked a command that reads
        ``flexibility/market_dispatch_timeseries.parquet`` with no argument,
        and no command in this repository writes that file -- it came from a
        study that was consolidated away. All five were ``optional=True``, so they
        failed on every network-impact build while the build still exited 0.
        Removing them is what makes that exit code mean something.
        """
        retired = [
            "generate_locational_clearing_verification_report",
            "generate_network_impact_perturbation_samples",
            "generate_network_impact_verification_report",
            "generate_network_impact_physics_verification_report",
            "generate_flexibility_clearing_scorecard",
        ]
        for skip_heavy in (False, True):
            steps = build_digital_twin_steps(
                skip_heavy=skip_heavy, include_network_impact=True
            )
            names = [step["name"] for step in steps]
            for name in retired:
                with self.subTest(skip_heavy=skip_heavy, step=name):
                    self.assertNotIn(name, names)

    def test_network_impact_build_defaults_to_digital_twin_artifacts(self):
        steps = build_digital_twin_steps(skip_heavy=False, include_network_impact=True)
        commands = {
            step["name"]: " ".join(step["command"])
            for step in steps
            if "network_impact" in step["name"] or "locational" in step["name"]
        }

        self.assertTrue(commands)
        self.assertFalse(
            any("projects/" in command for command in commands.values()),
            commands,
        )
        self.assertIn("generate_network_impact_surrogate", commands)
        self.assertIn("generate_locational_flexibility_clearing", commands)

    def test_dry_run_manifest_uses_portable_python_command(self):
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest = run_digital_twin_build(
                root=Path(tmpdir),
                skip_heavy=True,
                include_network_impact=False,
                dry_run=True,
                manifest_path=manifest_path,
            )

        self.assertTrue(manifest["dry_run"])
        self.assertTrue(
            all(result["command"][0] == "python" for result in manifest["results"])
        )

    def test_no_step_carries_optional_flag(self):
        """No build step may carry an ``optional`` failure-swallowing flag.

        The five orphan-blocked steps were removed on 2026-08-06 and the
        ``optional`` mechanism that let them fail silently must not resurface:
        a green exit on an incomplete build is impossible by construction.
        """
        from gridalyn.projects.workflows.digital_twin import build as build_module

        for include_network_impact in (False, True):
            steps = build_digital_twin_steps(
                skip_heavy=False, include_network_impact=include_network_impact
            )
            self.assertTrue(steps)
            self.assertTrue(all("name" in s and "command" in s for s in steps))
            for step in steps:
                with self.subTest(
                    include_network_impact=include_network_impact,
                    step=step["name"],
                ):
                    self.assertNotIn("optional", step)
        # The step factory must not accept an optional argument either.
        with self.assertRaises(TypeError):
            build_module._step("x", ["-m", "y"], optional=True)

    def test_failing_non_optional_step_raises_and_records_failed(self):
        """A failing non-optional step raises RuntimeError and the manifest records it."""
        from unittest import mock

        from gridalyn.projects.workflows.digital_twin import build as build_module

        fake = mock.Mock(returncode=1)
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            with mock.patch.object(build_module.subprocess, "run", return_value=fake):
                with self.assertRaises(RuntimeError) as ctx:
                    run_digital_twin_build(
                        root=Path(tmpdir),
                        skip_heavy=True,
                        include_network_impact=False,
                        manifest_path=manifest_path,
                    )
            self.assertIn("export_base", str(ctx.exception))
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["results"][0]["name"], "export_base")
            self.assertEqual(manifest["results"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()

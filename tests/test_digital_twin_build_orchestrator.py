import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gridalyn.workflows.digital_twin.build import build_digital_twin_steps, run_digital_twin_build


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
        self.assertLess(names.index("export_base"), names.index("generate_building_models"))
        self.assertLess(names.index("generate_building_models"), names.index("generate_scenarios"))
        self.assertLess(names.index("export_base"), names.index("generate_scenarios"))
        self.assertLess(names.index("generate_asset_registry"), names.index("generate_scenario_models"))
        self.assertLess(names.index("generate_scenario_models"), names.index("generate_flexibility_providers"))
        self.assertLess(names.index("run_powerflow"), names.index("generate_dashboard_catalog"))
        self.assertEqual(names[-1], "generate_dashboard_catalog")
        self.assertEqual(command_by_name["generate_building_models"][:3], ["-m", "gridalyn.interfaces.cli.digital_twin", "building-models"])
        self.assertEqual(command_by_name["generate_scenario_models"][:3], ["-m", "gridalyn.interfaces.cli.digital_twin", "scenario-models"])
        self.assertEqual(command_by_name["generate_scenarios"][:3], ["-m", "gridalyn.interfaces.cli.digital_twin", "scenarios"])
        self.assertEqual(command_by_name["generate_semantic_graph"][:3], ["-m", "gridalyn.interfaces.cli.semantic", "build"])
        self.assertEqual(command_by_name["generate_dashboard_catalog"][:3], ["-m", "gridalyn.interfaces.cli.dashboard", "catalog"])

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

    def test_include_network_impact_runs_locational_verification_after_clearing(self):
        steps = build_digital_twin_steps(skip_heavy=False, include_network_impact=True)
        names = [step["name"] for step in steps]
        command_by_name = {step["name"]: step["command"] for step in steps}

        self.assertIn("generate_locational_flexibility_clearing", names)
        self.assertIn("generate_locational_clearing_verification_report", names)
        self.assertLess(
            names.index("generate_locational_flexibility_clearing"),
            names.index("generate_locational_clearing_verification_report"),
        )
        self.assertEqual(
            command_by_name["generate_locational_clearing_verification_report"][:3],
            ["-m", "gridalyn.interfaces.cli.flexibility", "verify-clearing"],
        )

    def test_network_impact_build_defaults_to_digital_twin_artifacts(self):
        steps = build_digital_twin_steps(skip_heavy=False, include_network_impact=True)
        commands = {
            step["name"]: " ".join(step["command"])
            for step in steps
            if "network_impact" in step["name"] or "locational" in step["name"]
        }

        self.assertTrue(commands)
        self.assertFalse(
            any("projects/flexibility_cls" in command for command in commands.values()),
            commands,
        )
        self.assertIn(
            "digital_twin/flexibility/network_impact_physics_verification_report.json",
            commands["generate_network_impact_physics_verification_report"],
        )

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
        self.assertTrue(all(result["command"][0] == "python" for result in manifest["results"]))


if __name__ == "__main__":
    unittest.main()

import unittest
import tomllib
from pathlib import Path

from gridalyn.interfaces.cli import dashboard, digital_twin, flexibility, gridalyn as gridalyn_cli, platform, project, semantic


class CliCommandStructureTest(unittest.TestCase):
    def test_digital_twin_parser_exposes_build_command(self):
        parser = digital_twin.build_parser()
        args = parser.parse_args(["build", "--dry-run", "--skip-heavy"])

        self.assertEqual(args.command, "build")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.skip_heavy)

    def test_build_wrapper_imports_cli_main(self):
        import examples.compat.build_digital_twin as wrapper

        self.assertIs(wrapper.main, digital_twin.main)

    def test_build_wrapper_preserves_legacy_arguments(self):
        import examples.compat.build_digital_twin as wrapper

        self.assertEqual(
            wrapper.normalize_argv(["--dry-run", "--skip-heavy"]),
            ["build", "--dry-run", "--skip-heavy"],
        )
        self.assertEqual(
            wrapper.normalize_argv(["dashboard-catalog"]),
            ["dashboard-catalog"],
        )

    def test_compat_scripts_are_thin_wrappers(self):
        compat_dir = Path("examples/compat")
        oversized = []
        for path in sorted(compat_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            lines = path.read_text().splitlines()
            if len(lines) > 25:
                oversized.append(f"{path.as_posix()}:{len(lines)}")

        self.assertEqual([], oversized)

    def test_cli_script_handlers_do_not_depend_on_examples_compat(self):
        for module in [digital_twin, flexibility, semantic, dashboard, platform]:
            source = Path(module.__file__).read_text()
            self.assertNotIn("examples/compat", source)
            self.assertNotIn("run_path", source)

    def test_digital_twin_parser_exposes_artifact_commands(self):
        parser = digital_twin.build_parser()
        for command in [
            "base",
            "scenarios",
            "timeseries",
            "powerflow",
            "verify-scenarios",
            "verify-timeseries",
            "verify-powerflow",
            "asset-registry",
            "overload-report",
            "dashboard-catalog",
        ]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_digital_twin_parser_exposes_geojson_building_commands(self):
        parser = digital_twin.build_parser()
        commands = {
            "clip-buildings": [
                "--buildings-file",
                "buildings.geojson",
                "--polygon-file",
                "polygon.json",
                "--output-file",
                "out.geojson",
            ],
            "download-osm-buildings": [
                "--polygon-file",
                "polygon.json",
                "--output-file",
                "out.geojson",
            ],
            "prepare-microsoft-buildings": [
                "--input-file",
                "partition.geojsonl.gz",
                "--output-file",
                "out.geojson",
            ],
        }
        for command, extra in commands.items():
            args = parser.parse_args([command, *extra])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_flexibility_parser_exposes_operational_commands(self):
        parser = flexibility.build_parser()
        for command in [
            "providers",
            "surrogate",
            "locational-clearing",
            "verify-clearing",
            "perturbation-samples",
            "train-physics-surrogate",
            "verify-network-impact",
            "shadow-report",
            "scorecard",
            "network-impact-catalog",
        ]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_cli_parser_preserves_script_arguments(self):
        args, extra_args = flexibility.parse_args(["verify-clearing", "--scenario-id", "S4"])

        self.assertEqual(args.command, "verify-clearing")
        self.assertEqual(extra_args, ["--scenario-id", "S4"])

    def test_semantic_parser_exposes_build_and_validate(self):
        parser = semantic.build_parser()
        for command in ["build", "validate"]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_dashboard_parser_exposes_catalog_and_verify(self):
        parser = dashboard.build_parser()
        for command in ["catalog", "verify"]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_platform_parser_exposes_artifact_policy_check(self):
        parser = platform.build_parser()
        args = parser.parse_args(["check-artifacts", "--summary-only"])

        self.assertEqual(args.command, "check-artifacts")
        self.assertTrue(args.summary_only)
        self.assertTrue(callable(args.handler))

    def test_cli_modules_expose_main_functions(self):
        self.assertTrue(callable(gridalyn_cli.main))
        self.assertTrue(callable(digital_twin.main))
        self.assertTrue(callable(flexibility.main))
        self.assertTrue(callable(semantic.main))
        self.assertTrue(callable(dashboard.main))
        self.assertTrue(callable(platform.main))
        self.assertTrue(callable(project.main))

    def test_gridalyn_parser_exposes_product_domains_and_aliases(self):
        parser = gridalyn_cli.build_parser()
        for domain in [
            "validate",
            "twin",
            "dt",
            "model",
            "project",
            "projects",
            "market",
            "flex",
            "flexibility",
            "semantic",
            "semantics",
            "dashboard",
            "dash",
            "platform",
            "governance",
        ]:
            argv = [domain] if domain == "validate" else [domain, "status"]
            args, extra_args = gridalyn_cli.parse_args(argv)
            self.assertEqual(extra_args, [] if domain == "validate" else ["status"])
            self.assertTrue(callable(args.handler))

    def test_gridalyn_parser_exposes_same_product_domains(self):
        parser = gridalyn_cli.build_parser()
        args, extra_args = gridalyn_cli.parse_args(["project", "status"])

        self.assertEqual(parser.prog, "gridalyn")
        self.assertEqual(extra_args, ["status"])
        self.assertTrue(callable(args.handler))

    def test_gridalyn_routes_domain_arguments_to_existing_cli(self):
        called: list[list[str] | None] = []

        def fake_main(argv: list[str] | None = None) -> int:
            called.append(argv)
            return 0

        import types
        import sys

        fake_module = types.SimpleNamespace(main=fake_main)
        original_module = sys.modules.get("tests.fake_twin_cli")
        original_domain = gridalyn_cli.DOMAIN_MODULES["twin"]
        try:
            sys.modules["tests.fake_twin_cli"] = fake_module
            gridalyn_cli.DOMAIN_MODULES["twin"] = (
                "tests.fake_twin_cli",
                original_domain[1],
                original_domain[2],
            )
            result = gridalyn_cli.main(["twin", "build", "--dry-run"])
        finally:
            gridalyn_cli.DOMAIN_MODULES["twin"] = original_domain
            if original_module is None:
                sys.modules.pop("tests.fake_twin_cli", None)
            else:
                sys.modules["tests.fake_twin_cli"] = original_module

        self.assertEqual(result, 0)
        self.assertEqual(called, [["build", "--dry-run"]])

    def test_project_parser_exposes_init_validate_plan_run_status_and_regression(self):
        parser = project.build_parser()
        init_args = parser.parse_args(["init", "projects/example", "--template", "grid-study"])
        self.assertEqual(init_args.template, "grid-study")

        for command in ["init", "validate", "plan", "run", "status", "regression"]:
            args = parser.parse_args([command, "projects/example"])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_pyproject_exposes_only_gridalyn_entrypoints(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())

        self.assertEqual(
            pyproject["project"]["scripts"],
            {
                "gridalyn": "gridalyn.interfaces.cli.gridalyn:main",
                "gridalyn-dashboard": "gridalyn.interfaces.cli.dashboard:main",
                "gridalyn-dt": "gridalyn.interfaces.cli.digital_twin:main",
                "gridalyn-flex": "gridalyn.interfaces.cli.flexibility:main",
                "gridalyn-platform": "gridalyn.interfaces.cli.platform:main",
                "gridalyn-project": "gridalyn.interfaces.cli.project:main",
                "gridalyn-semantic": "gridalyn.interfaces.cli.semantic:main",
            },
        )
        removed_name = "synt" "grid"
        self.assertTrue(all(not name.startswith(removed_name) for name in pyproject["project"]["scripts"]))
        self.assertEqual(
            pyproject["tool"]["setuptools"]["packages"]["find"]["include"],
            ["gridalyn*"],
        )

    def test_public_cli_docs_do_not_advertise_removed_cli_name(self):
        text = Path("docs/reference/cli.md").read_text(encoding="utf-8")

        removed_name = "synt" "grid"
        self.assertNotIn(removed_name, text.lower())


if __name__ == "__main__":
    unittest.main()

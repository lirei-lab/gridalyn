import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from gridalyn.interfaces.cli import dashboard, digital_twin, flexibility
from gridalyn.interfaces.cli import gridalyn as gridalyn_cli
from gridalyn.interfaces.cli import platform, project, semantic
from gridalyn.interfaces.cli.environment import configure_cli_environment


class CliCommandStructureTest(unittest.TestCase):
    def test_digital_twin_parser_exposes_build_command(self):
        parser = digital_twin.build_parser()
        args = parser.parse_args(["build", "--dry-run", "--skip-heavy"])

        self.assertEqual(args.command, "build")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.skip_heavy)

    def test_examples_do_not_expose_compatibility_wrappers(self):
        self.assertFalse(Path("examples/compat").exists())

    def test_cli_script_handlers_do_not_depend_on_examples_compat(self):
        for module in [digital_twin, flexibility, semantic, dashboard, platform]:
            source = Path(module.__file__).read_text()
            self.assertNotIn("examples/compat", source)
            self.assertNotIn("interfaces.cli.compat", source)
            self.assertNotIn("run_path", source)

    def test_cli_environment_sets_writable_matplotlib_cache(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            configure_cli_environment()

            self.assertIn("MPLCONFIGDIR", __import__("os").environ)
            self.assertIn(
                "gridalyn-matplotlib", __import__("os").environ["MPLCONFIGDIR"]
            )

    def test_cli_environment_preserves_existing_matplotlib_cache(self):
        with mock.patch.dict(
            "os.environ", {"MPLCONFIGDIR": "/custom/cache"}, clear=True
        ):
            configure_cli_environment()

            self.assertEqual(__import__("os").environ["MPLCONFIGDIR"], "/custom/cache")

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
            "network-impact-catalog",
        ]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_flexibility_parser_does_not_expose_retired_commands(self):
        """The orphaned-input commands are gone, not hidden.

        All five read ``flexibility/market_dispatch_timeseries.parquet`` with
        no argument, and no command in this repository writes that file -- it
        came from a study that was consolidated away. They were removed on
        2026-08-06 rather than left to fail; a reinstated one must be able to
        name its producer.
        """
        parser = flexibility.build_parser()
        for command in [
            "verify-clearing",
            "perturbation-samples",
            "verify-network-impact",
            "shadow-report",
            "scorecard",
            "train-physics-surrogate",
        ]:
            with self.subTest(command=command):
                with self.assertRaises(SystemExit):
                    parser.parse_args([command])

    def test_cli_parser_preserves_script_arguments(self):
        args, extra_args = flexibility.parse_args(
            ["locational-clearing", "--scenario-id", "S4"]
        )

        self.assertEqual(args.command, "locational-clearing")
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
        self.assertEqual(args.root, ".")
        self.assertTrue(args.summary_only)
        self.assertTrue(callable(args.handler))

    def test_platform_artifact_check_discovers_workspace_from_subdirectory(self):
        parser = platform.build_parser()
        args = parser.parse_args(
            [
                "check-artifacts",
                "--root",
                "projects/minimal_grid_project",
                "--summary-only",
            ]
        )

        report = platform._artifact_policy_payload(args)

        self.assertTrue(report["valid"], report)
        self.assertEqual(
            "examples/tutorials/data/minimal", report["summary"]["minimal_dataset"]
        )

    def test_cli_modules_expose_main_functions(self):
        self.assertTrue(callable(gridalyn_cli.main))
        self.assertTrue(callable(digital_twin.main))
        self.assertTrue(callable(flexibility.main))
        self.assertTrue(callable(semantic.main))
        self.assertTrue(callable(dashboard.main))
        self.assertTrue(callable(platform.main))
        self.assertTrue(callable(project.main))

    def test_gridalyn_parser_exposes_product_domains_and_aliases(self):
        # Routing is asserted through parse_args below, so no parser handle is
        # needed here; test_gridalyn_parser_exposes_same_product_domains keeps
        # the one assertion that inspects the parser object itself.
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

    def test_gridalyn_domain_help_delegates_to_domain_parser(self):
        buffer = StringIO()

        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(buffer):
                gridalyn_cli.main(["project", "--help"])

        self.assertEqual(0, raised.exception.code)
        help_text = buffer.getvalue()
        self.assertIn("init", help_text)
        self.assertIn("run", help_text)
        self.assertIn("verify-all", help_text)

    def test_gridalyn_routes_domain_arguments_to_existing_cli(self):
        called: list[list[str] | None] = []

        def fake_main(argv: list[str] | None = None) -> int:
            called.append(argv)
            return 0

        import sys
        import types

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
        init_args = parser.parse_args(
            ["init", "projects/example", "--template", "grid-study"]
        )
        self.assertEqual(init_args.template, "grid-study")

        for command in [
            "init",
            "validate",
            "plan",
            "run",
            "status",
            "regression",
            "prepare-workspace",
        ]:
            args = parser.parse_args([command, "projects/example"])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

        for command in ["list", "verify-all"]:
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertTrue(callable(args.handler))

    def test_gridalyn_parser_exposes_doctor(self):
        args, extra_args = gridalyn_cli.parse_args(["doctor", "--root", "."])

        self.assertEqual(args.domain, "doctor")
        self.assertEqual(extra_args, [])
        self.assertTrue(callable(args.handler))

    def test_pyproject_splits_heavy_runtime_capabilities_into_extras(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())

        core_dependencies = "\n".join(pyproject["project"]["dependencies"])
        self.assertNotIn("osmnx", core_dependencies)
        self.assertNotIn("lightsim2grid", core_dependencies)
        self.assertNotIn("cvxpy", core_dependencies)

        optional = pyproject["project"]["optional-dependencies"]
        for extra in ["geo", "sim", "ops", "dashboard", "semantic", "all"]:
            self.assertIn(extra, optional)

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
        self.assertTrue(
            all(
                not name.startswith(removed_name)
                for name in pyproject["project"]["scripts"]
            )
        )
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

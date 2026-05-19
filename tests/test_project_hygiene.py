import inspect
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gridalyn.foundation.platform.artifacts import check_artifact_policy
from gridalyn.simulation.simulators.powerflow.runner import MonteCarloSimulationManager


class ProjectHygieneTest(unittest.TestCase):
    def test_monte_carlo_export_has_no_paper_data_default(self):
        signature = inspect.signature(MonteCarloSimulationManager.export_to_parquet)
        default = signature.parameters["out_dir"].default

        self.assertIsNone(default)

    def test_gridalyn_package_does_not_track_generated_artifacts(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "gridalyn"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        tracked_paths = [Path(path) for path in result.stdout.splitlines()]

        forbidden = []
        for path in tracked_paths:
            parts = set(path.parts)
            if "__pycache__" in parts or path.suffix == ".pyc":
                forbidden.append(path.as_posix())
            if {"cache", "outputs", "generated"} & parts:
                forbidden.append(path.as_posix())

        self.assertEqual([], forbidden)

    def test_gridalyn_source_tree_uses_seven_platform_modules(self):
        repo_root = Path(__file__).resolve().parents[1]
        allowed_directories = {
            "assets",
            "foundation",
            "interfaces",
            "operations",
            "projects",
            "simulation",
            "twin",
        }
        allowed_files = {"__init__.py", "api.py"}
        directories = {
            path.name
            for path in (repo_root / "gridalyn").iterdir()
            if path.is_dir() and path.name != "__pycache__"
        }
        files = {
            path.name
            for path in (repo_root / "gridalyn").iterdir()
            if path.is_file() and path.suffix == ".py"
        }

        self.assertEqual(allowed_directories, directories)
        self.assertLessEqual(files, allowed_files)

    def test_legacy_power_package_removed_from_source_and_imports(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        legacy_name = "geo" + "power"

        self.assertFalse((repo_root / legacy_name).exists())
        self.assertNotIn(f'"{legacy_name}*"', pyproject)
        self.assertIsNone(importlib.util.find_spec(legacy_name))

    def test_gridalyn_data_package_contains_only_discovery_code(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "gridalyn/foundation/data"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        tracked = sorted(result.stdout.splitlines())

        self.assertEqual(
            [
                "gridalyn/foundation/data/__init__.py",
                "gridalyn/foundation/data/datasets.py",
            ],
            tracked,
        )

    def test_datagen_weather_cache_defaults_to_generated_workspace(self):
        from gridalyn.datagen.data import weather

        repo_root = Path(__file__).resolve().parents[1]
        cache_path = weather._CACHE_FILE.relative_to(repo_root).as_posix()

        self.assertEqual(
            "examples/generated/cache/tmy_trois_rivieres.pkl",
            cache_path,
        )

    def test_datagen_weather_cache_accepts_gridalyn_env_alias(self):
        env = os.environ.copy()
        env["GRIDALYN_DATAGEN_CACHE_DIR"] = "projects/demo/outputs/cache"
        env.pop("GEOPOWER_DATAGEN_CACHE_DIR", None)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from gridalyn.datagen.data import weather; print(weather._CACHE_FILE.as_posix())",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertTrue(
            result.stdout.strip().endswith("projects/demo/outputs/cache/tmy_trois_rivieres.pkl")
        )

    def test_parametric_arx_generator_uses_gridalyn_model_weights(self):
        from gridalyn.simulation.simulators.agents.unmanaged_loads import ParametricArxGenerator

        generator = ParametricArxGenerator()

        self.assertEqual("gridalyn/assets/datagen/models/weights", generator.model_dir)
        self.assertTrue(Path(generator.heat_model_path).exists())
        self.assertTrue(Path(generator.bg_model_path).exists())

    def test_gridalyn_does_not_import_legacy_ev_runtime_modules(self):
        repo_root = Path(__file__).resolve().parents[1]
        legacy_token = "ev" "case"
        offenders = []
        allowed = set()
        for path in sorted((repo_root / "gridalyn").rglob("*.py")):
            if path in allowed:
                continue
            text = path.read_text()
            if f"from {legacy_token}." in text or f"import {legacy_token}." in text:
                offenders.append(str(path.relative_to(repo_root)))
        self.assertEqual(offenders, [])

    def test_new_platform_docs_do_not_frame_legacy_ev_runtime_as_core(self):
        repo_root = Path(__file__).resolve().parents[1]
        platform_docs = [
            repo_root / "README.md",
            repo_root / "docs" / "index.md",
            repo_root / "docs" / "platform" / "architecture.md",
            repo_root / "docs" / "platform" / "digital-twin.md",
            repo_root / "docs" / "platform" / "utility-platform-roadmap.md",
            repo_root / "docs" / "platform" / "release-readiness.md",
        ]
        offenders = []
        for path in platform_docs:
            if not path.exists():
                continue
            text = path.read_text().lower()
            legacy_token = "ev" "case"
            forbidden_phrases = [
                f"{legacy_token} is the platform",
                f"{legacy_token} core",
                "manuscripts/</code>",
                "manuscripts should",
                "dashboard and manuscripts",
            ]
            if any(phrase in text for phrase in forbidden_phrases):
                offenders.append(str(path.relative_to(repo_root)))
        self.assertEqual(offenders, [])

    def test_public_readme_uses_current_platform_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README.md").read_text(encoding="utf-8")

        required = [
            "# Gridalyn",
            "utility digital-twin",
            "uv run gridalyn --help",
            "uv run gridalyn project run projects/flexibility_cls",
            "uv run gridalyn validate",
        ]
        missing = [phrase for phrase in required if phrase not in readme]

        forbidden = [
            "PowerGridGraph",
            "support@gridalyn.org",
            "Python 3.10",
        ]
        stale = [phrase for phrase in forbidden if phrase in readme]

        self.assertEqual([], missing)
        self.assertEqual([], stale)

    def test_public_source_and_docs_do_not_reference_removed_cli_name(self):
        repo_root = Path(__file__).resolve().parents[1]
        removed_name = "synt" "grid"
        checked_roots = [
            repo_root / "README.md",
            repo_root / "pyproject.toml",
            repo_root / "docs",
            repo_root / "gridalyn",
            repo_root / "projects",
            repo_root / "examples",
        ]
        allowed_parts = {
            ("docs", "superpowers"),
        }
        offenders: list[str] = []

        for root in checked_roots:
            paths = [root] if root.is_file() else sorted(root.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                relative = path.relative_to(repo_root)
                if any(relative.parts[: len(parts)] == parts for parts in allowed_parts):
                    continue
                if "outputs" in relative.parts or "__pycache__" in relative.parts:
                    continue
                if path.suffix in {".pyc", ".parquet", ".pkl", ".npy", ".npz", ".png", ".jpg", ".pdf"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                if removed_name in text:
                    offenders.append(relative.as_posix())

        self.assertEqual([], offenders)

    def test_public_docs_nav_excludes_manuscript_workspace(self):
        repo_root = Path(__file__).resolve().parents[1]
        mkdocs = (repo_root / "docs" / "mkdocs.yml").read_text(encoding="utf-8")

        self.assertIn("Release Readiness: platform/release-readiness.md", mkdocs)
        self.assertIn("Architecture Map: platform/capability-architecture.md", mkdocs)
        self.assertNotIn("Manuscripts:", mkdocs)
        self.assertNotIn("workflows/manuscripts.md", mkdocs)

    def test_public_docs_expose_clear_reproduction_and_development_path(self):
        repo_root = Path(__file__).resolve().parents[1]
        mkdocs = (repo_root / "docs" / "mkdocs.yml").read_text(encoding="utf-8")
        index = (repo_root / "docs" / "index.md").read_text(encoding="utf-8")
        reproducibility = repo_root / "docs" / "getting-started" / "reproducibility.md"

        required_nav = [
            "Documentation Map: getting-started/documentation-map.md",
            "Reproducibility Checklist: getting-started/reproducibility.md",
            "Start:",
            "Platform:",
            "SDK:",
            "Operations:",
            "Projects:",
            "Reference:",
        ]
        missing_nav = [item for item in required_nav if item not in mkdocs]

        required_index_terms = [
            "Choose A Path",
            "Quickstart",
            "Build With The SDK",
            "Explore Demos",
        ]
        missing_index_terms = [item for item in required_index_terms if item not in index]

        self.assertEqual([], missing_nav)
        self.assertEqual([], missing_index_terms)
        self.assertTrue(reproducibility.exists())

    def test_gridalyn_package_does_not_depend_on_projects(self):
        repo_root = Path(__file__).resolve().parents[1]
        package_root = repo_root / "gridalyn"
        violations: list[str] = []

        for path in sorted(package_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "projects/flexibility_cls" in text or (
                '"projects"' in text and '"flexibility_cls"' in text
            ):
                violations.append(f"{path.relative_to(repo_root)} references projects/flexibility_cls")
            if "from projects." in text or "import projects." in text:
                violations.append(f"{path.relative_to(repo_root)} imports from projects")
            if "sys.path.insert" in text:
                violations.append(f"{path.relative_to(repo_root)} mutates sys.path")

        self.assertEqual([], violations)

    def test_capability_architecture_names_utility_layers(self):
        repo_root = Path(__file__).resolve().parents[1]
        path = repo_root / "docs" / "platform" / "capability-architecture.md"
        text = path.read_text(encoding="utf-8")

        required_layers = [
            "Foundation And Governance",
            "Digital Twin Core",
            "Asset And Flexibility Modeling",
            "Simulation And Validation",
            "Flexibility Market And Operations",
            "Problems And Experiments",
            "Applications And Interfaces",
        ]
        missing = [layer for layer in required_layers if layer not in text]

        self.assertEqual([], missing)

    def test_gitignore_covers_generated_artifact_roots(self):
        repo_root = Path(__file__).resolve().parents[1]
        gitignore = (repo_root / ".gitignore").read_text()
        required_patterns = [
            "_build/",
            "/site",
            "cache/",
            ".roo/",
            ".agents/",
            ".codex/",
            ".claude/",
            ".cursor/",
            ".windsurf/",
            "manuscripts/",
            "examples/generated/outputs/",
            "examples/generated/cache/",
            "projects/*/outputs/",
            "dashboard/public/",
            "instances/*/digital_twin/**/*.parquet",
            "instances/*/digital_twin/timeseries/",
            "manuscripts/**/*.aux",
            "manuscripts/**/*.fdb_latexmk",
            "manuscripts/**/*.synctex.gz",
            "manuscripts/**/*.pdf",
        ]

        missing = [pattern for pattern in required_patterns if pattern not in gitignore]

        self.assertEqual([], missing)

    def test_root_digital_twin_alias_is_not_tracked(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "digital_twin"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertEqual("", result.stdout.strip())

    def test_ai_agent_state_is_not_tracked(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", ".roo", ".agents", ".codex", ".claude", ".cursor", ".windsurf"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertEqual("", result.stdout.strip())

    def test_compiled_docs_and_root_cache_are_not_tracked(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "_build", "site", "cache", "manuscripts"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]

        self.assertEqual([], tracked)

    def test_reusable_configs_live_outside_examples(self):
        repo_root = Path(__file__).resolve().parents[1]
        required_configs = [
            "configs/grid/config.json",
            "configs/grid/powergrid_config.json",
            "configs/geography/tr01.json",
        ]

        missing = [path for path in required_configs if not (repo_root / path).exists()]
        self.assertEqual([], missing)

        for path in required_configs:
            json.loads((repo_root / path).read_text(encoding="utf-8"))

    def test_examples_tree_does_not_own_generated_or_platform_config_files(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "examples"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        tracked_paths = [
            Path(path)
            for path in result.stdout.splitlines()
            if (repo_root / path).exists()
        ]

        forbidden = []
        for path in tracked_paths:
            parts = set(path.parts)
            if "__pycache__" in parts or path.suffix == ".pyc":
                forbidden.append(path.as_posix())
            if "grid_configs" in parts or "geo_configs" in parts:
                forbidden.append(path.as_posix())
            if path.parts[:3] in {
                ("examples", "generated", "cache"),
                ("examples", "generated", "outputs"),
            }:
                forbidden.append(path.as_posix())

        self.assertEqual([], forbidden)

    def test_public_examples_do_not_track_legacy_archive_or_large_duplicate_inputs(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "ls-files", "examples"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        tracked = set(result.stdout.splitlines())

        forbidden = [
            path
            for path in sorted(tracked)
            if path.startswith("examples/legacy/")
            or path
            in {
                "examples/tutorials/data/buildings.json",
                "examples/tutorials/data/buildings_tr.json",
                "examples/tutorials/data/simulation_results.h5",
            }
        ]

        self.assertEqual([], forbidden)

    def test_project_runtime_does_not_depend_on_examples_generated_cache(self):
        repo_root = Path(__file__).resolve().parents[1]
        scanned_roots = [
            repo_root / "projects" / "flexibility_cls",
            repo_root / "gridalyn" / "workflows",
        ]
        offenders = []
        for root in scanned_roots:
            for path in sorted(root.rglob("*.py")):
                text = path.read_text(encoding="utf-8")
                if "examples/generated/outputs" in text:
                    offenders.append(path.relative_to(repo_root).as_posix())

        self.assertEqual([], offenders)

    def test_project_runtime_does_not_depend_on_legacy_ev_runtime(self):
        repo_root = Path(__file__).resolve().parents[1]
        legacy_token = "ev" "case"
        offenders = []
        for path in sorted((repo_root / "projects" / "flexibility_cls").rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml", ".md", ".sh"}:
                continue
            text = path.read_text(encoding="utf-8")
            if f"from {legacy_token}." in text or f"import {legacy_token}." in text or f"{legacy_token}/" in text:
                offenders.append(path.relative_to(repo_root).as_posix())

        self.assertEqual([], offenders)

    def test_dashboard_does_not_depend_on_legacy_ev_runtime_static_paths(self):
        repo_root = Path(__file__).resolve().parents[1]
        legacy_token = "ev" "case"
        offenders = []
        for path in sorted((repo_root / "dashboard").rglob("*")):
            if "dist" in path.relative_to(repo_root / "dashboard").parts:
                continue
            if not path.is_file() or path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".yml", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8")
            if f"/{legacy_token}" in text or f"{legacy_token}/outputs" in text:
                offenders.append(path.relative_to(repo_root).as_posix())

        self.assertEqual([], offenders)

    def test_minimal_tutorial_dataset_stays_small(self):
        repo_root = Path(__file__).resolve().parents[1]
        minimal_dir = repo_root / "examples" / "tutorials" / "data" / "minimal"
        if not minimal_dir.exists():
            self.skipTest("minimal tutorial dataset has not been created yet")

        total_bytes = sum(
            path.stat().st_size
            for path in minimal_dir.rglob("*")
            if path.is_file()
        )

        self.assertLessEqual(total_bytes, 10 * 1024 * 1024)

    def test_minimal_tutorial_dataset_has_expected_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        minimal_dir = repo_root / "examples" / "tutorials" / "data" / "minimal"
        required_files = {
            "manifest.json",
            "grid_nodes.geojson",
            "grid_edges.geojson",
            "buildings.geojson",
            "scenarios.json",
            "expected_summary.json",
        }

        missing = [name for name in sorted(required_files) if not (minimal_dir / name).exists()]
        self.assertEqual([], missing)

        for name in required_files:
            json.loads((minimal_dir / name).read_text(encoding="utf-8"))

        summary = json.loads((minimal_dir / "expected_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(3, summary["node_count"])
        self.assertEqual(2, summary["edge_count"])
        self.assertEqual(3, summary["building_count"])
        self.assertEqual(2, summary["scenario_count"])

    def test_artifact_policy_accepts_clean_tracked_file_list(self):
        repo_root = Path(__file__).resolve().parents[1]
        report = check_artifact_policy(
            repo_root,
            tracked_files=[
                ".gitignore",
                "README.md",
                "examples/tutorials/data/minimal/manifest.json",
            ],
        )

        self.assertTrue(report.valid, report.errors)

    def test_artifact_policy_tolerates_source_archive_without_real_git_index(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "examples" / "tutorials" / "data" / "minimal").mkdir(parents=True)
            for filename in (
                "manifest.json",
                "grid_nodes.geojson",
                "grid_edges.geojson",
                "buildings.geojson",
                "scenarios.json",
                "expected_summary.json",
            ):
                (root / "examples" / "tutorials" / "data" / "minimal" / filename).write_text(
                    "{}",
                    encoding="utf-8",
                )
            (root / "examples" / "tutorials" / "data" / "minimal" / "manifest.json").write_text(
                json.dumps(
                    {
                        "dataset_id": "gridalyn_minimal_radial_demo",
                        "files": [
                            {"path": "grid_nodes.geojson"},
                            {"path": "grid_edges.geojson"},
                            {"path": "buildings.geojson"},
                            {"path": "scenarios.json"},
                            {"path": "expected_summary.json"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / ".gitignore").write_text((repo_root / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")

            report = check_artifact_policy(root)

            self.assertTrue(report.valid, report.errors)

    def test_base_dependencies_exclude_dev_docs_and_git_sources(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        base_dependencies = pyproject.split("[project.optional-dependencies]", maxsplit=1)[0]

        forbidden = [
            "git+https://",
            "pytest",
            "pre-commit",
            "mkdocs",
            "mkdocstrings",
            "jupyterlab",
        ]
        offenders = [dependency for dependency in forbidden if dependency in base_dependencies]

        self.assertEqual([], offenders)

    def test_artifact_policy_rejects_generated_tracked_artifacts(self):
        repo_root = Path(__file__).resolve().parents[1]
        report = check_artifact_policy(
            repo_root,
            tracked_files=[
                "README.md",
                "_build/index.html",
                "site/index.html",
                "cache/raw_response.json",
                "manuscripts/ev_capacity_limitation/paper/index.tex",
                "examples/generated/outputs/pg_graph_cache.pkl",
                "examples/generated/outputs/power_grid_map.html",
                "examples/generated/cache/tmy_trois_rivieres.pkl",
                "examples/generated/cache/raw_response.json",
                "projects/flexibility_cls/outputs/reports/study_run_manifest.json",
                "instances/default/digital_twin/timeseries/S4_ev_load.parquet",
                "manuscripts/ev_capacity_limitation/paper/main.pdf",
            ],
        )

        self.assertFalse(report.valid)
        self.assertEqual(11, report.summary["forbidden_tracked_files"])

    def test_production_defaults_use_artifact_layout_for_default_twin_paths(self):
        repo_root = Path(__file__).resolve().parents[1]
        roots = [
            repo_root / "gridalyn",
            repo_root / "projects" / "flexibility_cls" / "scripts",
        ]
        forbidden_snippets = [
            'ROOT / "instances" / "default" / "digital_twin"',
            'root / "instances" / "default" / "digital_twin"',
            'Path("instances/default/digital_twin',
        ]
        offenders: list[str] = []
        for root in roots:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                for snippet in forbidden_snippets:
                    if snippet in text:
                        offenders.append(
                            f"{path.relative_to(repo_root).as_posix()}: {snippet}"
                        )

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()

import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path

from projects.flexibility_cls.scripts.pipeline.prepare_topology_cache import (
    prepare_topology_cache,
)

from gridalyn.foundation import ReportMetadata, validate_workspace, write_report
from gridalyn.projects import (
    init_project,
    load_project as public_load_project,
    plan_project,
    prepare_project_workspace,
    project_regression,
    project_status,
    project_verify,
    run_workflow,
    validate_project,
)
from gridalyn.projects.loader import load_project
from gridalyn.projects.outputs import DEFAULT_OUTPUT_DIRECTORIES
from gridalyn.projects.runner import plan_stages, run_project
from gridalyn.projects.validation import validate_project_file


class ProjectWorkflowSchemaTest(unittest.TestCase):
    def test_rejects_wrong_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.yaml"
            project.write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: SomethingElse
metadata:
  name: bad_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test project contract.
    model:
      type: workflow_model
      name: test_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  workflow:
    file: workflow.yaml
  inputs: {}
  artifacts: {}
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(project)

            self.assertFalse(report.valid)
            self.assertTrue(any("kind" in error for error in report.errors))

    def test_rejects_project_without_problem_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: missing_problem
  version: 0.1.0
spec:
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(root / "project.yaml")

            self.assertFalse(report.valid)
            self.assertIn("'problem' is a required property", "\n".join(report.errors))

    def test_rejects_experiment_with_unknown_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: unknown_scenario
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test unknown scenario references.
    model:
      type: workflow_model
      name: sample_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  experiments:
    - id: broken_run
      scenario: missing
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(root / "project.yaml")

            self.assertFalse(report.valid)
            self.assertIn(
                "experiment broken_run references unknown scenario missing",
                "\n".join(report.errors),
            )

    def test_accepts_problem_contract_without_explicit_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: no_spaces_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test project contract without explicit spaces.
    model:
      type: simulation_model
      name: sample_simulation
    scenarios:
      - id: baseline
        role: test_baseline
  experiments:
    - id: baseline_run
      scenario: baseline
      model: sample_simulation
      artifacts:
        - outputs/reports/project_summary.json
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(root / "project.yaml")
            project = load_project(root / "project.yaml")

            self.assertTrue(report.valid, report.errors)
            self.assertEqual(project.experiments[0].model, "sample_simulation")
            self.assertEqual(
                project.experiments[0].artifacts,
                ("outputs/reports/project_summary.json",),
            )

    def test_rejects_unknown_problem_model_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: unknown_model_kind
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test model type vocabulary.
    model:
      type: kitchen_sink
      name: sample_model
    scenarios:
      - id: baseline
        role: test_baseline
  experiments:
    - id: baseline_run
      scenario: baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(root / "project.yaml")

            self.assertFalse(report.valid)
            self.assertIn("kitchen_sink", "\n".join(report.errors))


class ProjectWorkflowLoaderTest(unittest.TestCase):
    def test_loads_valid_project_and_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
      outputs:
        - outputs/build.json
    - id: validate
      needs: [build]
      command: echo validate
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: sample_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test project contract.
    model:
      type: workflow_model
      name: sample_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  experiments:
    - id: baseline_run
      scenario: baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation:
    requiredReports: []
    requiredFigures: []
""".strip(),
                encoding="utf-8",
            )

            project = load_project(root / "project.yaml")

            self.assertEqual(project.name, "sample_project")
            self.assertEqual(project.problem.type, "test_problem")
            self.assertEqual(project.problem.scenarios[0].id, "baseline")
            self.assertEqual(project.experiments[0].scenario, "baseline")
            self.assertEqual(
                [stage.id for stage in project.workflow.stages],
                ["build", "validate"],
            )

    def test_prepare_project_workspace_creates_standard_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            report = prepare_project_workspace(root)

            self.assertEqual(root, report.root)
            self.assertEqual(DEFAULT_OUTPUT_DIRECTORIES, report.created_directories)
            for relative in DEFAULT_OUTPUT_DIRECTORIES:
                self.assertTrue((root / relative).is_dir(), relative)

    def test_prepare_workspace_cli_runs_from_project_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gridalyn.interfaces.cli.project",
                    "prepare-workspace",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(str(root), payload["root"])
            self.assertIn("outputs/cache", payload["created_directories"])
            self.assertTrue((root / "outputs" / "reports").is_dir())

    def test_repo_path_base_resolves_from_source_archive_without_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            project_root = workspace / "projects" / "archive_case"
            project_root.mkdir(parents=True)
            (workspace / "gridalyn").mkdir()
            (workspace / "pyproject.toml").write_text(
                "[project]\nname = \"gridalyn\"\n",
                encoding="utf-8",
            )
            (project_root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: archive_case_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (project_root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: archive_case
  version: 0.1.0
spec:
  pathBase: repo
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test repository-relative project contract.
    model:
      type: workflow_model
      name: archive_case_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: projects/archive_case/workflow.yaml
  validation:
    requiredReports: []
    requiredFigures: []
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(project_root / "project.yaml")
            project = load_project(project_root / "project.yaml")

            self.assertTrue(report.valid, "\n".join(report.errors))
            self.assertEqual(workspace.resolve(), project.base_dir)
            self.assertEqual(project_root / "workflow.yaml", project.workflow.path)

    def test_reports_unresolved_stage_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: broken_workflow
spec:
  stages:
    - id: validate
      needs: [missing_stage]
      command: echo validate
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: broken_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test unresolved dependency validation.
    model:
      type: workflow_model
      name: broken_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(root / "project.yaml")

            self.assertFalse(report.valid)
            self.assertIn("missing_stage", "\n".join(report.errors))

    def test_project_verify_reports_missing_outputs_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: minimal_grid_project_workflow
spec:
  stages:
    - id: run_minimal_powerflow
      command: python scripts/run_minimal_powerflow.py
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: minimal_grid_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test missing output reporting.
    model:
      type: workflow_model
      name: minimal_grid_project_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation:
    requiredReports:
      - outputs/reports/minimal_grid_report.json
    requiredFigures:
      - outputs/figures/minimal_voltage_profile.png
""".strip(),
                encoding="utf-8",
            )

            report = project_verify(root, write=False)

            self.assertFalse(report["valid"])
            self.assertFalse(report["sense_check"]["valid"])
            self.assertIn("missing_objective_artifact", report["sense_check"]["errors"])


class ProjectWorkflowRunnerTest(unittest.TestCase):
    def test_plan_orders_dependencies_before_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: validate
      needs: [build]
      command: echo validate
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: sample_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test stage planning.
    model:
      type: workflow_model
      name: sample_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )

            project = load_project(root / "project.yaml")
            ordered = plan_stages(project)

            self.assertEqual([stage.id for stage in ordered], ["build", "validate"])

    def test_dry_run_writes_execution_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
    - id: validate
      needs: [build]
      command: echo validate
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: sample_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test dry-run manifest writing.
    model:
      type: workflow_model
      name: sample_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip(),
                encoding="utf-8",
            )
            manifest_path = root / "outputs" / "manifests" / "project_run_manifest.json"

            project = load_project(root / "project.yaml")
            executed = run_project(
                project,
                dry_run=True,
                manifest_path=manifest_path,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(executed, ["build", "validate"])
            self.assertTrue(manifest["dry_run"])
            self.assertEqual(manifest["project"]["name"], "sample_project")
            self.assertTrue(manifest["study_run"]["run_id"].startswith("run:sample_project:"))
            self.assertEqual(manifest["study_run"]["project_id"], "sample_project")
            self.assertEqual(manifest["study_run"]["project_version"], "0.1.0")
            self.assertEqual(manifest["study_run"]["workflow_id"], "sample_workflow")
            self.assertEqual(manifest["study_run"]["status"], "planned")
            self.assertEqual(manifest["study_run"]["stage_count"], 2)
            self.assertEqual(manifest["study_run"]["completed_stage_count"], 0)
            self.assertEqual(manifest["study_run"]["planned_stage_count"], 2)
            self.assertEqual(
                [stage["id"] for stage in manifest["stages"]],
                ["build", "validate"],
            )
            self.assertEqual(
                [stage["status"] for stage in manifest["stages"]],
                ["planned", "planned"],
            )


class ProjectApiTest(unittest.TestCase):
    def test_public_project_api_loads_validates_and_plans_project(self) -> None:
        project = public_load_project(Path("projects/flexibility_cls"))
        report = validate_project(project.path)
        stages = plan_project(project)

        self.assertEqual(project.name, "flexibility_cls")
        self.assertTrue(report.valid, "\n".join(report.errors))
        self.assertGreater(len(stages), 10)

    def test_public_projects_declare_problem_and_experiment_contracts(self) -> None:
        for project_path in sorted(Path("projects").glob("*/project.yaml")):
            with self.subTest(project=project_path):
                project = load_project(project_path)
                scenario_ids = {scenario.id for scenario in project.problem.scenarios}
                experiment_refs = {
                    ref
                    for experiment in project.experiments
                    for ref in ([experiment.scenario] if experiment.scenario else [])
                    + list(experiment.scenarios)
                }

                self.assertTrue(project.problem.objective)
                self.assertGreaterEqual(len(project.problem.scenarios), 1)
                self.assertGreaterEqual(len(project.experiments), 1)
                self.assertTrue(experiment_refs.issubset(scenario_ids))

    def test_init_project_creates_valid_study_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_case"

            created = init_project(target, name="my_case")
            status = project_status(target)
            report = validate_project(created.project_file)

            self.assertEqual(created.root, target)
            self.assertTrue((target / "project.yaml").exists())
            self.assertTrue((target / "workflow.yaml").exists())
            self.assertTrue((target / "inputs").is_dir())
            self.assertTrue((target / "outputs").is_dir())
            self.assertEqual(status["name"], "my_case")
            self.assertEqual(status["stage_count"], 2)
            self.assertTrue(report.valid, "\n".join(report.errors))

    def test_project_status_reports_expected_and_found_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_case"
            created = init_project(target, name="my_case")
            project_text = created.project_file.read_text(encoding="utf-8")
            created.project_file.write_text(
                project_text.replace(
                    "requiredReports: []",
                    "requiredReports:\n      - outputs/reports/sample_report.json",
                ),
                encoding="utf-8",
            )
            report_path = target / "outputs" / "reports" / "sample_report.json"
            write_report(
                report_path,
                metadata=ReportMetadata(
                    report_id="sample_report",
                    source_domain="my_case",
                ),
            )

            status = project_status(target, check_artifacts=True)

            self.assertEqual(status["reports"]["expected_count"], 1)
            self.assertEqual(status["reports"]["found_count"], 1)
            self.assertEqual(status["reports"]["invalid_count"], 0)
            self.assertTrue(status["reports"]["ready"])

    def test_project_status_marks_invalid_report_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_case"
            created = init_project(target, name="my_case")
            project_text = created.project_file.read_text(encoding="utf-8")
            created.project_file.write_text(
                project_text.replace(
                    "requiredReports: []",
                    "requiredReports:\n      - outputs/reports/broken_report.json",
                ),
                encoding="utf-8",
            )
            report_path = target / "outputs" / "reports" / "broken_report.json"
            report_path.write_text('{"report_id": "broken_report"}\n', encoding="utf-8")

            status = project_status(target, check_artifacts=True)

            self.assertEqual(status["reports"]["expected_count"], 1)
            self.assertEqual(status["reports"]["found_count"], 1)
            self.assertEqual(status["reports"]["invalid_count"], 1)
            self.assertFalse(status["reports"]["ready"])

    def test_init_project_grid_study_template_runs_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "hosting_case"

            init_project(target, name="Hosting Case", template="grid-study")
            executed = run_workflow(target)
            status = project_status(target, check_artifacts=True)

            self.assertEqual(executed, ["prepare_workspace", "write_summary_report"])
            self.assertTrue((target / "scripts" / "write_summary_report.py").exists())
            self.assertTrue((target / "outputs" / "operations").is_dir())
            self.assertTrue((target / "outputs" / "reports" / "project_summary.json").exists())
            self.assertTrue(status["valid"], status)
            self.assertTrue(status["reports"]["ready"], status["reports"])

    def test_workspace_validation_combines_artifact_and_project_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(
                "\n".join(
                    [
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
                        "instances/default/digital_twin/**/*.parquet",
                        "instances/default/digital_twin/timeseries/",
                        "instances/*/digital_twin/**/*.parquet",
                        "instances/*/digital_twin/timeseries/",
                        "manuscripts/**/*.aux",
                        "manuscripts/**/*.fdb_latexmk",
                        "manuscripts/**/*.synctex.gz",
                        "manuscripts/**/*.pdf",
                    ]
                ),
                encoding="utf-8",
            )
            minimal = root / "examples" / "tutorials" / "data" / "minimal"
            minimal.mkdir(parents=True)
            for filename in [
                "grid_nodes.geojson",
                "grid_edges.geojson",
                "buildings.geojson",
                "scenarios.json",
                "expected_summary.json",
            ]:
                (minimal / filename).write_text("{}\n", encoding="utf-8")
            (minimal / "manifest.json").write_text(
                json.dumps(
                    {
                        "dataset_id": "demo",
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
            init_project(root / "projects" / "demo_case", name="demo_case")

            report = validate_workspace(
                root,
                projects=["projects/demo_case"],
                check_project_artifacts=True,
            )

            self.assertTrue(report["valid"], report)
            self.assertEqual(report["summary"]["check_count"], 2)
            self.assertEqual(
                [check["id"] for check in report["checks"]],
                ["artifact_policy", "project:projects/demo_case"],
            )


class ProjectArtifactValidationTest(unittest.TestCase):
    def test_missing_required_report_is_an_error_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workflow.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
""".strip(),
                encoding="utf-8",
            )
            (root / "project.yaml").write_text(
                """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: sample_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Test missing required report validation.
    model:
      type: workflow_model
      name: sample_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation:
    requiredReports:
      - outputs/reports/missing.json
""".strip(),
                encoding="utf-8",
            )

            report = validate_project_file(
                root / "project.yaml",
                check_artifacts=True,
            )

            self.assertFalse(report.valid)
            self.assertIn("missing required report", "\n".join(report.errors))


class EVCapacityLimitationProjectTest(unittest.TestCase):
    def test_flexibility_cls_project_contract_is_valid(self) -> None:
        report = validate_project_file(
            Path("projects/flexibility_cls/project.yaml")
        )

        self.assertTrue(report.valid, "\n".join(report.errors))

    def test_flexibility_cls_declares_building_footprint_contract(self) -> None:
        project = load_project(Path("projects/flexibility_cls/project.yaml"))
        footprints = project.raw["spec"]["inputs"].get("buildingFootprints", {})

        self.assertEqual(
            "examples/tutorials/data/buildings_inside_polygon.geojson",
            footprints.get("source"),
        )
        self.assertEqual("GeoJSON FeatureCollection", footprints.get("format"))
        self.assertIn("osm", footprints.get("replacement", {}))
        self.assertIn("microsoft", footprints.get("replacement", {}))
        self.assertIn("topologyStage", footprints.get("replacement", {}))

    def test_flexibility_cls_workflow_exposes_pipeline_stages(self) -> None:
        project = load_project(Path("projects/flexibility_cls/project.yaml"))
        stage_ids = [stage.id for stage in plan_stages(project)]

        self.assertIn("prepare_topology_cache", stage_ids)
        self.assertIn("generate_stochastic_profiles", stage_ids)
        self.assertIn("congestion_forecast", stage_ids)
        self.assertIn("market_allocation", stage_ids)
        self.assertIn("plot_stage_2_grid_exceedance", stage_ids)
        self.assertIn("pandapower_validation", stage_ids)
        self.assertIn("validate_study_outputs", stage_ids)
        self.assertIn("materialize_operational_artifacts", stage_ids)
        self.assertIn("build_study_reports", stage_ids)
        self.assertGreater(len(stage_ids), 10)

    def test_topology_cache_manifest_records_footprint_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"

            manifest_path = prepare_topology_cache(
                cache_dir=cache_dir,
                force_rebuild=True,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validation_path = cache_dir / "building_footprint_validation_report.json"
            validation_report = json.loads(validation_path.read_text(encoding="utf-8"))

            self.assertEqual("synthetic_topology_cache", manifest["artifact_type"])
            self.assertIn("building_footprints", manifest)
            self.assertIn("sha256", manifest["building_footprints"])
            self.assertEqual(
                "building_footprint_validation_report.json",
                Path(manifest["building_footprints"]["validation_report"]).name,
            )
            self.assertGreater(manifest["building_footprints"]["feature_count"], 0)
            self.assertTrue(validation_report["valid"])
            self.assertEqual(
                manifest["building_footprints"]["sha256"],
                validation_report["source"]["sha256"],
            )

    def test_flexibility_cls_workflow_keeps_only_case_analysis_plots(self) -> None:
        project = load_project(Path("projects/flexibility_cls/project.yaml"))
        stage_ids = [stage.id for stage in plan_stages(project)]

        self.assertFalse(
            any(stage_id.startswith("plot_concept_") for stage_id in stage_ids),
            stage_ids,
        )
        self.assertFalse(
            any(stage_id.startswith("plot_model_") for stage_id in stage_ids),
            stage_ids,
        )
        self.assertIn("plot_stage_1_stacked_ev", stage_ids)
        self.assertIn("plot_stage_2_grid_exceedance", stage_ids)
        self.assertIn("plot_stage_3_day_ahead", stage_ids)
        self.assertIn("plot_stage_4_realization", stage_ids)
        self.assertIn("plot_stage_5_settlement", stage_ids)

    def test_flexibility_cls_public_outputs_are_study_local(self) -> None:
        project = load_project(Path("projects/flexibility_cls/project.yaml"))
        stage_outputs = [
            output for stage in project.workflow.stages for output in stage.outputs
        ]
        validation_paths = (
            project.raw["spec"].get("validation", {}).get("requiredReports", [])
            + project.raw["spec"].get("validation", {}).get("requiredFigures", [])
        )
        project_artifacts = project.raw["spec"]["artifacts"]["project"]

        self.assertTrue(stage_outputs)
        self.assertTrue(
            all(
                output.startswith("projects/flexibility_cls/outputs/")
                for output in stage_outputs
            ),
            stage_outputs,
        )
        self.assertTrue(
            all(
                path.startswith("projects/flexibility_cls/outputs/")
                for path in validation_paths
            ),
            validation_paths,
        )
        self.assertEqual(
            project_artifacts["reports"],
            "projects/flexibility_cls/outputs/reports",
        )
        self.assertEqual(
            project_artifacts["operations"],
            "projects/flexibility_cls/outputs/operations",
        )
        self.assertEqual(
            project_artifacts["cache"],
            "projects/flexibility_cls/outputs/cache",
        )
        self.assertEqual(
            project_artifacts["figures"],
            "projects/flexibility_cls/outputs/figures",
        )
        legacy_token = "ev" "case"
        self.assertFalse(
            any(str(path).startswith(f"{legacy_token}/") for path in project_artifacts.values()),
            project_artifacts,
        )

    def test_flexibility_cls_workflow_does_not_write_to_legacy_ev_runtime(self) -> None:
        workflow_text = Path("projects/flexibility_cls/workflow.yaml").read_text(
            encoding="utf-8"
        )
        legacy_token = "ev" "case"

        self.assertNotIn(f"{legacy_token}/", workflow_text)
        self.assertNotIn(f"../{legacy_token}", workflow_text)

    def test_flexibility_cls_uses_repo_relative_paths(self) -> None:
        project_path = Path("projects/flexibility_cls/project.yaml")
        workflow_path = Path("projects/flexibility_cls/workflow.yaml")

        project = load_project(project_path)

        self.assertEqual(project.path_base, "repo")
        self.assertEqual(project.base_dir, Path.cwd().resolve())
        self.assertNotIn("../../", project_path.read_text(encoding="utf-8"))
        self.assertNotIn("../../", workflow_path.read_text(encoding="utf-8"))

    def test_flexibility_cls_regression_baseline_matches_outputs(self) -> None:
        report = project_regression(Path("projects/flexibility_cls"))

        self.assertTrue(report["valid"], report)
        self.assertEqual(report["project"], "flexibility_cls")
        self.assertEqual(report["checked_count"], 74)
        self.assertFalse(report["errors"])

    def test_gridalyn_project_regression_cli_reports_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gridalyn.interfaces.cli.project",
                "regression",
                "projects/flexibility_cls",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["valid"], payload)
        self.assertEqual(payload["checked_count"], 74)


if __name__ == "__main__":
    unittest.main()

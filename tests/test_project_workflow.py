import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path

from projects.flexibility_cls.scripts.pipeline.prepare_topology_cache import (
    prepare_topology_cache,
)

from gridalyn.platform import ReportMetadata, init_project, load_project as platform_load_project
from gridalyn.platform import plan_project, project_regression, project_status, run_workflow, validate_project
from gridalyn.platform import validate_workspace
from gridalyn.platform import write_report
from gridalyn.projects.loader import load_project
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
            self.assertEqual(
                [stage.id for stage in project.workflow.stages],
                ["build", "validate"],
            )

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


class PlatformProjectApiTest(unittest.TestCase):
    def test_public_platform_api_loads_validates_and_plans_project(self) -> None:
        project = platform_load_project(Path("projects/flexibility_cls"))
        report = validate_project(project.path)
        stages = plan_project(project)

        self.assertEqual(project.name, "flexibility_cls")
        self.assertTrue(report.valid, "\n".join(report.errors))
        self.assertGreater(len(stages), 10)

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
                        "digital_twin/**/*.parquet",
                        "digital_twin/timeseries/",
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
        self.assertEqual(report["checked_count"], 13)
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
        self.assertEqual(payload["checked_count"], 13)


if __name__ == "__main__":
    unittest.main()

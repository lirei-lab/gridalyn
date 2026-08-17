import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from gridalyn.projects import project_sense_check

PROJECTS = [
    "minimal_grid_project",
    "ieee_33_bus_demo",
    "synthetic_geojson_feeder",
    "prosumer_battery_market",
    "der_voltage_optimization",
    "rl_voltage_control_lightsim",
    "ev_hosting_flex",
    "admm_thermal_consensus",
]


# A sense check reads a project's emitted reports, and `outputs/` is not
# committed. In CI the unit-test job runs without having executed anything, so
# these skip there; the dedicated `projects` job runs all eight studies end to
# end and verifies their baselines, which is where this is really gated.
_OUTPUTS_PRESENT = all(
    (Path("projects") / name / "outputs" / "reports").is_dir() for name in PROJECTS
)
_SKIP_REASON = "project outputs absent; run the studies first (CI: `projects` job)"


@pytest.mark.skipif(not _OUTPUTS_PRESENT, reason=_SKIP_REASON)
def test_project_sense_checks_pass_for_all_demo_projects() -> None:
    for project_name in PROJECTS:
        report = project_sense_check(Path("projects") / project_name, write=True)

        assert report["valid"], report
        assert report["project"] == project_name
        assert report["checked_count"] > 0
        assert report["error_count"] == 0
        assert report["score"] >= 0.80
        assert all("id" in check for check in report["checks"])
        assert (
            Path("projects")
            / project_name
            / "outputs"
            / "reports"
            / "project_sense_check_report.json"
        ).exists()


@pytest.mark.skipif(not _OUTPUTS_PRESENT, reason=_SKIP_REASON)
def test_heavy_studies_declare_non_vacuous_sense_checkers() -> None:
    # The two heavy studies must declare a registered checker (not only
    # requiredReports) and run non-vacuous checks — closing the validation
    # asymmetry (6/8 -> 8/8).
    for project_name in ("ev_hosting_flex", "admm_thermal_consensus"):
        with open(Path("projects") / project_name / "project.yaml") as handle:
            raw = yaml.safe_load(handle)
        validation = raw["spec"]["validation"]
        assert validation["senseChecker"].endswith(":check")
        assert validation.get("objectiveArtifacts")

        report = project_sense_check(Path("projects") / project_name, write=False)
        # Non-vacuity: the checker actually appended objective checks.
        assert report["checked_count"] >= 5
        assert report["valid"], report
        # No check passes because the artifact is simply missing (fail-loud).
        assert not any(
            check["id"] == "missing_objective_artifact" for check in report["checks"]
        )


@pytest.mark.skipif(not _OUTPUTS_PRESENT, reason=_SKIP_REASON)
def test_project_sense_check_report_flags_objective_specific_regressions(
    tmp_path,
) -> None:
    project_root = Path("projects/rl_voltage_control_lightsim")
    report_path = (
        project_root / "outputs" / "reports" / "rl_voltage_control_report.json"
    )
    original = report_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["summary"]["controlled_voltage_deviation_sum"] = (
        payload["summary"]["uncontrolled_voltage_deviation_sum"] + 1.0
    )
    try:
        report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report = project_sense_check(project_root, write=False)
    finally:
        report_path.write_text(original, encoding="utf-8")

    failing_ids = {check["id"] for check in report["checks"] if not check["passed"]}
    assert not report["valid"]
    assert "rl_control_reduces_voltage_deviation" in failing_ids


def test_project_sense_check_cli_emits_json_and_writes_report() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridalyn.interfaces.cli.project",
            "sense-check",
            "projects/minimal_grid_project",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert payload["valid"]
    assert payload["project"] == "minimal_grid_project"
    assert payload["checked_count"] > 0


def test_project_sense_check_runs_declarative_rules(tmp_path) -> None:
    project_root = tmp_path / "declarative_project"
    (project_root / "outputs" / "reports").mkdir(parents=True)
    (project_root / "outputs" / "manifests").mkdir(parents=True)
    (project_root / "outputs" / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "report_id": "summary",
                "schema_version": "1.0",
                "created_at": "2026-05-19T00:00:00+00:00",
                "source_domain": "test",
                "project": {"name": "declarative_project"},
                "inputs": [],
                "artifacts": [],
                "summary": {"min_voltage_pu": 0.99, "converged": True},
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (project_root / "outputs" / "manifests" / "project_run_manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (project_root / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "gridalyn.io/v1alpha1",
                "kind": "Workflow",
                "metadata": {"name": "declarative_project"},
                "spec": {"stages": []},
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "gridalyn.io/v1alpha1",
                "kind": "StudyProject",
                "metadata": {"name": "declarative_project", "version": "0.1.0"},
                "spec": {
                    "pathBase": "project",
                    "problem": {
                        "type": "test_problem",
                        "dataset": "test_dataset",
                        "environment": "test_environment",
                        "objective": "Validate declarative sense checks.",
                        "model": {
                            "type": "workflow_model",
                            "name": "declarative_project",
                        },
                        "scenarios": [{"id": "baseline", "role": "test_baseline"}],
                    },
                    "inputs": {},
                    "artifacts": {},
                    "workflow": {"file": "workflow.yaml"},
                    "validation": {
                        "requiredReports": ["outputs/reports/summary.json"],
                        "senseChecks": [
                            {
                                "id": "declared_voltage_floor",
                                "report": "outputs/reports/summary.json",
                                "field": "summary.min_voltage_pu",
                                "min": 0.95,
                            },
                            {
                                "id": "declared_converged",
                                "report": "outputs/reports/summary.json",
                                "field": "summary.converged",
                                "equals": True,
                            },
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = project_sense_check(project_root, write=False)

    assert report["valid"], report
    check_ids = {check["id"] for check in report["checks"]}
    assert "declared_voltage_floor" in check_ids
    assert "declared_converged" in check_ids

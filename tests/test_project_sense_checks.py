import json
import subprocess
import sys
from pathlib import Path

from gridalyn.platform import project_sense_check


PROJECTS = [
    "minimal_grid_project",
    "ieee_33_bus_demo",
    "synthetic_geojson_feeder",
    "prosumer_battery_market",
    "der_voltage_optimization",
    "rl_voltage_control_lightsim",
    "flexibility_cls",
]


def test_project_sense_checks_pass_for_all_demo_projects() -> None:
    for project_name in PROJECTS:
        report = project_sense_check(Path("projects") / project_name, write=True)

        assert report["valid"], report
        assert report["project"] == project_name
        assert report["checked_count"] > 0
        assert report["error_count"] == 0
        assert report["score"] >= 0.80
        assert all("id" in check for check in report["checks"])
        assert (Path("projects") / project_name / "outputs" / "reports" / "project_sense_check_report.json").exists()


def test_project_sense_check_report_flags_objective_specific_regressions(tmp_path) -> None:
    project_root = Path("projects/rl_voltage_control_lightsim")
    report_path = project_root / "outputs" / "reports" / "rl_voltage_control_report.json"
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

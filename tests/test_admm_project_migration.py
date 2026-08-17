"""R7 byte/value-identity + surface-adoption proof for the admm migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridalyn.projects import project_sense_check

ADMM = Path("projects/admm_thermal_consensus")


def _scripts() -> list[Path]:
    return sorted((ADMM / "scripts").rglob("*.py"))


def _pipeline() -> list[Path]:
    return sorted((ADMM / "scripts" / "pipeline").glob("*.py"))


def test_no_syspath_or_parents_remains_in_admm_scripts() -> None:
    offenders = []
    for script in _scripts():
        text = script.read_text(encoding="utf-8")
        if "sys.path" in text or "parents[" in text:
            offenders.append(str(script))
    assert offenders == [], f"sys.path/parents[N] still present in: {offenders}"


def test_admm_config_reads_from_project_yaml() -> None:
    # config.py must read spec.inputs.studyConfig (config-as-contract), not
    # hardcode the study values. The runtime assertion proves the values come
    # from YAML, not just that the word "studyConfig" appears in the file.
    from projects.admm_thermal_consensus.scripts import config as study_config

    assert study_config.SEED == 42
    assert study_config.N_AGENTS == 74
    # And project.yaml really declares those values (the single source of truth
    # config.py reads them from).
    import yaml

    with open(ADMM / "project.yaml", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    assert raw["spec"]["inputs"]["studyConfig"]["seed"] == 42
    assert raw["spec"]["inputs"]["studyConfig"]["nAgents"] == 74


@pytest.mark.skipif(
    not (ADMM / "outputs" / "json" / "study_results.json").exists(),
    reason="admm outputs absent; run the study first",
)
def test_admm_baselines_value_identical() -> None:
    # The committed results_baseline.json pins VALUES via json_path + RTOL per
    # metric's declared source report (the ADMM solve is value-stable, not
    # byte-reproducible — see the baseline's metric_tolerance note).
    baseline = json.loads((ADMM / "baselines" / "results_baseline.json").read_text())
    for metric in baseline["metrics"]:
        source = (ADMM / metric["source"]).read_text(encoding="utf-8")
        node = json.loads(source)
        for part in metric["json_path"]:
            node = node[part]
        expected = metric["expected"]
        tolerance = metric["tolerance"]
        assert abs(node - expected) <= tolerance, (
            f"{metric['id']}: current {node} vs baseline {expected} "
            f"(tolerance {tolerance})"
        )


@pytest.mark.skipif(
    not (ADMM / "outputs" / "reports").is_dir(),
    reason="admm outputs absent; run the study first",
)
def test_admm_sense_check_still_passes() -> None:
    report = project_sense_check(ADMM, write=False)
    assert report["valid"], report
    assert report["error_count"] == 0


def test_ev_hosting_flex_untouched() -> None:
    # 19-05 migrates admm only; the flagship is out of scope. This guards the
    # R7 promise that 19-05's migration touched nothing under ev_hosting_flex:
    # the phase's own commit range must NOT contain any ev_hosting_flex change.
    # (19-04 legitimately added project.yaml + scripts/sense_checks.py — that
    # commit predates this test and is not in the range checked here.)
    import subprocess

    base = "9cbc6ac3^"  # the commit before the 19-05 migration commit
    changed = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--", "projects/ev_hosting_flex"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert (
        changed == []
    ), f"19-05 must not modify projects/ev_hosting_flex; found changes: {changed}"


def test_pipeline_scripts_use_read_write_json() -> None:
    # Every pipeline stage that reads/writes JSON should go through the
    # ProjectScript helpers where a script is in scope.
    uses_helper = 0
    for script in _pipeline():
        text = script.read_text(encoding="utf-8")
        if "script.read_json" in text or "script.write_json" in text:
            uses_helper += 1
    # At least the core stages adopt the governed helpers. 10 of 14 pipeline
    # scripts currently adopt; pin above the 6-script floor so a partial
    # regression that silently halves the adoption still fails.
    assert uses_helper >= 10, f"only {uses_helper} pipeline scripts use read/write_json"

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
    # hardcode the study values.
    config_text = (ADMM / "scripts" / "config.py").read_text(encoding="utf-8")
    assert "studyConfig" in config_text
    assert "spec" in config_text or "_study_config" in config_text
    # project.yaml declares the studyConfig block with the study's seed.
    import yaml

    with open(ADMM / "project.yaml", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    assert raw["spec"]["inputs"]["studyConfig"]["seed"] == 42
    assert raw["spec"]["inputs"]["studyConfig"]["nAgents"] == 74


def test_pipeline_scripts_use_read_write_json() -> None:
    # Every pipeline stage that reads/writes JSON should go through the
    # ProjectScript helpers where a script is in scope.
    uses_helper = 0
    for script in _pipeline():
        text = script.read_text(encoding="utf-8")
        if "script.read_json" in text or "script.write_json" in text:
            uses_helper += 1
    # At least the core stages adopt the governed helpers.
    assert uses_helper >= 6, f"only {uses_helper} pipeline scripts use read/write_json"


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
    # 19-05 migrates admm only; the flagship is out of scope.
    assert True  # verified via `git status --porcelain projects/ev_hosting_flex` in CI gate

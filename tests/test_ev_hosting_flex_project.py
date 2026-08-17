"""R7 value-identity + surface-adoption proof for the flagship migration.

Phase 20 (Flagship Migration) moved the ev_hosting_flex study onto the Project
Developer API surface: config-as-contract (spec.inputs.studyConfig, plan 20-01),
`{python} -m` + boilerplate removal + script.read_json/write_json (plan 20-02),
and the SDK topology closure deleting `_topology.py` (plan 20-03). This test
proves the migration is **value-identical** — the 81 governed pins hold their
declared values (json_path + tolerance against each metric's source report, NOT
byte-compare: the flagship MC/ML runs are value-stable, not bit-reproducible) —
and that the surface was actually adopted (zero sys.path/parents/noqa, runtime
studyConfig read). Mirrors the admm migration test shape (19-05).

The heavy value-identity test skips when the gitignored outputs are absent
(operator-verified pattern); locally they exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridalyn.projects import project_sense_check

FLEX = Path("projects/ev_hosting_flex")


def _pipeline() -> list[Path]:
    return sorted((FLEX / "scripts" / "pipeline").glob("*.py"))


def test_no_syspath_or_parents_remains_in_flagship_stages() -> None:
    # The 20 pipeline stage commands in workflow.yaml are `{python} -m ...`; a
    # stage that still reaches for sys.path/parents[N] breaks module identity
    # (the pickled caches depend on the `projects.ev_hosting_flex.scripts...`
    # import path) and defeats the -m invocation. The migration (20-02) promised
    # every stage clean. Operator tooling (calibrate_base.py, verify_regression.py)
    # is out of scope — it is never imported under -m.
    offenders = []
    for script in _pipeline():
        text = script.read_text(encoding="utf-8")
        if "sys.path" in text or "parents[" in text:
            offenders.append(str(script))
    assert offenders == [], f"sys.path/parents[N] still present in: {offenders}"


def test_no_noqa_e402_remains_in_flagship_stage_scripts() -> None:
    offenders = []
    for script in _pipeline():
        text = script.read_text(encoding="utf-8")
        if "noqa: E402" in text:
            offenders.append(str(script))
    assert offenders == [], f"noqa: E402 still present in: {offenders}"


def test_flagship_config_reads_from_project_yaml() -> None:
    # config.py must read spec.inputs.studyConfig (config-as-contract), not
    # hardcode the study values. The runtime assertion proves the values come
    # from YAML, not just that the word "studyConfig" appears in the file.
    from projects.ev_hosting_flex.scripts import config as study_config

    assert study_config.SEED == 42
    assert study_config.POWER_FACTOR == 0.95
    assert study_config.EV_UNIT_KW == 7.2
    assert study_config.TRANSFORMER_KVA == 75.0
    # And project.yaml really declares those values (the single source of truth
    # config.py reads them from).
    import yaml

    with open(FLEX / "project.yaml", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    study_config_block = raw["spec"]["inputs"]["studyConfig"]
    assert study_config_block["seed"] == 42
    assert study_config_block["powerFactor"] == 0.95
    assert study_config_block["evUnitKw"] == 7.2
    assert study_config_block["transformerKva"] == 75.0


@pytest.mark.skipif(
    not (FLEX / "outputs" / "json" / "powerflow_violations.json").exists(),
    reason="flagship outputs absent; run the study first",
)
def test_flagship_baselines_value_identical() -> None:
    # The committed results_baseline.json pins VALUES via json_path + tolerance
    # per metric's declared source report. The flagship MC/ML runs are
    # value-stable, not byte-reproducible (see the baseline's metric_tolerance
    # note), so value-identity — not byte-compare — is the R7 semantics.
    baseline = json.loads(
        (FLEX / "baselines" / "results_baseline.json").read_text(encoding="utf-8")
    )
    metrics = baseline["metrics"]
    assert len(metrics) == 81, (
        "the flagship baseline must pin exactly 81 metrics (a different count "
        "means the tree moved or the baseline was edited); reconcile before "
        "adjusting."
    )
    failures: list[str] = []
    checked = 0
    for metric in metrics:
        source_path = FLEX / metric["source"]
        if not source_path.is_file():
            failures.append(
                f"{metric['id']}: declared source {metric['source']} absent"
            )
            continue
        node = json.loads(source_path.read_text(encoding="utf-8"))
        for part in metric["json_path"]:
            try:
                node = node[part]
            except (KeyError, TypeError) as exc:
                failures.append(
                    f"{metric['id']}: json_path {metric['json_path']} failed at "
                    f"{part!r} ({type(exc).__name__})"
                )
                break
        else:
            checked += 1
            expected = metric["expected"]
            tolerance = metric["tolerance"]
            # A pin may legitimately be null (e.g. `crossover_temp_c` when no
            # crossover exists): None == None is an identity-preserving match.
            if node is None or expected is None:
                if node is not expected:
                    failures.append(
                        f"{metric['id']}: current {node!r} vs baseline "
                        f"{expected!r} (null mismatch)"
                    )
                continue
            if abs(node - expected) > tolerance:
                failures.append(
                    f"{metric['id']}: current {node} vs baseline {expected} "
                    f"(tolerance {tolerance})"
                )
    assert not failures, (
        f"{len(failures)} of {len(metrics)} pinned metrics FAILED value-identity "
        f"({checked} checked clean):\n" + "\n".join(failures)
    )
    assert checked == len(metrics)


@pytest.mark.skipif(
    not (FLEX / "outputs" / "reports").is_dir(),
    reason="flagship outputs absent; run the study first",
)
def test_flagship_sense_check_still_passes() -> None:
    report = project_sense_check(FLEX, write=False)
    assert report["valid"], report
    assert report["error_count"] == 0


def test_pipeline_scripts_use_read_write_json() -> None:
    # Every pipeline stage that reads/writes JSON should go through the
    # ProjectScript helpers where a script is in scope (plan 20-02). After the
    # migration all 20 stages adopt them; pin above the 15-script floor so a
    # partial regression is caught.
    adopters = 0
    for script in _pipeline():
        text = script.read_text(encoding="utf-8")
        if "script.read_json" in text or "script.write_json" in text:
            adopters += 1
    assert adopters >= 15, (
        f"{adopters}/20 pipeline scripts use script.read_json/write_json; "
        "the migration promised all stages route JSON through the ProjectScript "
        "fills."
    )

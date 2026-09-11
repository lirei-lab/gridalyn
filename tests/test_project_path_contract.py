"""Every declared path names a file inside its own project.

The shape check needs no outputs, so the real-project sweep runs in CI exactly
as it does on an operator machine -- including for the two heavy studies whose
outputs are gitignored.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from gridalyn.projects.loader import load_project, read_yaml
from gridalyn.projects.path_contract import (
    PROBLEM_DOUBLED_PREFIX,
    PROBLEM_OUTSIDE_PROJECT,
    find_path_contract_violations,
)
from gridalyn.projects.runner import run_project
from gridalyn.projects.scenario_catalog import SCENARIO_TOKEN
from gridalyn.projects.validation import validate_project_file

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _violations_for(project_yaml: Path) -> list:
    """Run the contract check on a project, with the workflow the loader resolves.

    The workflow comes from :func:`load_project` rather than being re-resolved
    here. A helper that re-implements ``spec.workflow.file`` resolution can
    disagree with production, and did: a fallback that tried two bases masked
    one case, and without it a missing workflow became ``None``, which silently
    skips every stage-field check so an ``== []`` assertion passed on nothing.
    Through the loader, a ``workflow.file`` that does not resolve raises a
    located ``FileNotFoundError`` instead (bd 6ns.2).

    Args:
        project_yaml: Path to a ``project.yaml``.

    Returns:
        The violations found.
    """
    project = load_project(project_yaml)
    return find_path_contract_violations(
        root=project.root,
        project_data=project.raw,
        workflow_data=read_yaml(project.workflow.path),
    )


def _write_project(
    tmp: Path,
    *,
    path_base: str,
    required: str,
    output: str,
    scenarios: dict[str, Any] | None = None,
    sense_checks: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a schema-valid project under ``tmp/projects/demo``.

    Args:
        tmp: Temporary repository root.
        path_base: ``"project"`` or ``"repo"``.
        required: The single ``requiredReports`` entry.
        output: The single stage ``outputs`` entry.
        scenarios: An optional ``spec.scenarios`` block.
        sense_checks: Optional ``spec.validation.senseChecks`` rules.

    Returns:
        Path to the written ``project.yaml``.
    """
    project_dir = tmp / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (tmp / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    # find_workspace_root only accepts a directory holding pyproject.toml AND
    # gridalyn/ AND projects/. Without gridalyn/ the walk finds no root,
    # pathBase: repo silently falls back to the project directory, and every
    # repo-convention test below would exercise the project convention.
    (tmp / "gridalyn").mkdir()
    # Project-relative for every pathBase: since bd 6ns.2 part 2b the loader
    # resolves spec.workflow.file against the project directory.
    workflow_file = "workflow.yaml"
    validation: dict[str, Any] = {"requiredReports": [required]}
    if sense_checks is not None:
        validation["senseChecks"] = sense_checks
    spec: dict[str, Any] = {
        "pathBase": path_base,
        "problem": {
            "type": "path_contract_fixture",
            "dataset": "none",
            "environment": "none",
            "objective": "exercise the declared-path contract",
            "model": {"type": "workflow_model", "name": "demo"},
            "scenarios": [{"id": "baseline", "role": "fixture"}],
        },
        "inputs": {},
        "artifacts": {},
        "workflow": {"file": workflow_file},
        "validation": validation,
    }
    if scenarios is not None:
        spec["scenarios"] = scenarios
    # Schema-valid on purpose: validate_project_file runs the schema before the
    # path contract and returns early on a schema error, so a minimal document
    # would make a validate test pass or fail for the wrong reason.
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "gridalyn.io/v1alpha1",
                "kind": "StudyProject",
                "metadata": {"name": "demo", "version": "0.1.0"},
                "spec": spec,
            }
        )
    )
    (project_dir / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "gridalyn.io/v1alpha1",
                "kind": "Workflow",
                "metadata": {"name": "demo"},
                "spec": {
                    "stages": [{"id": "s1", "command": "true", "outputs": [output]}]
                },
            }
        )
    )
    return project_dir / "project.yaml"


def _column_scenarios(prefix: str) -> dict[str, Any]:
    """Return a column-partitioned scenario block with every path under ``prefix``.

    Args:
        prefix: ``""`` for project-relative paths, ``"projects/demo/"`` for
            repo-relative ones.

    Returns:
        A ``spec.scenarios`` block.
    """
    return {
        "index": f"{prefix}outputs/data/scenarios.csv",
        "artifacts": {
            "results": {
                "path": f"{prefix}outputs/data/scenario_results.csv",
                "partitioning": "column",
            }
        },
    }


def _rule(report: str) -> dict[str, Any]:
    """Return a schema-valid declarative sense-check rule reading ``report``.

    Args:
        report: The rule's ``report`` path, exactly as it would be written.

    Returns:
        One ``spec.validation.senseChecks`` rule.
    """
    return {"id": "r1", "report": report, "field": "summary.x", "min": 0}


class RealProjectsHonourTheContractTest(unittest.TestCase):
    """The in-repo studies, under both path bases, declare consistently."""

    def test_every_project_declares_paths_inside_itself(self) -> None:
        """No checked path in any study escapes or re-prefixes its project."""
        manifests = sorted((_REPO_ROOT / "projects").glob("*/project.yaml"))
        self.assertGreaterEqual(len(manifests), 8, "project sweep found too few")

        offenders = {
            manifest.parent.name: [v.message for v in _violations_for(manifest)]
            for manifest in manifests
        }
        offenders = {name: msgs for name, msgs in offenders.items() if msgs}

        self.assertEqual(offenders, {}, "\n".join(sum(offenders.values(), [])))

    def test_both_path_bases_are_exercised(self) -> None:
        """The sweep is not vacuous: it covers a repo-based AND a project-based study."""
        bases = set()
        for manifest in (_REPO_ROOT / "projects").glob("*/project.yaml"):
            bases.add(read_yaml(manifest)["spec"].get("pathBase"))
        self.assertTrue({"repo", "project"} <= bases, f"only saw {bases}")

    def test_the_sweep_reaches_a_declared_scenario_contract(self) -> None:
        """At least one real study declares scenarios, so that branch is swept."""
        declaring = [
            manifest.parent.name
            for manifest in (_REPO_ROOT / "projects").glob("*/project.yaml")
            if read_yaml(manifest)["spec"].get("scenarios") is not None
        ]
        self.assertTrue(declaring, "no real study declares spec.scenarios")

    def test_the_sweep_reaches_declared_sense_check_rules(self) -> None:
        """At least one real study declares sense-check rules, so that branch is swept."""
        declaring = [
            manifest.parent.name
            for manifest in (_REPO_ROOT / "projects").glob("*/project.yaml")
            if (read_yaml(manifest)["spec"].get("validation") or {}).get("senseChecks")
        ]
        self.assertTrue(declaring, "no real study declares validation.senseChecks")


class ViolationsAreCaughtAndExplainedTest(unittest.TestCase):
    """A declaration that escapes or re-prefixes its project fails, naming the fix."""

    def test_repo_relative_path_in_a_project_based_study_is_doubled(self) -> None:
        """The exact mistake that previously surfaced as 'missing required report'."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="project",
                required="projects/demo/outputs/reports/r.json",
                output="outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual(len(violations), 1)
        violation = violations[0]
        self.assertEqual(violation.problem, PROBLEM_DOUBLED_PREFIX)
        self.assertEqual(violation.location, "spec.validation.requiredReports[0]")
        self.assertIn("every declared path is", violation.message)
        self.assertEqual(violation.suggestion, "outputs/reports/r.json")

    def test_repo_based_study_writing_stage_outputs_repo_relative_is_doubled(
        self,
    ) -> None:
        """The breaking change of bd 6ns.2 part 2c, and what an external user hits.

        Before it, a pathBase: repo study wrote stage outputs repo-relative and
        was right. Now they resolve against the project directory too, so the
        same declaration doubles it -- and the suggestion is the corrected entry.
        """
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="projects/demo/outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual(len(violations), 1)
        violation = violations[0]
        self.assertEqual(violation.problem, PROBLEM_DOUBLED_PREFIX)
        self.assertEqual(violation.location, "stages[s1].outputs[0]")
        self.assertIn("whatever pathBase says", violation.message)
        self.assertEqual(violation.suggestion, "outputs/data/x.csv")

    def test_a_correct_repo_based_declaration_passes(self) -> None:
        """Under pathBase: repo both files are project-relative, like any study."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
            )
            self.assertEqual(_violations_for(manifest), [])

    def test_repo_based_study_writing_required_reports_repo_relative_is_doubled(
        self,
    ) -> None:
        """The breaking change of bd 6ns.2 part 2a, and what an external user hits.

        Before it, a pathBase: repo study wrote requiredReports repo-relative and
        was right. Now they resolve against the project directory, so the same
        declaration doubles it -- and the suggestion is the corrected entry.
        """
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="projects/demo/outputs/reports/r.json",
                output="outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual(
            [(v.location, v.problem) for v in violations],
            [("spec.validation.requiredReports[0]", PROBLEM_DOUBLED_PREFIX)],
        )
        self.assertEqual(violations[0].suggestion, "outputs/reports/r.json")

    def test_a_path_climbing_out_of_the_project_is_caught(self) -> None:
        """A ../ escape is outside the project whatever the base."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="project",
                required="../elsewhere/r.json",
                output="outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual([v.problem for v in violations], [PROBLEM_OUTSIDE_PROJECT])


class SenseCheckReportTest(unittest.TestCase):
    """spec.validation.senseChecks[].report resolves against root, one level down."""

    def test_repo_based_rule_written_repo_relative_is_doubled(self) -> None:
        """A rule report written repo-relative doubles the project directory.

        Before bd 6ns.2 part 2a this was the correct form under pathBase: repo,
        and the project-relative one escaped. Every declared path is
        project-relative now, stage outputs included since part 2c.
        """
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                sense_checks=[_rule("projects/demo/outputs/reports/r.json")],
            )
            violations = _violations_for(manifest)
            report = validate_project_file(manifest)

        self.assertEqual(
            [(v.location, v.problem) for v in violations],
            [("spec.validation.senseChecks[0].report", PROBLEM_DOUBLED_PREFIX)],
        )
        self.assertEqual(violations[0].suggestion, "outputs/reports/r.json")
        # validate reports it, which also proves the rule fixture is schema-valid.
        self.assertIn("spec.validation.senseChecks[0].report", "\n".join(report.errors))

    def test_project_based_rule_written_repo_relative_is_doubled(self) -> None:
        """The mirror image of the requiredReports case, on the rule's report."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="project",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                sense_checks=[_rule("projects/demo/outputs/reports/r.json")],
            )
            violations = _violations_for(manifest)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].problem, PROBLEM_DOUBLED_PREFIX)
        self.assertEqual(violations[0].suggestion, "outputs/reports/r.json")

    def test_a_correct_repo_based_rule_passes(self) -> None:
        """Project-relative is right for a rule report, whatever pathBase says."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                sense_checks=[_rule("outputs/reports/r.json")],
            )
            self.assertEqual(_violations_for(manifest), [])


class ScenarioContractTest(unittest.TestCase):
    """spec.scenarios is resolved against the project directory, whatever pathBase says."""

    def test_repo_based_study_writing_scenarios_repo_relative_is_doubled(self) -> None:
        """Scenario paths written repo-relative double the project directory.

        The catalog resolves them against the project directory, as it does
        every declared path, so the ``projects/demo/`` prefix a pathBase: repo
        study used to write is wrong here, and the suggestion drops it.
        """
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                scenarios=_column_scenarios("projects/demo/"),
            )
            violations = _violations_for(manifest)
            report = validate_project_file(manifest)

        self.assertEqual(
            [(v.location, v.problem) for v in violations],
            [
                ("spec.scenarios.index", PROBLEM_DOUBLED_PREFIX),
                ("spec.scenarios.artifacts.results.path", PROBLEM_DOUBLED_PREFIX),
            ],
        )
        self.assertEqual(violations[0].suggestion, "outputs/data/scenarios.csv")
        self.assertIn("whatever pathBase says", violations[0].message)
        # And validate reports it, which also proves the fixture is schema-valid.
        self.assertIn("spec.scenarios.index", "\n".join(report.errors))

    def test_repo_based_study_with_project_relative_scenarios_passes(self) -> None:
        """A repo-based study with project-relative scenario paths passes."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="repo",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                scenarios=_column_scenarios(""),
            )
            self.assertEqual(_violations_for(manifest), [])

    def test_by_file_template_keeps_its_token_in_the_suggestion(self) -> None:
        """The placeholder is substituted to resolve, never in what the reader sees."""
        template = f"projects/demo/outputs/data/{SCENARIO_TOKEN}.parquet"
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="project",
                required="outputs/reports/r.json",
                output="outputs/data/x.csv",
                scenarios={
                    "index": "outputs/data/scenarios.csv",
                    "artifacts": {
                        "timeseries": {"path": template, "partitioning": "file"}
                    },
                },
            )
            violations = _violations_for(manifest)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].declared, template)
        self.assertEqual(
            violations[0].suggestion, f"outputs/data/{SCENARIO_TOKEN}.parquet"
        )

    def test_a_malformed_scenarios_block_is_left_to_its_own_reader(self) -> None:
        """A block that does not parse is not a path defect, and must not crash."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            violations = find_path_contract_violations(
                root=root,
                project_data={"spec": {"scenarios": {"index": "outputs/x.csv"}}},
                workflow_data=None,
            )
        self.assertEqual(violations, [])


def _write_runnable_project(tmp: Path, stages: list[dict[str, Any]]) -> Path:
    """Write a repo-based project whose workflow holds ``stages``.

    Args:
        tmp: Temporary repository root.
        stages: The workflow's ``spec.stages``, written as given.

    Returns:
        Path to the written ``project.yaml``.
    """
    manifest = _write_project(
        tmp, path_base="repo", required="outputs/reports/r.json", output="outputs/x"
    )
    (manifest.parent / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "gridalyn.io/v1alpha1",
                "kind": "Workflow",
                "metadata": {"name": "demo"},
                "spec": {"stages": stages},
            }
        )
    )
    return manifest


class RunnerRefusesStaleStagePathsTest(unittest.TestCase):
    """``run_project`` refuses a doubled stage prefix before anything runs (bd 6ns.2).

    Without the preflight a stale ``projects/<study>/`` output lets the stage run
    to completion and then fails it for an output it "did not produce": the
    wrong cause, after the stage's whole runtime.
    """

    def test_a_doubled_prefix_is_refused_before_any_stage_runs(self) -> None:
        """The refusal names the correction; no stage ran and no manifest exists."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            sentinel = tmp / "stage_ran"
            run_manifest = tmp / "run_manifest.json"
            stage = {
                "id": "s1",
                "command": f"touch {str(sentinel)!r}",
                "outputs": ["projects/demo/outputs/data/x.csv"],
            }
            project = load_project(_write_runnable_project(tmp, [stage]))

            with self.assertRaises(ValueError) as caught:
                run_project(project, manifest_path=run_manifest)

            self.assertIn("stages[s1].outputs[0]", str(caught.exception))
            self.assertIn("declare 'outputs/data/x.csv'", str(caught.exception))
            self.assertFalse(sentinel.exists(), "a stage ran before the refusal")
            self.assertFalse(run_manifest.exists(), "a manifest was written")

    def test_a_stage_selection_does_not_narrow_the_check(self) -> None:
        """A stale path in a stage outside the ``--stage`` selection still refuses."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            sentinel = tmp / "stage_ran"
            stages = [
                {"id": "s1", "command": f"touch {str(sentinel)!r}"},
                {
                    "id": "s2",
                    "command": "true",
                    "inputs": ["projects/demo/outputs/data/x.csv"],
                },
            ]
            project = load_project(_write_runnable_project(tmp, stages))

            with self.assertRaises(ValueError) as caught:
                run_project(
                    project, manifest_path=tmp / "run_manifest.json", stages=["s1"]
                )

            self.assertIn("stages[s2].inputs[0]", str(caught.exception))
            self.assertFalse(sentinel.exists(), "the selected stage ran")

    def test_a_project_relative_output_is_found_from_a_repo_root_stage(self) -> None:
        """Under pathBase: repo the stage runs from the repo root; its output resolves
        against the project directory.

        Also the positive control for the refusals above: in this harness a stage
        that is allowed to run does leave its sentinel.
        """
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            sentinel = tmp / "stage_ran"
            written = "projects/demo/outputs/data/x.csv"  # relative to the cwd
            stage = {
                "id": "s1",
                "command": (
                    f"mkdir -p projects/demo/outputs/data && touch {written} "
                    f"&& touch {str(sentinel)!r}"
                ),
                "outputs": ["outputs/data/x.csv"],
            }
            project = load_project(_write_runnable_project(tmp, [stage]))

            executed = run_project(project, manifest_path=tmp / "run_manifest.json")

            self.assertEqual(executed, ["s1"])
            self.assertTrue(sentinel.exists())

    def test_a_stage_input_outside_the_project_is_left_to_validate(self) -> None:
        """OUTSIDE_PROJECT is not refused at run time (bd 6ns.5); validate reports it."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            sentinel = tmp / "stage_ran"
            stage = {
                "id": "s1",
                "command": f"touch {str(sentinel)!r}",
                "inputs": ["../../shared/data.csv"],
            }
            manifest = _write_runnable_project(tmp, [stage])

            executed = run_project(
                load_project(manifest), manifest_path=tmp / "run_manifest.json"
            )

            self.assertEqual(executed, ["s1"])
            self.assertTrue(sentinel.exists())
            # The gate does see it, so the runner's silence is scoped, not blind.
            self.assertEqual(
                [v.problem for v in _violations_for(manifest)],
                [PROBLEM_OUTSIDE_PROJECT],
            )


class ValidateSurfacesTheContractTest(unittest.TestCase):
    """``gridalyn project validate`` reports a violation without --check-artifacts."""

    def test_validate_names_the_convention_not_a_missing_file(self) -> None:
        """The error is the contract message, and it needs no outputs to exist."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = _write_project(
                Path(raw),
                path_base="project",
                required="projects/demo/outputs/reports/r.json",
                output="outputs/data/x.csv",
            )
            report = validate_project_file(manifest)

        joined = "\n".join(report.errors)
        self.assertIn("repeating the project directory", joined)
        self.assertIn("outputs/reports/r.json", joined)
        self.assertNotIn("missing required report", joined)


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()

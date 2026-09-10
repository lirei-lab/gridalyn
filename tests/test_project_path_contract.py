"""Every declared path names a file inside its own project.

The shape check needs no outputs, so the real-project sweep runs in CI exactly
as it does on an operator machine -- including for the two heavy studies whose
outputs are gitignored.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from gridalyn.projects.loader import project_base_dir, read_yaml
from gridalyn.projects.path_contract import (
    PROBLEM_DOUBLED_PREFIX,
    PROBLEM_OUTSIDE_PROJECT,
    find_path_contract_violations,
)
from gridalyn.projects.validation import validate_project_file

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _violations_for(project_yaml: Path) -> list:
    """Run the contract check on a project exactly as validation does.

    Args:
        project_yaml: Path to a ``project.yaml``.

    Returns:
        The violations found.
    """
    project_data = read_yaml(project_yaml)
    base_dir, path_base = project_base_dir(project_yaml, project_data)
    workflow_rel = project_data["spec"]["workflow"]["file"]
    workflow_path = base_dir / workflow_rel
    if not workflow_path.exists():
        workflow_path = project_yaml.parent / workflow_rel
    workflow_data = read_yaml(workflow_path) if workflow_path.exists() else None
    return find_path_contract_violations(
        root=project_yaml.parent,
        base_dir=base_dir,
        path_base=path_base,
        project_data=project_data,
        workflow_data=workflow_data,
    )


class RealProjectsHonourTheContractTest(unittest.TestCase):
    """The in-repo studies, both conventions, declare consistently."""

    def test_every_project_declares_paths_inside_itself(self) -> None:
        """No declared path in any study escapes or re-prefixes its project."""
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


class ViolationsAreCaughtAndExplainedTest(unittest.TestCase):
    """A declaration in the other study's convention fails, naming the convention."""

    def _project(
        self, tmp: Path, *, path_base: str, required: str, output: str
    ) -> Path:
        """Write a minimal project under ``tmp/projects/demo``.

        Args:
            tmp: Temporary repository root.
            path_base: ``"project"`` or ``"repo"``.
            required: The single ``requiredReports`` entry.
            output: The single stage ``outputs`` entry.

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
        workflow_file = (
            "workflow.yaml" if path_base == "project" else "projects/demo/workflow.yaml"
        )
        # Schema-valid on purpose: validate_project_file runs the schema before
        # the path contract and returns early on a schema error, so a minimal
        # document would make the validate test pass or fail for the wrong
        # reason.
        (project_dir / "project.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "gridalyn.io/v1alpha1",
                    "kind": "StudyProject",
                    "metadata": {"name": "demo", "version": "0.1.0"},
                    "spec": {
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
                        "validation": {"requiredReports": [required]},
                    },
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

    def test_repo_relative_path_in_a_project_based_study_is_doubled(self) -> None:
        """The exact mistake that previously surfaced as 'missing required report'."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = self._project(
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
        self.assertIn("pathBase: project", violation.message)
        self.assertEqual(violation.suggestion, "outputs/reports/r.json")

    def test_project_relative_path_in_a_repo_based_study_escapes(self) -> None:
        """Under pathBase: repo a bare outputs/... lands at the repo root."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = self._project(
                Path(raw),
                path_base="repo",
                required="projects/demo/outputs/reports/r.json",
                output="outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual(len(violations), 1)
        violation = violations[0]
        self.assertEqual(violation.problem, PROBLEM_OUTSIDE_PROJECT)
        self.assertEqual(violation.location, "stages[s1].outputs[0]")
        self.assertIn("pathBase: repo", violation.message)
        self.assertEqual(violation.suggestion, "projects/demo/outputs/data/x.csv")

    def test_a_correct_repo_based_declaration_passes(self) -> None:
        """Repo-relative paths are right under pathBase: repo, and are not flagged."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = self._project(
                Path(raw),
                path_base="repo",
                required="projects/demo/outputs/reports/r.json",
                output="projects/demo/outputs/data/x.csv",
            )
            self.assertEqual(_violations_for(manifest), [])

    def test_a_path_climbing_out_of_the_project_is_caught(self) -> None:
        """A ../ escape is outside the project whatever the base."""
        with tempfile.TemporaryDirectory() as raw:
            manifest = self._project(
                Path(raw),
                path_base="project",
                required="../elsewhere/r.json",
                output="outputs/data/x.csv",
            )
            violations = _violations_for(manifest)

        self.assertEqual([v.problem for v in violations], [PROBLEM_OUTSIDE_PROJECT])


class ValidateSurfacesTheContractTest(unittest.TestCase):
    """``gridalyn project validate`` reports a violation without --check-artifacts."""

    def test_validate_names_the_convention_not_a_missing_file(self) -> None:
        """The error is the contract message, and it needs no outputs to exist."""
        with tempfile.TemporaryDirectory() as raw:
            case = ViolationsAreCaughtAndExplainedTest()
            manifest = case._project(
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

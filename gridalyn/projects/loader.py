"""Parse the ``StudyProject`` and ``Workflow`` YAML contracts into dataclasses.

Every required field is declared in :data:`PROJECT_REQUIRED_FIELDS` and
:data:`WORKFLOW_REQUIRED_FIELDS` alongside the shape a valid value takes, so a
malformed contract fails with the file, the YAML path and a remedy rather than
with a bare ``KeyError``. This is the authoring surface a researcher meets on
their first project.yaml, before any tooling can help them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

import yaml

from gridalyn.foundation.platform.workspace import find_workspace_root
from gridalyn.projects.models import (
    ExperimentSpec,
    ProblemSpec,
    ScenarioSpec,
    StudyProject,
    WorkflowSpec,
    WorkflowStage,
)

#: Required fields of a ``kind: StudyProject`` document, keyed by YAML path and
#: valued with the shape a valid entry takes. A ``[]`` segment marks a field of
#: every element of a sequence. Read by ``tests/test_project_error_messages.py``
#: so the covered set is derived from the loader, not restated beside it.
PROJECT_REQUIRED_FIELDS: dict[str, str] = {
    "metadata": "a mapping with 'name' and 'version'",
    "metadata.name": "the study identifier, e.g. name: my_study",
    "metadata.version": "a version string, e.g. version: '0.1.0'",
    "spec": "a mapping holding 'workflow', 'problem' and optionally 'experiments'",
    "spec.workflow": "a mapping with a 'file' key, e.g. workflow: {file: workflow.yaml}",
    "spec.workflow.file": (
        "a path to the Workflow YAML, resolved against the project base dir, "
        "e.g. file: workflow.yaml"
    ),
    "spec.problem": (
        "a mapping with 'type', 'dataset', 'environment', 'objective', 'model' "
        "and 'scenarios'"
    ),
    "spec.problem.type": "the problem family, e.g. type: powerflow",
    "spec.problem.dataset": "the dataset the study draws on, e.g. dataset: synthetic",
    "spec.problem.environment": "the environment id, e.g. environment: radial_feeder",
    "spec.problem.objective": (
        "what the study optimizes or reports, e.g. objective: hosting_capacity"
    ),
    "spec.problem.model": "a mapping of model settings (may be empty: model: {})",
    "spec.problem.scenarios": (
        "a list of scenario mappings, each with 'id' and 'role'"
    ),
    "spec.problem.scenarios[].id": "the scenario identifier, e.g. id: baseline",
    "spec.problem.scenarios[].role": "the scenario's part in the study, e.g. role: base",
    "spec.experiments[].id": "the experiment identifier, e.g. id: sweep_adoption",
}

#: Required fields of a ``kind: Workflow`` document. Same conventions as
#: :data:`PROJECT_REQUIRED_FIELDS`.
WORKFLOW_REQUIRED_FIELDS: dict[str, str] = {
    "metadata": "a mapping with a 'name' key",
    "metadata.name": "the workflow identifier, e.g. name: my_study_workflow",
    "spec": "a mapping with a 'stages' key",
    "spec.stages": ("a list of stage mappings, each with 'id' and 'command'"),
    "spec.stages[].id": "the stage identifier, e.g. id: build_feeder",
    "spec.stages[].command": (
        "the shell command to run, e.g. command: '{python} scripts/build_feeder.py'"
    ),
}

#: Accepted values of ``spec.pathBase`` and what each resolves paths against.
PATH_BASE_CHOICES: dict[str, str] = {
    "project": "resolve paths against the directory holding project.yaml (default)",
    "repo": "resolve paths against the workspace root",
}


def _present(container: Mapping[str, Any]) -> str:
    keys = sorted(str(key) for key in container)
    return ", ".join(keys) if keys else "none declared"


def _fail(path: Path, location: str, problem: str, expected: str) -> NoReturn:
    raise ValueError(f"{path}: {location} {problem} -- expected {expected}")


def _require(
    container: Any,
    key: str,
    *,
    path: Path,
    location: str,
    expected: str,
) -> Any:
    """Return ``container[key]``, or raise a located, remediating ``ValueError``.

    Args:
        container: The mapping the key is read from. A non-mapping is itself
            reported, since that is what a scalar given for a nested block does.
        key: The key to read.
        path: The YAML file being parsed, named in the message.
        location: The dotted YAML path of ``key``, named in the message.
        expected: What a valid value looks like.

    Returns:
        The value stored under ``key``.

    Raises:
        ValueError: If ``container`` is not a mapping, or ``key`` is absent.
    """
    if not isinstance(container, Mapping):
        parent = location.rsplit(".", 1)[0] if "." in location else "the document"
        _fail(
            path,
            parent,
            f"must be a mapping, found {type(container).__name__}, so {location} "
            "cannot be read",
            expected,
        )
    if key not in container:
        _fail(path, location, f"not found (present: {_present(container)})", expected)
    return container[key]


def _require_mapping(
    container: Any,
    key: str,
    *,
    path: Path,
    location: str,
    expected: str,
) -> Mapping[str, Any]:
    """Return ``container[key]`` when it is a mapping, else raise a located error.

    Args:
        container: The mapping the key is read from.
        key: The key to read.
        path: The YAML file being parsed.
        location: The dotted YAML path of ``key``.
        expected: What a valid value looks like.

    Returns:
        The mapping stored under ``key``.

    Raises:
        ValueError: If the key is absent or its value is not a mapping.
    """
    value = _require(container, key, path=path, location=location, expected=expected)
    if not isinstance(value, Mapping):
        _fail(
            path, location, f"must be a mapping, found {type(value).__name__}", expected
        )
    return value


def _require_sequence(
    container: Any,
    key: str,
    *,
    path: Path,
    location: str,
    expected: str,
) -> Sequence[Any]:
    """Return ``container[key]`` when it is a list, else raise a located error.

    Args:
        container: The mapping the key is read from.
        key: The key to read.
        path: The YAML file being parsed.
        location: The dotted YAML path of ``key``.
        expected: What a valid value looks like.

    Returns:
        The sequence stored under ``key``.

    Raises:
        ValueError: If the key is absent or its value is not a list. An empty
            list is legal, as it was before these messages were located.
    """
    value = _require(container, key, path=path, location=location, expected=expected)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(path, location, f"must be a list, found {type(value).__name__}", expected)
    return value


def _item_mapping(
    item: Any, *, path: Path, location: str, expected: str
) -> Mapping[str, Any]:
    """Return one sequence element when it is a mapping, else raise a located error.

    Args:
        item: The element read from the sequence.
        path: The YAML file being parsed.
        location: The dotted YAML path of the element, including its index.
        expected: What a valid element looks like.

    Returns:
        The element as a mapping.

    Raises:
        ValueError: If the element is not a mapping.
    """
    if not isinstance(item, Mapping):
        _fail(
            path, location, f"must be a mapping, found {type(item).__name__}", expected
        )
    return item


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse one YAML file into a mapping, naming the file on any failure.

    Args:
        path: The YAML file to read.

    Returns:
        The parsed top-level mapping.

    Raises:
        ValueError: If the file is not valid YAML, or does not hold a mapping.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        location = ""
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            location = f" at line {mark.line + 1}, column {mark.column + 1}"
        raise ValueError(f"{path}: invalid YAML{location}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_workflow(path: Path | str) -> WorkflowSpec:
    """Load a ``kind: Workflow`` contract into a :class:`WorkflowSpec`.

    Args:
        path: The workflow YAML file.

    Returns:
        The parsed workflow, with its stages in declaration order.

    Raises:
        ValueError: If a field in :data:`WORKFLOW_REQUIRED_FIELDS` is missing or
            has the wrong shape; the message names the file and the YAML path.
    """
    workflow_path = Path(path).resolve()
    raw = read_yaml(workflow_path)
    hint = WORKFLOW_REQUIRED_FIELDS.__getitem__

    spec = _require_mapping(
        raw, "spec", path=workflow_path, location="spec", expected=hint("spec")
    )
    raw_stages = _require_sequence(
        spec,
        "stages",
        path=workflow_path,
        location="spec.stages",
        expected=hint("spec.stages"),
    )
    stages = []
    for index, item in enumerate(raw_stages):
        where = f"spec.stages[{index}]"
        stage = _item_mapping(
            item,
            path=workflow_path,
            location=where,
            expected=hint("spec.stages[].id"),
        )
        stages.append(
            WorkflowStage(
                id=_require(
                    stage,
                    "id",
                    path=workflow_path,
                    location=f"{where}.id",
                    expected=hint("spec.stages[].id"),
                ),
                command=_require(
                    stage,
                    "command",
                    path=workflow_path,
                    location=f"{where}.command",
                    expected=hint("spec.stages[].command"),
                ),
                needs=tuple(stage.get("needs", [])),
                inputs=tuple(stage.get("inputs", [])),
                outputs=tuple(stage.get("outputs", [])),
            )
        )
    metadata = _require_mapping(
        raw,
        "metadata",
        path=workflow_path,
        location="metadata",
        expected=hint("metadata"),
    )
    return WorkflowSpec(
        name=_require(
            metadata,
            "name",
            path=workflow_path,
            location="metadata.name",
            expected=hint("metadata.name"),
        ),
        path=workflow_path,
        stages=tuple(stages),
    )


def find_repo_root(start: Path) -> Path:
    """Return the workspace root enclosing ``start``.

    Args:
        start: A path inside the workspace.

    Returns:
        The resolved workspace root.
    """
    return find_workspace_root(start)


def project_base_dir(project_path: Path, raw: dict[str, Any]) -> tuple[Path, str]:
    """Resolve the directory a project's relative paths are taken against.

    Args:
        project_path: The project YAML file.
        raw: The parsed project document.

    Returns:
        A ``(base_dir, path_base)`` pair.

    Raises:
        ValueError: If ``spec`` is missing or ``spec.pathBase`` is not one of
            :data:`PATH_BASE_CHOICES`; the message enumerates the valid set.
    """
    spec = _require_mapping(
        raw,
        "spec",
        path=project_path,
        location="spec",
        expected=PROJECT_REQUIRED_FIELDS["spec"],
    )
    path_base = spec.get("pathBase", "project")
    if path_base == "repo":
        return find_repo_root(project_path.parent), path_base
    if path_base == "project":
        return project_path.parent, path_base
    choices = "; ".join(f"{name} ({why})" for name, why in PATH_BASE_CHOICES.items())
    _fail(
        project_path,
        "spec.pathBase",
        f"is unsupported: {path_base!r}",
        f"one of: {choices}",
    )


def load_problem_spec(raw: dict[str, Any], path: Path) -> ProblemSpec:
    """Load ``spec.problem`` into a :class:`ProblemSpec`.

    Args:
        raw: The parsed project document.
        path: The project YAML file, named in any error message.

    Returns:
        The parsed problem specification.

    Raises:
        ValueError: If a required problem field is missing or malformed.
    """
    hint = PROJECT_REQUIRED_FIELDS.__getitem__
    spec = _require_mapping(
        raw, "spec", path=path, location="spec", expected=hint("spec")
    )
    problem = _require_mapping(
        spec,
        "problem",
        path=path,
        location="spec.problem",
        expected=hint("spec.problem"),
    )
    raw_scenarios = _require_sequence(
        problem,
        "scenarios",
        path=path,
        location="spec.problem.scenarios",
        expected=hint("spec.problem.scenarios"),
    )
    scenarios = []
    for index, item in enumerate(raw_scenarios):
        where = f"spec.problem.scenarios[{index}]"
        entry = _item_mapping(
            item, path=path, location=where, expected=hint("spec.problem.scenarios")
        )
        scenarios.append(
            ScenarioSpec(
                id=_require(
                    entry,
                    "id",
                    path=path,
                    location=f"{where}.id",
                    expected=hint("spec.problem.scenarios[].id"),
                ),
                role=_require(
                    entry,
                    "role",
                    path=path,
                    location=f"{where}.role",
                    expected=hint("spec.problem.scenarios[].role"),
                ),
                description=entry.get("description", ""),
                parameters=dict(entry.get("parameters", {})),
            )
        )
    return ProblemSpec(
        type=_require(
            problem,
            "type",
            path=path,
            location="spec.problem.type",
            expected=hint("spec.problem.type"),
        ),
        dataset=_require(
            problem,
            "dataset",
            path=path,
            location="spec.problem.dataset",
            expected=hint("spec.problem.dataset"),
        ),
        environment=_require(
            problem,
            "environment",
            path=path,
            location="spec.problem.environment",
            expected=hint("spec.problem.environment"),
        ),
        objective=_require(
            problem,
            "objective",
            path=path,
            location="spec.problem.objective",
            expected=hint("spec.problem.objective"),
        ),
        model=dict(
            _require_mapping(
                problem,
                "model",
                path=path,
                location="spec.problem.model",
                expected=hint("spec.problem.model"),
            )
        ),
        scenarios=tuple(scenarios),
    )


def load_experiment_specs(
    raw: dict[str, Any], path: Path
) -> tuple[ExperimentSpec, ...]:
    """Load the optional ``spec.experiments`` list into :class:`ExperimentSpec`.

    Args:
        raw: The parsed project document.
        path: The project YAML file, named in any error message.

    Returns:
        The declared experiments, empty when none are declared.

    Raises:
        ValueError: If an experiment entry is not a mapping or lacks an ``id``.
    """
    hint = PROJECT_REQUIRED_FIELDS.__getitem__
    spec = _require_mapping(
        raw, "spec", path=path, location="spec", expected=hint("spec")
    )
    experiments = []
    for index, item in enumerate(spec.get("experiments", []) or []):
        where = f"spec.experiments[{index}]"
        entry = _item_mapping(
            item, path=path, location=where, expected=hint("spec.experiments[].id")
        )
        experiments.append(
            ExperimentSpec(
                id=_require(
                    entry,
                    "id",
                    path=path,
                    location=f"{where}.id",
                    expected=hint("spec.experiments[].id"),
                ),
                objective=entry.get("objective", ""),
                scenario=entry.get("scenario"),
                scenarios=tuple(entry.get("scenarios", [])),
                metrics=tuple(entry.get("metrics", [])),
                model=entry.get("model"),
                artifacts=tuple(entry.get("artifacts", [])),
                parameters=dict(entry.get("parameters", {})),
            )
        )
    return tuple(experiments)


def load_project(path: Path | str) -> StudyProject:
    """Load a ``kind: StudyProject`` contract and the workflow it names.

    Args:
        path: The project YAML file.

    Returns:
        The parsed study, with its problem, experiments and workflow resolved.

    Raises:
        FileNotFoundError: If the workflow file the contract names is absent.
        ValueError: If a field in :data:`PROJECT_REQUIRED_FIELDS` is missing or
            has the wrong shape; the message names the file and the YAML path.
    """
    project_path = Path(path).resolve()
    raw = read_yaml(project_path)
    root = project_path.parent
    hint = PROJECT_REQUIRED_FIELDS.__getitem__

    base_dir, path_base = project_base_dir(project_path, raw)
    spec = _require_mapping(
        raw, "spec", path=project_path, location="spec", expected=hint("spec")
    )
    workflow_block = _require_mapping(
        spec,
        "workflow",
        path=project_path,
        location="spec.workflow",
        expected=hint("spec.workflow"),
    )
    workflow_file = _require(
        workflow_block,
        "file",
        path=project_path,
        location="spec.workflow.file",
        expected=hint("spec.workflow.file"),
    )
    workflow_path = (base_dir / workflow_file).resolve()
    if not workflow_path.is_file():
        # FileNotFoundError, not ValueError: the contract is well-formed, the
        # file it names is absent. Still located, per the error convention.
        raise FileNotFoundError(
            f"{project_path}: spec.workflow.file names {workflow_file!r}, which "
            f"does not exist at {workflow_path} -- expected "
            f"{hint('spec.workflow.file')}"
        )
    workflow = load_workflow(workflow_path)
    problem = load_problem_spec(raw, project_path)
    experiments = load_experiment_specs(raw, project_path)
    metadata = _require_mapping(
        raw,
        "metadata",
        path=project_path,
        location="metadata",
        expected=hint("metadata"),
    )
    return StudyProject(
        name=_require(
            metadata,
            "name",
            path=project_path,
            location="metadata.name",
            expected=hint("metadata.name"),
        ),
        version=_require(
            metadata,
            "version",
            path=project_path,
            location="metadata.version",
            expected=hint("metadata.version"),
        ),
        path=project_path,
        root=root,
        base_dir=base_dir,
        path_base=path_base,
        raw=raw,
        problem=problem,
        experiments=experiments,
        workflow=workflow,
    )

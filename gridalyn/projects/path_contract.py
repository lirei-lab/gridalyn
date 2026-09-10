"""Every path a project declares must name a file inside that project.

A study declares paths in two files and resolves them against two bases. The
loader resolves ``base_dir`` from ``spec.pathBase``: the project directory under
``pathBase: project``, the repository root under ``pathBase: repo``. The heavy
studies need the second because their stages run as ``python -m
projects.<study>...`` from the repo root. ``root`` is always the project
directory. The consumers split them like this:

======================================================  ============  ============
Declaration                                             Resolved by   Base
======================================================  ============  ============
``project.yaml`` spec.validation.requiredReports        sense_checks  ``root``
``project.yaml`` spec.validation.requiredFigures        sense_checks  ``root``
``project.yaml`` spec.validation.senseChecks[].report   sense_checks  ``root``
``project.yaml`` spec.validation.objectiveArtifacts     catalog       ``root``
``project.yaml`` spec.scenarios.index                   catalog       ``root``
``project.yaml`` spec.scenarios.artifacts.<kind>.path   catalog       ``root``
``workflow.yaml`` stages[].outputs                      runner        ``base_dir``
``workflow.yaml`` stages[].inputs                       (declared)    ``base_dir``
======================================================  ============  ============

Both bases are legitimate, and every in-repo study declares against its own
correctly -- measured 2026-09-10: 452 declared paths, 0 violations, and
re-measured after bd 6ns.2 part 2a moved 39 of them onto ``root``: still 452,
still 0. What was missing is anything that says so. A path written in the other
study's convention resolved somewhere real-looking, and the failure surfaced
much later as ``missing required report``, which names a symptom and sends the
reader looking for a file that was never the problem. The same shape, in the
catalog, was the ``base_path: '/.'`` defect fixed in 3c7c47b1.

**Two files, two bases, in a repo-based study.** Since bd 6ns.2 part 2a every
path in ``project.yaml`` resolves against ``root`` and is written
project-relative, whatever ``spec.pathBase`` says. ``workflow.yaml`` is the
exception that remains: under ``pathBase: repo`` its stage ``inputs`` and
``outputs`` still resolve against ``base_dir`` and are written repo-relative,
until the rest of 6ns.2 unifies them. An author copying a stage output's
``projects/<study>/`` prefix into ``project.yaml`` doubles the directory, and
this gate names the corrected declaration.

Before part 2a, ``requiredReports``, ``requiredFigures`` and sense-check
``report`` paths followed ``pathBase`` too. A repo-based study written that way
now reports each of them as a doubled prefix -- the breaking change recorded
in ``docs/reference/workflow-yaml.md``.

**Declared paths this gate deliberately does not check**, so its scope is not
read as wider than it is:

- ``spec.workflow.file`` -- resolved against ``base_dir``, but the loader fails
  with a located error when the file is missing, so it is already protected by
  existence.
- ``spec.artifacts.project`` -- nothing reads it. ``ProjectScript`` hardcodes
  the output directories and the runner fingerprints a fixed tuple, so gating
  it would lend authority to a declaration that already disagrees with both.
  Retired in 4099d023: no longer required, and removed from every study.
- ``spec.experiments[].artifacts`` -- parsed into ``ExperimentSpec`` and read by
  nothing.

This module checks the SHAPE, so it needs no outputs on disk and runs the same
in CI as on an operator machine. The invariant: resolved against the base its
consumer uses, a declared path lands inside ``root``, and not under a second
``projects/`` segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from gridalyn.projects.scenario_catalog import (
    ScenarioContractError,
    read_scenario_contract,
)

PROBLEM_OUTSIDE_PROJECT = "outside_project"
PROBLEM_DOUBLED_PREFIX = "doubled_prefix"

_ROOT_FIELDS: tuple[str, ...] = (
    "requiredReports",
    "requiredFigures",
    "objectiveArtifacts",
)
#: The base every ``project.yaml`` declaration resolves against, named so a
#: message never attributes one field's rule to another (bd 6ns.2).
_ROOT_LABEL = (
    "the project directory (every path in project.yaml is, whatever pathBase says)"
)
_STAGE_FIELDS: tuple[str, ...] = ("inputs", "outputs")

# Substituted for a by-file template's scenario token before resolving, so the
# path is checked as a path. The message keeps the template as written.
_PLACEHOLDER_SCENARIO_ID = "scenario"


@dataclass(frozen=True)
class PathContractViolation:
    """One declared path that does not name a file inside its project.

    Attributes:
        source: ``"project.yaml"`` or ``"workflow.yaml"``.
        location: The contract path of the declaration, e.g.
            ``spec.validation.requiredReports[0]``,
            ``spec.scenarios.artifacts.results.path`` or
            ``stages[analyze_x].outputs[2]``.
        declared: The string exactly as written.
        resolved: Where the consumer will actually look.
        problem: :data:`PROBLEM_OUTSIDE_PROJECT` or
            :data:`PROBLEM_DOUBLED_PREFIX`.
        base_label: Human name of the base this declaration resolves against.
        suggestion: The declaration that would name the intended file, when one
            can be derived; ``None`` otherwise.
    """

    source: str
    location: str
    declared: str
    resolved: Path
    problem: str
    base_label: str
    suggestion: str | None

    @property
    def message(self) -> str:
        """Return a located, remediating description of the violation.

        Returns:
            One sentence naming the file and key, where the path lands, why
            that is wrong for this base, and what to write instead.
        """
        where = f"{self.source}: {self.location} = {self.declared!r}"
        if self.problem == PROBLEM_DOUBLED_PREFIX:
            why = (
                f"resolves to {self.resolved}, repeating the project directory; "
                f"this declaration is relative to {self.base_label}, which "
                "already is the project directory"
            )
        else:
            why = (
                f"resolves to {self.resolved}, outside the project; this "
                f"declaration is relative to {self.base_label}"
            )
        remedy = (
            f"declare {self.suggestion!r}"
            if self.suggestion is not None
            else "declare the path relative to that base"
        )
        return f"{where} {why} -- {remedy}"


def find_path_contract_violations(
    *,
    root: Path,
    base_dir: Path,
    path_base: str,
    project_data: Mapping[str, Any],
    workflow_data: Mapping[str, Any] | None,
) -> list[PathContractViolation]:
    """Check every checked declaration against the base its consumer uses.

    Args:
        root: The project directory, i.e. the parent of ``project.yaml``.
        base_dir: The resolved ``spec.pathBase`` directory.
        path_base: The ``spec.pathBase`` value, used only to phrase messages.
        project_data: The parsed ``project.yaml``.
        workflow_data: The parsed ``workflow.yaml``, or ``None`` when it could
            not be read (its own error is reported elsewhere).

    Returns:
        Every violation, in declaration order. Empty when the project's
        declarations are all consistent with their bases.
    """
    root = root.resolve()
    base_dir = base_dir.resolve()
    base_label = _base_label(path_base)
    violations: list[PathContractViolation] = []

    spec = project_data.get("spec")
    spec = spec if isinstance(spec, Mapping) else {}
    validation = spec.get("validation") or {}
    violations.extend(
        _check_sense_check_reports(
            validation.get("senseChecks"),
            base=root,
            base_label=_ROOT_LABEL,
            root=root,
        )
    )
    for key in _ROOT_FIELDS:
        violations.extend(
            _check_list(
                validation.get(key),
                source="project.yaml",
                location=f"spec.validation.{key}",
                base=root,
                base_label=_ROOT_LABEL,
                root=root,
            )
        )
    violations.extend(_check_scenarios(spec, root=root))

    stages = ((workflow_data or {}).get("spec") or {}).get("stages") or []
    for stage in stages:
        if not isinstance(stage, Mapping):
            continue
        stage_id = stage.get("id", "?")
        for key in _STAGE_FIELDS:
            violations.extend(
                _check_list(
                    stage.get(key),
                    source="workflow.yaml",
                    location=f"stages[{stage_id}].{key}",
                    base=base_dir,
                    base_label=base_label,
                    root=root,
                )
            )
    return violations


def _check_sense_check_reports(
    rules: Any, *, base: Path, base_label: str, root: Path
) -> list[PathContractViolation]:
    """Check the ``report`` each declarative sense-check rule reads.

    ``sense_checks`` opens ``project.root / rule["report"]``, so unlike the
    plain path lists this field sits one level down, inside each rule.

    Args:
        rules: The declared ``spec.validation.senseChecks`` value; anything
            that is not a list of mappings is skipped, because the schema
            validator owns type errors.
        base: ``root``, the directory the rule reports resolve against.
        base_label: Human name for ``base``.
        root: The project directory the reports must land inside.

    Returns:
        Violations in the declared rule reports.
    """
    if not isinstance(rules, (list, tuple)):
        return []
    found: list[PathContractViolation] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            continue
        report = rule.get("report")
        if not isinstance(report, str):
            continue
        violation = _check_path(
            report,
            source="project.yaml",
            location=f"spec.validation.senseChecks[{index}].report",
            base=base,
            base_label=base_label,
            root=root,
        )
        if violation is not None:
            found.append(violation)
    return found


def _check_scenarios(
    spec: Mapping[str, Any], *, root: Path
) -> list[PathContractViolation]:
    """Check a study's scenario contract, which is always project-relative.

    Args:
        spec: The ``spec`` block of ``project.yaml``.
        root: The project directory the catalog resolves these paths against.

    Returns:
        Violations in the declared index and artifact templates. Empty when the
        study declares no scenarios, or when the block does not parse: a
        malformed contract is :func:`read_scenario_contract`'s to report, with
        its own located message, and checking the paths of a block that does
        not parse would report the wrong defect first.
    """
    try:
        contract = read_scenario_contract(spec, path=root / "project.yaml")
    except ScenarioContractError:
        return []
    if contract is None:
        return []
    label = (
        "the project directory (spec.scenarios paths always are, whatever "
        "pathBase says)"
    )
    candidates = [("spec.scenarios.index", contract.index, contract.index)]
    for artifact in contract.artifacts:
        candidates.append(
            (
                f"spec.scenarios.artifacts.{artifact.kind}.path",
                artifact.template,
                artifact.resolve(_PLACEHOLDER_SCENARIO_ID),
            )
        )
    found: list[PathContractViolation] = []
    for location, declared, resolvable in candidates:
        violation = _check_path(
            declared,
            source="project.yaml",
            location=location,
            base=root,
            base_label=label,
            root=root,
            resolvable=resolvable,
        )
        if violation is not None:
            found.append(violation)
    return found


def _check_list(
    items: Any,
    *,
    source: str,
    location: str,
    base: Path,
    base_label: str,
    root: Path,
) -> list[PathContractViolation]:
    """Check one declared list of paths.

    Args:
        items: The declared value; anything that is not a list of strings is
            skipped, because the schema validator owns type errors.
        source: File the list was declared in.
        location: Contract path of the list.
        base: Directory the consumer resolves these entries against.
        base_label: Human name for ``base``.
        root: The project directory the entries must land inside.

    Returns:
        Violations found in this list.
    """
    if not isinstance(items, (list, tuple)):
        return []
    found: list[PathContractViolation] = []
    for index, declared in enumerate(items):
        if not isinstance(declared, str):
            continue
        violation = _check_path(
            declared,
            source=source,
            location=f"{location}[{index}]",
            base=base,
            base_label=base_label,
            root=root,
        )
        if violation is not None:
            found.append(violation)
    return found


def _check_path(
    declared: str,
    *,
    source: str,
    location: str,
    base: Path,
    base_label: str,
    root: Path,
    resolvable: str | None = None,
) -> PathContractViolation | None:
    """Check one declared path.

    Args:
        declared: The path exactly as written, kept for the message.
        source: File it was declared in.
        location: Contract path of the declaration.
        base: Directory the consumer resolves it against.
        base_label: Human name for ``base``.
        root: The project directory it must land inside.
        resolvable: What to resolve instead of ``declared``, when the written
            form carries a placeholder. Defaults to ``declared``.

    Returns:
        The violation, or ``None`` when the path is well-formed for its base.
        Absolute paths are skipped: they name no base to be wrong about.
    """
    target = declared if resolvable is None else resolvable
    if Path(target).is_absolute():
        return None
    resolved = (base / target).resolve()
    problem = _problem(resolved, root)
    if problem is None:
        return None
    return PathContractViolation(
        source=source,
        location=location,
        declared=declared,
        resolved=resolved,
        problem=problem,
        base_label=base_label,
        suggestion=_suggest(declared, base=base, root=root),
    )


def _problem(resolved: Path, root: Path) -> str | None:
    """Classify where a resolved path landed relative to its project.

    Args:
        resolved: The absolute path a consumer will open.
        root: The project directory.

    Returns:
        A ``PROBLEM_*`` constant, or ``None`` when the path is inside the
        project and not re-prefixed.
    """
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return PROBLEM_OUTSIDE_PROJECT
    if relative.parts and relative.parts[0] == "projects":
        return PROBLEM_DOUBLED_PREFIX
    return None


def _suggest(declared: str, *, base: Path, root: Path) -> str | None:
    """Derive the declaration that names the intended file, if unambiguous.

    Args:
        declared: The path as written, placeholders included.
        base: The base it is resolved against.
        root: The project directory.

    Returns:
        The corrected declaration, or ``None`` when the intended file cannot be
        inferred from the string alone.
    """
    parts = PurePosixPath(declared).parts
    project_tail = ("projects", root.name)
    # Written repo-relative, resolved against the project directory.
    if parts[:2] == project_tail and base == root:
        return str(PurePosixPath(*parts[2:])) if len(parts) > 2 else None
    # Written project-relative, resolved against the repo root.
    if parts[:1] != ("projects",) and base != root:
        try:
            prefix = root.relative_to(base)
        except ValueError:
            return None
        return str(PurePosixPath(*prefix.parts, *parts))
    return None


def _base_label(path_base: str) -> str:
    """Name the ``base_dir`` a ``pathBase`` value selects.

    Args:
        path_base: ``"project"`` or ``"repo"``.

    Returns:
        A phrase for messages.
    """
    if path_base == "repo":
        return "the repository root (pathBase: repo)"
    return "the project directory (pathBase: project)"


__all__ = [
    "PROBLEM_DOUBLED_PREFIX",
    "PROBLEM_OUTSIDE_PROJECT",
    "PathContractViolation",
    "find_path_contract_violations",
]

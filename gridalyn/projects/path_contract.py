"""Every path a project declares must name a file inside that project.

A study declares paths in two files and resolves them against two bases. The
loader resolves ``base_dir`` from ``spec.pathBase``: the project directory under
``pathBase: project``, the repository root under ``pathBase: repo``. The heavy
studies need the second because their stages run as ``python -m
projects.<study>...`` from the repo root. ``root`` is always the project
directory. Today the consumers split them like this:

=========================================  ============  ======================
Declaration                                Resolved by   Base
=========================================  ============  ======================
``project.yaml`` validation.requiredReports  sense_checks  ``base_dir``
``project.yaml`` validation.requiredFigures  sense_checks  ``base_dir``
``project.yaml`` validation.objectiveArtifacts  catalog    ``root``
``workflow.yaml`` stages[].outputs           runner        ``base_dir``
``workflow.yaml`` stages[].inputs            (declared)    ``base_dir``
=========================================  ============  ======================

Both bases are legitimate, and every in-repo study declares against its own
correctly -- measured 2026-09-10: 446 declared paths, 0 violations. What was
missing is anything that says so. A path written in the other study's
convention resolved somewhere real-looking, and the failure surfaced much later
as ``missing required report``, which names a symptom and sends the reader
looking for a file that was never the problem. The same shape, in the catalog,
was the ``base_path: '/.'`` defect fixed in 3c7c47b1.

This module checks the SHAPE, so it needs no outputs on disk and runs the same
in CI as on an operator machine. The invariant: resolved against the base its
consumer uses, a declared path lands inside ``root``, and not under a second
``projects/`` segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

PROBLEM_OUTSIDE_PROJECT = "outside_project"
PROBLEM_DOUBLED_PREFIX = "doubled_prefix"

_BASE_DIR_FIELDS: tuple[str, ...] = ("requiredReports", "requiredFigures")
_ROOT_FIELDS: tuple[str, ...] = ("objectiveArtifacts",)
_STAGE_FIELDS: tuple[str, ...] = ("inputs", "outputs")


@dataclass(frozen=True)
class PathContractViolation:
    """One declared path that does not name a file inside its project.

    Attributes:
        source: ``"project.yaml"`` or ``"workflow.yaml"``.
        location: The contract path of the declaration, e.g.
            ``spec.validation.requiredReports[0]`` or
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
    """Check every declared path against the base its consumer resolves it by.

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

    validation = (project_data.get("spec") or {}).get("validation") or {}
    for key in _BASE_DIR_FIELDS:
        violations.extend(
            _check_list(
                validation.get(key),
                source="project.yaml",
                location=f"spec.validation.{key}",
                base=base_dir,
                base_label=base_label,
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
                base_label="the project directory (objectiveArtifacts always are)",
                root=root,
            )
        )

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
        if not isinstance(declared, str) or Path(declared).is_absolute():
            continue
        resolved = (base / declared).resolve()
        problem = _problem(resolved, root)
        if problem is None:
            continue
        found.append(
            PathContractViolation(
                source=source,
                location=f"{location}[{index}]",
                declared=declared,
                resolved=resolved,
                problem=problem,
                base_label=base_label,
                suggestion=_suggest(declared, base=base, root=root),
            )
        )
    return found


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
        declared: The path as written.
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

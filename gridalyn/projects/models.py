from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.roots import ProjectDir


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    role: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProblemSpec:
    type: str
    dataset: str
    environment: str
    objective: str
    model: dict[str, Any]
    scenarios: tuple[ScenarioSpec, ...]


@dataclass(frozen=True)
class ExperimentSpec:
    id: str
    objective: str = ""
    scenario: str | None = None
    scenarios: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    model: str | None = None
    artifacts: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowStage:
    id: str
    command: str
    needs: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    path: Path
    stages: tuple[WorkflowStage, ...]


@dataclass(frozen=True)
class StudyProject:
    """A loaded study: its identity, contract and the directories it involves.

    Attributes:
        root: The study's own directory, the parent of ``project.yaml``. Every
            path the study declares resolves against it (bd 6ns.2), and it is
            what to pass wherever a :class:`ProjectDir` is required.
        base_dir: The directory the runner starts stage commands in -- the
            workspace root under ``pathBase: repo``, ``root`` otherwise. It is a
            working directory, not a root: it equals the workspace root for
            only some studies, so passing it where a
            :class:`WorkspaceRoot` is required is right by coincidence (bd 7rt).
        path_base: The ``spec.pathBase`` value that chose ``base_dir``.
    """

    name: str
    version: str
    path: Path
    root: ProjectDir
    base_dir: Path
    path_base: str
    raw: dict[str, Any]
    problem: ProblemSpec
    experiments: tuple[ExperimentSpec, ...]
    workflow: WorkflowSpec


@dataclass
class ValidationReport:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.valid = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

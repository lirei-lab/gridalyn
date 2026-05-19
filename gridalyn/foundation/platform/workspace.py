"""Workspace and artifact layout contracts for Gridalyn."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _looks_like_workspace(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / "gridalyn").is_dir()
        and (path / "projects").is_dir()
    )


def _usable_start_path(start: Path | str) -> Path:
    path = Path(start).resolve()
    if path.exists() and path.is_file():
        return path.parent
    if path.exists():
        return path
    return path.parent


def find_workspace_root(start: Path | str = ".") -> Path:
    """Discover a Gridalyn workspace from a nested path.

    Git metadata is useful during development, but public archives should also
    work cleanly. The marker walk keeps source distributions independent from a
    local repository checkout.
    """

    start_path = _usable_start_path(start)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            candidate = Path(result.stdout.strip()).resolve()
            if _looks_like_workspace(candidate):
                return candidate
    except OSError:
        pass

    for candidate in (start_path, *start_path.parents):
        if _looks_like_workspace(candidate):
            return candidate
    return start_path


@dataclass(frozen=True)
class ArtifactLayout:
    """Canonical artifact paths for a Gridalyn workspace."""

    root: Path | str = "."

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def digital_twin(self) -> Path:
        return self.root / "digital_twin"

    @property
    def cache(self) -> Path:
        return self.digital_twin / "cache"

    @property
    def base(self) -> Path:
        return self.digital_twin / "base"

    @property
    def scenarios(self) -> Path:
        return self.digital_twin / "scenarios"

    @property
    def timeseries(self) -> Path:
        return self.digital_twin / "timeseries"

    @property
    def models(self) -> Path:
        return self.digital_twin / "models"

    @property
    def semantic(self) -> Path:
        return self.digital_twin / "semantic"

    @property
    def reports(self) -> Path:
        return self.digital_twin / "reports"

    @property
    def dashboard(self) -> Path:
        return self.digital_twin / "dashboard"

    @property
    def flexibility(self) -> Path:
        return self.digital_twin / "flexibility"

    @property
    def operations(self) -> Path:
        return self.digital_twin / "operations"

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def instances(self) -> Path:
        return self.root / "instances"

    @property
    def default_instance(self) -> Path:
        return self.instances / "default"

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def examples_generated(self) -> Path:
        return self.root / "examples" / "generated"

    def project(self, name: str) -> Path:
        return self.projects / name

    def project_outputs(self, name: str) -> Path:
        return self.project(name) / "outputs"


@dataclass(frozen=True)
class GridalynWorkspace:
    """A repository or application workspace using Gridalyn artifact contracts."""

    root: Path | str = "."

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "layout", ArtifactLayout(self.root))

    layout: ArtifactLayout = field(init=False)

    @classmethod
    def discover(cls, start: Path | str = ".") -> GridalynWorkspace:
        return cls(find_workspace_root(start))

    def project_paths(self) -> list[Path]:
        projects_root = self.layout.projects
        if not projects_root.exists():
            return []
        return [
            path
            for path in sorted(projects_root.iterdir())
            if path.is_dir() and (path / "project.yaml").exists()
        ]

    def project_path(self, name: str) -> Path:
        return self.layout.project(name)


def workspace_from_root(root: Path | str = ".") -> GridalynWorkspace:
    """Create a workspace object from a repository root."""

    return GridalynWorkspace(root)


def workspace_from_path(start: Path | str = ".") -> GridalynWorkspace:
    """Create a workspace object by discovering the nearest Gridalyn root."""

    return GridalynWorkspace.discover(start)


__all__ = [
    "ArtifactLayout",
    "GridalynWorkspace",
    "find_workspace_root",
    "workspace_from_path",
    "workspace_from_root",
]

"""Workspace and artifact layout contracts for Gridalyn."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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


__all__ = ["ArtifactLayout", "GridalynWorkspace", "workspace_from_root"]

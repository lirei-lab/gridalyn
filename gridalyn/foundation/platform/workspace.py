"""Workspace and artifact layout contracts for Gridalyn."""

from __future__ import annotations

import os
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


def _has_git_metadata(start: Path) -> bool:
    """Report whether ``start`` or any parent holds a ``.git`` entry.

    Args:
        start: Directory the workspace walk begins from.

    Returns:
        True when a checkout is plausibly in scope, so shelling out to ``git``
        is worth the process spawn. A worktree or submodule records ``.git`` as
        a file rather than a directory, so both are accepted.
    """
    return any((candidate / ".git").exists() for candidate in (start, *start.parents))


def find_workspace_root(start: Path | str = ".") -> Path:
    """Discover a Gridalyn workspace from a nested path.

    Git metadata is useful during development, but public archives should also
    work cleanly. The marker walk keeps source distributions independent from a
    local repository checkout.
    """

    start_path = _usable_start_path(start)
    # Only spawn git when a checkout is actually in scope. Path resolution in
    # this layer should not fork a process for an installed wheel or a container
    # with no repository, and ``artifacts.py`` already guards its own git call
    # the same way.
    if _has_git_metadata(start_path):
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
    """Canonical artifact paths for a Gridalyn workspace.

    A workspace can materialize more than one digital twin. The ``instance``
    field selects which named twin under ``<root>/instances/`` the layout
    points at; ``"default"`` is the canonical workspace twin and the
    unchanged default for existing callers. Commands, scripts, tests,
    documentation, and dashboard mounts resolve through
    ``ArtifactLayout(root, instance=...)`` so that ``gridalyn twin`` is a
    general mechanism for *any* twin of *any* project, not a single
    hard-wired instance.
    """

    root: Path | str = "."
    instance: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        if not isinstance(self.instance, str) or not self.instance.strip():
            raise ValueError(
                f"instance must be a non-empty name, got {self.instance!r}"
            )
        object.__setattr__(self, "instance", self.instance)

    @property
    def digital_twin(self) -> Path:
        return self.instance_dir / "digital_twin"

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
    def observations(self) -> Path:
        """Directory a deployment's MEASURED observations are read from.

        The one artifact directory whose contents this repo never ships. The
        SDK ships the ingest *path* -- ``gridalyn.twin.observation.ingest`` --
        and a deployment becomes a digital *shadow* when its operator puts
        their own AMI/SCADA export here alongside the entity join. Naming the
        location in the layout is what lets the catalog say "there are none,
        and here is where they would go" rather than leaving a consumer to
        guess whether it looked in the right place.
        """
        return self.digital_twin / "observations"

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
    def instance_dir(self) -> Path:
        """Directory of the selected named twin instance."""

        return self.instances / self.instance

    @property
    def default_instance(self) -> Path:
        """Legacy alias for the canonical ``default`` instance directory."""

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
    instance: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "instance", self.instance or "default")
        object.__setattr__(self, "layout", ArtifactLayout(self.root, self.instance))

    layout: ArtifactLayout = field(init=False)

    @classmethod
    def discover(
        cls, start: Path | str = ".", *, instance: str = "default"
    ) -> GridalynWorkspace:
        return cls(find_workspace_root(start), instance=instance)

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


def layout_from_environment(
    *,
    default_root: Path | str = ".",
    instance_env: str = "GRIDALYN_INSTANCE",
    root_env: str = "GRIDALYN_WORKSPACE_ROOT",
) -> ArtifactLayout:
    """Resolve a twin layout from CLI-threaded environment variables.

    ``gridalyn twin`` sets ``GRIDALYN_WORKSPACE_ROOT`` and
    ``GRIDALYN_INSTANCE`` before dispatching a layer script, so every twin
    layer script can materialize on *any* named instance of *any* workspace
    without knowing the workspace root or instance itself. When the variables
    are unset (scripts run directly), the layout falls back to the script's
    own default root and the canonical ``default`` instance — unchanged from
    pre-generalization behaviour.
    """

    instance = os.environ.get(instance_env) or "default"
    root = os.environ.get(root_env) or str(default_root)
    return ArtifactLayout(root, instance=instance)


def workspace_from_root(
    root: Path | str = ".", *, instance: str = "default"
) -> GridalynWorkspace:
    """Create a workspace object from a repository root."""

    return GridalynWorkspace(root, instance=instance)


def workspace_from_environment(
    *,
    default_root: Path | str = ".",
    instance_env: str = "GRIDALYN_INSTANCE",
    root_env: str = "GRIDALYN_WORKSPACE_ROOT",
) -> GridalynWorkspace:
    """Resolve a twin workspace from CLI-threaded environment variables.

    Companion to :func:`layout_from_environment` for scripts that bind a
    ``GridalynWorkspace`` instead of a bare layout (e.g. the base exporter).
    """

    layout = layout_from_environment(
        default_root=default_root,
        instance_env=instance_env,
        root_env=root_env,
    )
    return GridalynWorkspace(layout.root, instance=layout.instance)


def workspace_from_path(
    start: Path | str = ".", *, instance: str = "default"
) -> GridalynWorkspace:
    """Create a workspace object by discovering the nearest Gridalyn root."""

    return GridalynWorkspace.discover(start, instance=instance)


__all__ = [
    "ArtifactLayout",
    "GridalynWorkspace",
    "find_workspace_root",
    "layout_from_environment",
    "workspace_from_environment",
    "workspace_from_path",
    "workspace_from_root",
]

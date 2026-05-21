"""Standard project output workspace helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OUTPUT_DIRECTORIES: tuple[str, ...] = (
    "outputs/data",
    "outputs/figures",
    "outputs/manifests",
    "outputs/operations",
    "outputs/reports",
    "outputs/cache",
)


@dataclass(frozen=True)
class ProjectWorkspacePreparation:
    """Result of preparing a project output workspace."""

    root: Path
    created_directories: tuple[str, ...]
    matplotlib_cache: Path

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "root": str(self.root),
            "created_directories": list(self.created_directories),
            "matplotlib_cache": str(self.matplotlib_cache),
        }


def prepare_project_workspace(
    root: Path | str = ".",
    output_directories: tuple[str, ...] = DEFAULT_OUTPUT_DIRECTORIES,
) -> ProjectWorkspacePreparation:
    """Create standard output directories for a governed project."""
    project_root = Path(root)
    for relative in output_directories:
        (project_root / relative).mkdir(parents=True, exist_ok=True)
    matplotlib_cache = project_root / "outputs" / "cache" / "matplotlib"
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache.resolve()))
    return ProjectWorkspacePreparation(
        root=project_root,
        created_directories=output_directories,
        matplotlib_cache=matplotlib_cache,
    )


__all__ = [
    "DEFAULT_OUTPUT_DIRECTORIES",
    "ProjectWorkspacePreparation",
    "prepare_project_workspace",
]

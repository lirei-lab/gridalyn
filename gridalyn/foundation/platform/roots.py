"""The roots a Gridalyn path can be relative to, as distinct types (bd 6ns.1).

``WorkspaceRoot`` is the directory holding ``pyproject.toml``, ``gridalyn/``,
``projects/`` and ``instances/``. ``ProjectDir`` is one study's directory, the
parent of its ``project.yaml``. They coincide for no study, and a path computed
from the wrong one resolves somewhere real-looking: that is how bd 7rt wrote
21 MB under ``projects/<study>/projects/<study>/outputs``. As ``NewType`` they
cost nothing at run time and let mypy reject one where the other is required.

``BaseArtifactDir`` is the canonical base-artifact directory of one instance,
``<workspace>/instances/<instance>/digital_twin/base``. It is named for its role
in :class:`ArtifactLayout` rather than for ``gridalyn.twin``, which is its main
reader but not its owner: the layout is a general mechanism over named
instances. It is not ``StudyProject.base_dir``, which is the directory stage
commands run in.
"""

from __future__ import annotations

from pathlib import Path
from typing import NewType

WorkspaceRoot = NewType("WorkspaceRoot", Path)
ProjectDir = NewType("ProjectDir", Path)
BaseArtifactDir = NewType("BaseArtifactDir", Path)

__all__ = ["BaseArtifactDir", "ProjectDir", "WorkspaceRoot"]

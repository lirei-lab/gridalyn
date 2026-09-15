"""The roots a Gridalyn path can be relative to, as distinct types (bd 6ns.1).

``WorkspaceRoot`` is the directory holding ``pyproject.toml``, ``gridalyn/``,
``projects/`` and ``instances/``. ``ProjectDir`` is one study's directory, the
parent of its ``project.yaml``. They coincide for no study, and a path computed
from the wrong one resolves somewhere real-looking: that is how bd 7rt wrote
21 MB under ``projects/<study>/projects/<study>/outputs``. As ``NewType`` they
cost nothing at run time and let mypy reject one where the other is required.
"""

from __future__ import annotations

from pathlib import Path
from typing import NewType

WorkspaceRoot = NewType("WorkspaceRoot", Path)
ProjectDir = NewType("ProjectDir", Path)

__all__ = ["ProjectDir", "WorkspaceRoot"]

"""Study-local serialization and labeling helpers for ``flexibility_cls``.

These are verbatim copies of pure helper bodies that live interior to the
``gridalyn.operations`` package (``relpath`` / ``json_default`` in
``operations/artifacts.py`` and ``scenario_label`` in
``operations/clearing/engine_mode.py``). They are relocated here (D-03) so the
study's serialization/labeling is study-local and does not reach past the
canonical facade. The originals remain interior to the SDK; copying the bodies
verbatim keeps the study's output (and the 74-metric regression baseline)
byte-identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def relpath(path: Path, root: Path) -> str:
    """Return a root-relative path when possible."""

    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def json_default(value: Any) -> Any:
    """JSON fallback for datetime-like objects."""

    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def scenario_label(index: int, ev_percent: int) -> str:
    """Return the canonical EV scenario label used by study reports."""

    return f"S{int(index)}_{int(ev_percent)}pct"

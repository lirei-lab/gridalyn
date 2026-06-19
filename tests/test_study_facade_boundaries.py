"""Study-code facade-only import boundary for ``flexibility_cls`` (D-04 gate).

This is an AST file-set scan (analog of
``tests/test_operations_boundaries.py``) over the
``projects/flexibility_cls/scripts/`` tree. After the Phase-4 migration, every
study script must import operations symbols **only** through the canonical
top-level ``gridalyn.operations`` facade. Reaching past it into any interior
module — the legacy ``operations.flexibility`` / ``operations.market`` shim
packages, or any concept submodule (``operations.replay``,
``operations.clearing.*``, ``operations.verification``, ``operations.artifacts``)
— is forbidden. The single predicate allows the bare ``gridalyn.operations``
facade exactly and rejects ``gridalyn.operations.<anything>``.

Scope note: this guard covers **study code only** (the ``flexibility_cls``
scripts tree). Unit tests whose subject *is* an interior module are out of
scope — they legitimately import the interior under test and are migrated
separately (Plan 03 Bucket B). The ``tests/`` tree is deliberately not scanned.
The study-local ``projects.flexibility_cls.scripts._serialize`` import is allowed
because it is not a ``gridalyn.operations.*`` module.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STUDY_SCRIPTS_DIR = _REPO_ROOT / "projects" / "flexibility_cls" / "scripts"


def test_study_scripts_import_operations_only_via_facade() -> None:
    """No flexibility_cls study script imports a gridalyn.operations submodule."""
    violations: list[str] = []
    for path in sorted(_STUDY_SCRIPTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if (
                    module.startswith("gridalyn.operations.")
                    and module != "gridalyn.operations"
                ):
                    violations.append(f"{path}: {module}")

    assert violations == [], violations

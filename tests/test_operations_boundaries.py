"""Layer-direction + lazy-import-purity gate for operations (D-04 gate #3).

Two cases:

* :func:`test_operations_imports_only_downward_layers` is an AST scan
  (analog of ``tests/test_asset_modeling_boundaries.py``) over the whole
  ``gridalyn/operations/`` tree. The operations layer sits below ``projects``
  and ``interfaces``, so it must never import upward into them. Downward layers
  (``foundation``, ``twin``, ``assets``, ``simulation``) are allowed. The scan
  rglobs the entire tree so it automatically covers the
  ``gridalyn/operations/clearing/`` package once it is introduced in a later
  sub-merge.
* :func:`test_importing_operations_loads_no_heavy_optional_deps` is a
  subprocess lazy-purity check (analog of
  ``tests/test_operations_contract.py``) asserting that importing
  ``gridalyn.operations`` pulls in none of the heavy optional capability
  modules.

Scope note: forbidding re-imports of ``operations.flexibility`` /
``operations.market`` (the forbid-reintroduction assertion) is Phase 5 /
CLEAN-02 and is deliberately NOT enforced here — shims keep those paths alive
during this phase.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPERATIONS_DIR = _REPO_ROOT / "gridalyn" / "operations"

# Operations sits below projects/interfaces; importing upward into them breaks
# the strict downward layer direction. Downward layers are intentionally absent.
_FORBIDDEN_UPWARD_PREFIXES = (
    "gridalyn.projects",
    "gridalyn.interfaces",
)

# Heavy optional capabilities that must stay deferred (lazy) on facade import.
_HEAVY_OPTIONAL_MODULES = (
    "pandapower",
    "lightsim2grid",
    "cvxpy",
    "scipy",
    "matplotlib",
)


def test_operations_imports_only_downward_layers() -> None:
    """No module under gridalyn/operations/ imports upward into higher layers."""
    violations: list[str] = []
    for path in sorted(_OPERATIONS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in _FORBIDDEN_UPWARD_PREFIXES
                ):
                    violations.append(f"{path}: {module}")

    assert violations == [], violations


def test_importing_operations_loads_no_heavy_optional_deps() -> None:
    """Importing gridalyn.operations loads no heavy optional capability module."""
    heavy = ", ".join(repr(name) for name in _HEAVY_OPTIONAL_MODULES)
    code = (
        "import sys\n"
        "import gridalyn\n"
        "import gridalyn.operations\n"
        f"heavy = [m for m in ({heavy},) if m in sys.modules]\n"
        "assert heavy == [], heavy\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr

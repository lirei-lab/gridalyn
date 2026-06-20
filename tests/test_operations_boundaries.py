"""Layer-direction, forbid-reintroduction, and lazy-import-purity gate.

Three cases:

* :func:`test_operations_imports_only_downward_layers` is an AST scan
  (analog of ``tests/test_asset_modeling_boundaries.py``) over the whole
  ``gridalyn/operations/`` tree. The operations layer sits below ``projects``
  and ``interfaces``, so it must never import upward into them. Downward layers
  (``foundation``, ``twin``, ``assets``, ``simulation``) are allowed.
* :func:`test_no_module_reintroduces_legacy_operations_packages` is a repo-wide
  AST scan (CLEAN-02) over ``gridalyn/``, ``projects/``, and ``tests/`` that
  fails on any import/from whose module equals or starts with a forbidden
  ``gridalyn.operations.{flexibility,market}`` prefix. Those duplicate packages
  were deleted in Phase 5; this guard prevents them from ever coming back.
* :func:`test_importing_operations_loads_no_heavy_optional_deps` is a
  subprocess lazy-purity check (analog of
  ``tests/test_operations_contract.py``) asserting that importing
  ``gridalyn.operations`` pulls in none of the heavy optional capability
  modules.
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

# Deleted duplicate packages (CLEAN-02). No module anywhere in the repo may
# import these again — the canonical homes are the concept modules / facade.
_FORBIDDEN_REINTRODUCED_PREFIXES = (
    "gridalyn.operations.flexibility",
    "gridalyn.operations.market",
)

# Source trees scanned repo-wide for re-introduced legacy imports.
_REINTRODUCTION_SCAN_DIRS = (
    _REPO_ROOT / "gridalyn",
    _REPO_ROOT / "projects",
    _REPO_ROOT / "tests",
)

# Heavy optional capabilities that must stay deferred (lazy) on facade import.
_HEAVY_OPTIONAL_MODULES = (
    "pandapower",
    "lightsim2grid",
    "cvxpy",
    "scipy",
    "matplotlib",
)


def _imported_modules(tree: ast.AST) -> list[str]:
    """Collect every imported module name from an AST."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_operations_imports_only_downward_layers() -> None:
    """No module under gridalyn/operations/ imports upward into higher layers."""
    violations: list[str] = []
    for path in sorted(_OPERATIONS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in _FORBIDDEN_UPWARD_PREFIXES
            ):
                violations.append(f"{path}: {module}")

    assert violations == [], violations


def test_no_module_reintroduces_legacy_operations_packages() -> None:
    """No module repo-wide re-imports the deleted operations.{flexibility,market}."""
    this_file = Path(__file__).resolve()
    violations: list[str] = []
    for scan_dir in _REINTRODUCTION_SCAN_DIRS:
        for path in sorted(scan_dir.rglob("*.py")):
            if path.resolve() == this_file:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module in _imported_modules(tree):
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in _FORBIDDEN_REINTRODUCED_PREFIXES
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

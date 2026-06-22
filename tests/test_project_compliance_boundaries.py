"""Project-script SDK-compliance import boundary gate (GUARD-01 + GUARD-02).

This is an AST file-set scan (analog of ``tests/test_study_facade_boundaries.py``
and ``tests/test_operations_boundaries.py``) over every project's ``scripts/``
tree. It permanently locks the Phase-6 SDK-compliance work so future studies
cannot drift back into two forbidden patterns:

* **GUARD-01 (deep private gridalyn import):** a ``gridalyn.*`` import whose path
  crosses an internal-implementation package segment (denylist seed:
  ``simulators``). Reaching past the blessed public sub-facades into an interior
  implementation module is forbidden. The Phase-6 breach that motivated this was
  ``gridalyn.simulation.simulators.powerflow.synthetic_network`` — what made it a
  violation is the internal ``simulators`` package, not its import depth.
* **GUARD-02 (eager heavy-dependency import):** a *module-scope* import whose root
  package is one of the optional heavy network/geo deps
  (``pandapower``, ``lightsim2grid``, ``geopandas``). Such usage must be deferred
  inside a function body and gated through ``require_capabilities`` — these
  capabilities are optional and must never be imported at module load time.
  Imports nested inside a function/method body are the sanctioned deferred
  pattern and are allowed.

Scope note (D-05): every ``*.py`` under all seven ``projects/*/scripts/`` trees
is scanned recursively, including helper modules (``network_model.py``,
``_serialize.py``, ``pipeline/`` / ``plotting/`` / ``reports/`` subpackages).
Scanning the already-compliant projects actively proves they stay clean.
``projects/*/__init__.py`` outside ``scripts/`` and the ``tests/`` tree are NOT
scanned.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# D-05: recursively scan every script in all seven projects' scripts/ trees.
# ``*/scripts/**/*.py`` matches every .py under each project's scripts/ tree
# (equivalent to a per-project ``rglob("*.py")``).
_PROJECT_SCRIPTS = sorted((_REPO_ROOT / "projects").glob("*/scripts/**/*.py"))

# D-03 seed denylist: package segments that mark gridalyn-internal implementation
# modules a project script must never reach into. ``simulators`` is the proven
# Phase-6 breach vector (under ``gridalyn.simulation``). The denylist is
# extensible, but each new marker MUST be verified non-shadowing against the
# blessed public sub-facades currently imported by compliant scripts (scripting,
# model_inputs, regression, capabilities, datagen, modeling.thermal, twin.io,
# twin.adapters.geojson) — otherwise the guard would fail the green tree.
_GRIDALYN_INTERNAL_MARKERS = ("simulators",)

# D-06 hardcoded heavy-dep set: deliberately NOT derived from
# ``gridalyn.foundation.platform.capabilities.OPTIONAL_CAPABILITY_MODULES``.
# Deriving the full optional set (sim=[pandapower, lightsim2grid],
# geo=[geopandas, osmnx, shapely], ops=[cvxpy, lightgbm]) would also forbid
# module-scope imports of optional deps that are NOT the roadmap's named heavy
# network/geo deps (e.g. cvxpy/lightgbm under ``ops`` or osmnx/shapely under
# ``geo``), which are legitimately allowed at module scope. This set matches the
# roadmap's named heavy network/geo dependencies exactly. (This module imports
# nothing from the capabilities module — the reference above is documentation.)
_FORBIDDEN_MODULE_SCOPE_ROOTS = ("pandapower", "lightsim2grid", "geopandas")


def _imported_modules(tree: ast.AST) -> list[str]:
    """Collect every imported module name from an AST (module-scope or nested).

    Mirrors the ``tests/test_operations_boundaries.py`` helper: walks the whole
    tree and normalizes both ``import x`` (alias names) and ``from x import y``
    (``node.module``) to module-path strings. GUARD-01 uses this directly because
    the denylist applies to imports anywhere, not only at module scope.

    For ``from x import y`` the imported *name* is also reconstructed as
    ``f"{x}.{y}"`` (WR-02): binding an internal package by name — e.g.
    ``from gridalyn.simulation import simulators`` — is the semantic equivalent of
    the deep-private breach GUARD-01 forbids, so the name-bound form must be
    visible to the denylist, not only the dotted path before ``import``. Relative
    imports (``from . import x``, where ``node.module`` is ``None``) are skipped to
    avoid crashing on a missing module path.

    Args:
        tree: The parsed module AST to inspect.

    Returns:
        Every imported module-path string found anywhere in the tree, including
        the reconstructed ``module.name`` of each ``from``-imported name.
    """
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _module_level_imports(tree: ast.AST) -> list[str]:
    """Collect only module-scope (non-function-nested) imported module names.

    Flat ``ast.walk`` loses parent context and cannot tell a module-scope import
    from one nested inside a function body. GUARD-02 needs that distinction
    (D-08): only imports whose nearest enclosing ``FunctionDef`` /
    ``AsyncFunctionDef`` ancestor is ``None`` are module-scope; imports inside a
    top-level ``if`` / ``try`` are still module-scope. This recursive walker
    therefore collects ``Import`` / ``ImportFrom`` at the surviving module-scope
    level and does NOT descend into function/async-function bodies.

    Args:
        tree: The parsed module AST to inspect.

    Returns:
        Every module-scope imported module-path string, normalized the same way
        as :func:`_imported_modules`.
    """
    modules: list[str] = []

    def _collect(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Deferred (function-nested) imports are allowed: do not recurse.
                continue
            if isinstance(child, ast.Import):
                modules.extend(alias.name for alias in child.names)
            elif isinstance(child, ast.ImportFrom) and child.module:
                modules.append(child.module)
            else:
                _collect(child)

    _collect(tree)
    return modules


def _is_deep_private_gridalyn_import(module: str) -> bool:
    """Return True when a gridalyn.* import crosses an internal-marker segment.

    GUARD-01 predicate (D-01..D-04). Non-``gridalyn`` imports are out of scope
    (GUARD-02 handles heavy third-party deps).

    Args:
        module: A dotted module-path string from an import statement.

    Returns:
        True iff ``module`` is under ``gridalyn.`` and any of its path segments
        is in :data:`_GRIDALYN_INTERNAL_MARKERS`.
    """
    if not module.startswith("gridalyn."):
        return False
    return any(seg in _GRIDALYN_INTERNAL_MARKERS for seg in module.split("."))


def _is_forbidden_heavy_root(module: str) -> bool:
    """Return True when a module's root package is a forbidden heavy dependency.

    GUARD-02 predicate (D-07): root-package match so it catches ``pandapower``,
    ``pandapower.networks``, ``geopandas``, ``lightsim2grid.*``, etc.

    Args:
        module: A dotted module-path string from an import statement.

    Returns:
        True iff ``module.split(".")[0]`` is in
        :data:`_FORBIDDEN_MODULE_SCOPE_ROOTS`.
    """
    return module.split(".")[0] in _FORBIDDEN_MODULE_SCOPE_ROOTS


def test_project_scripts_have_no_deep_private_gridalyn_imports() -> None:
    """No project script imports a gridalyn internal-implementation module.

    GUARD-01 file-set scan (D-01, D-05): applies the deep-private-import denylist
    to every import (module-scope or nested) across all seven
    ``projects/*/scripts/`` trees. Green on arrival on the post-Phase-6 tree.
    """
    violations: list[str] = []
    for path in _PROJECT_SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if _is_deep_private_gridalyn_import(module):
                violations.append(f"{path}: {module}")

    assert violations == [], violations


def test_project_scripts_have_no_eager_heavy_dependency_imports() -> None:
    """No project script imports an optional heavy dep at module scope.

    GUARD-02 file-set scan (D-06..D-08): classifies only module-scope imports and
    flags any whose root package is a forbidden heavy dependency, across all seven
    ``projects/*/scripts/`` trees. Function-nested (deferred) imports are allowed.
    Green on arrival on the post-Phase-6 tree.
    """
    violations: list[str] = []
    for path in _PROJECT_SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _module_level_imports(tree):
            if _is_forbidden_heavy_root(module):
                violations.append(f"{path}: {module}")

    assert violations == [], violations


def test_guard01_predicate_flags_phase6_breach_and_passes_public_facade() -> None:
    """GUARD-01 is non-vacuous: it flags the Phase-6 breach, not the facade (D-09).

    Exercises the predicate against in-memory synthetic source so the proof needs
    no committed real violation.
    """
    breach = "from gridalyn.simulation.simulators.powerflow import synthetic_network"
    breach_tree = ast.parse(breach)
    breach_flagged = [
        m for m in _imported_modules(breach_tree) if _is_deep_private_gridalyn_import(m)
    ]
    assert breach_flagged, "GUARD-01 must flag the Phase-6 deep-private breach"

    alias_breach = "import gridalyn.simulation.simulators.powerflow.synthetic_network"
    alias_tree = ast.parse(alias_breach)
    alias_flagged = [
        m for m in _imported_modules(alias_tree) if _is_deep_private_gridalyn_import(m)
    ]
    assert alias_flagged, "GUARD-01 must flag the alias-form deep-private breach"

    # WR-02: name-binding form. ``from gridalyn.simulation import simulators`` binds
    # the internal ``simulators`` package by name; ``node.module`` alone
    # (``gridalyn.simulation``) is clean, so the reconstructed ``module.name`` must
    # be what the denylist catches.
    name_breach = "from gridalyn.simulation import simulators"
    name_tree = ast.parse(name_breach)
    name_flagged = [
        m for m in _imported_modules(name_tree) if _is_deep_private_gridalyn_import(m)
    ]
    assert name_flagged, "GUARD-01 must flag the name-binding deep-private breach"

    # WR-02: relative ``from . import x`` has ``node.module is None`` and must be
    # handled without crashing (and must not be flagged).
    relative = "from . import helper"
    relative_flagged = [
        m
        for m in _imported_modules(ast.parse(relative))
        if _is_deep_private_gridalyn_import(m)
    ]
    assert (
        relative_flagged == []
    ), "GUARD-01 must not flag (or crash on) relative imports"

    clean = "from gridalyn.projects import scripting"
    clean_tree = ast.parse(clean)
    clean_flagged = [
        m for m in _imported_modules(clean_tree) if _is_deep_private_gridalyn_import(m)
    ]
    assert clean_flagged == [], "GUARD-01 must not flag the public facade import"


def test_guard02_flags_module_scope_heavy_import_and_allows_deferred_and_cvxpy() -> (
    None
):
    """GUARD-02 is non-vacuous and module-scope-discriminating (D-09).

    Module-scope heavy imports are flagged; the same import nested in a function
    body is allowed (deferred pattern, D-08); module-scope ``cvxpy`` is allowed
    (D-06 — intentionally outside the hardcoded set).
    """
    pos_alias = "import pandapower as pp"
    pos_alias_flagged = [
        m
        for m in _module_level_imports(ast.parse(pos_alias))
        if _is_forbidden_heavy_root(m)
    ]
    assert pos_alias_flagged, "GUARD-02 must flag module-scope 'import pandapower'"

    pos_from = "from pandapower.networks import case33bw"
    pos_from_flagged = [
        m
        for m in _module_level_imports(ast.parse(pos_from))
        if _is_forbidden_heavy_root(m)
    ]
    assert pos_from_flagged, "GUARD-02 must flag module-scope dotted heavy import"

    deferred = "def f():\n    import pandapower as pp\n    return pp\n"
    deferred_flagged = [
        m
        for m in _module_level_imports(ast.parse(deferred))
        if _is_forbidden_heavy_root(m)
    ]
    assert (
        deferred_flagged == []
    ), "GUARD-02 must allow function-nested deferred imports"

    cvxpy_ok = "import cvxpy"
    cvxpy_flagged = [
        m
        for m in _module_level_imports(ast.parse(cvxpy_ok))
        if _is_forbidden_heavy_root(m)
    ]
    assert cvxpy_flagged == [], "GUARD-02 must allow module-scope cvxpy (D-06)"

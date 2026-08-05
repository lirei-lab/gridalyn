"""Seven-layer downward-import direction gate for the ``gridalyn`` package.

The SDK advertises a strict downward layer direction::

    foundation -> twin -> assets -> simulation -> operations -> projects -> interfaces

A module living in layer *i* may import only layers whose index is ``<= i``.
Four pre-existing boundary tests (``test_asset_modeling_boundaries``,
``test_demo_modeling_boundaries``, ``test_operations_boundaries``,
``test_project_compliance_boundaries``) each police a hand-written subset of
the 21 ordered upward pairs, and all four walk ``ast.Import`` /
``ast.ImportFrom`` nodes only. An upward import written as a *string literal*
is therefore invisible to every one of them, so this module scans three
sources rather than one.

Five cases:

* :meth:`LayerDirectionTests.test_gridalyn_imports_only_downward_layers` is the
  gate. It walks every ``.py`` file under ``gridalyn/`` and fails with one line
  per violation, naming the file, both layers, and the detection source.
* :meth:`LayerDirectionTests.test_scanner_finds_known_good_downward_imports`
  is the non-vacuity guard against the real tree: a parser that silently
  extracted nothing would report "no violations", so the scanner must be shown
  to find the many legitimate downward edges that exist, *and* to extract very
  nearly every ``_LAZY_EXPORTS`` entry the tree actually declares.
* :meth:`LayerDirectionTests.test_extractors_read_string_literal_sources` proves
  the string-literal extractors work, using synthetic snippets rather than the
  live tree. It therefore keeps its meaning after the tree's only
  ``import_module`` string constant is resolved.
* :meth:`LayerDirectionTests.test_relative_and_facade_targets_resolve` pins the
  two resolution rules that are easy to get subtly wrong -- the package a
  relative import is measured from, and the root-facade form
  ``from gridalyn import <layer>`` -- because a wrong answer there is a
  green-making evasion rather than a mere blind spot.
* :meth:`LayerDirectionTests.test_dynamic_import_module_calls_are_measured`
  reports the gate's static blind spot: an import call with a non-constant
  argument cannot be resolved statically, so the count is asserted and surfaced
  instead of being quietly ignored.

Detection sources, in the order they are reported:

1. ``ast.Import`` / absolute ``ast.ImportFrom`` module names.
2. Relative ``ast.ImportFrom`` nodes, resolved against the package *containing*
   the file (which for a non-``__init__.py`` module is its parent directory,
   not its own dotted path). Relative imports are resolved rather than
   excluded: resolution is deterministic (the level count plus the containing
   package fully determine the target), and while the one that exists today is
   same-layer by construction, a form such as ``from ... import interfaces``
   inside ``gridalyn/foundation/platform/`` resolves to ``gridalyn.interfaces``
   and does cross a layer boundary, so excluding them would open a second blind
   spot.
3. String-literal first arguments to ``import_module(...)`` -- including a
   ``from importlib import import_module as _alias`` rebinding -- and to
   ``__import__(...)``.
4. String constants in a module-level ``_LAZY_EXPORTS`` mapping, whose values
   are ``(module_path, attribute_name)`` tuples. The mapping is read whether it
   is written as a plain assignment or as an annotated one
   (``_LAZY_EXPORTS: dict[str, tuple[str, str]] = {...}``).

Any ``from ... import <name>`` whose resolved target is exactly ``gridalyn`` is
expanded into ``gridalyn.<name>`` before layer resolution, because the root
``__init__``'s own ``_LAZY_EXPORTS`` publishes every layer under its bare name:
``from gridalyn import projects`` binds the projects layer just as surely as
``import gridalyn.projects`` does.

Exceptions are held in :data:`_DOCUMENTED_EXCEPTIONS`, keyed by
``(exact_relative_file_path, exact_target_module)``. There is deliberately no
support for wildcards, directory prefixes or layer-wide entries: an exception
that cannot name its own file and its own target is not an exception, it is a
hole. The gate additionally fails when an entry stops matching, so a crossing
that later gets fixed cannot leave a silent permission behind.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "gridalyn"

# Index position defines rank. A module in layer i may import only layers
# with index <= i.
_LAYER_ORDER: tuple[str, ...] = (
    "foundation",
    "twin",
    "assets",
    "simulation",
    "operations",
    "projects",
    "interfaces",
)
_LAYER_RANK: dict[str, int] = {name: index for index, name in enumerate(_LAYER_ORDER)}

_SOURCE_IMPORT = "import"
_SOURCE_RELATIVE = "relative import"
_SOURCE_IMPORT_MODULE = "import_module string"
_SOURCE_DUNDER_IMPORT = "__import__ string"
_SOURCE_LAZY_EXPORTS = "_LAZY_EXPORTS"

_ROOT_PACKAGE = "gridalyn"
_LAZY_EXPORTS_NAME = "_LAZY_EXPORTS"
_IMPORT_MODULE_NAME = "import_module"
_IMPORTLIB_NAME = "importlib"
_DUNDER_IMPORT_NAME = "__import__"

# Individually justified exceptions to the layer direction.
#
# Key: (repo-relative source file, exact dotted target module). Both halves are
# exact strings -- no globs, no directory prefixes, no "layer X may import layer
# Y". Value: why the inversion was not taken and what would remove the entry.
# The full rationale lives as a comment at each import site; these are the
# one-line summaries. Every entry must still match a real crossing, which
# ``test_gridalyn_imports_only_downward_layers`` asserts.
_DOCUMENTED_EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        "gridalyn/foundation/platform/validation.py",
        "gridalyn.projects.api",
    ): (
        "validate_workspace composes the repo-level artifact policy with the "
        "per-project contract check, so it spans both layers; it sits in "
        "foundation because gridalyn.foundation.validate_workspace is its "
        "published entry point. The import is call-time, so importing the "
        "module pulls no gridalyn.projects into sys.modules. Removed by "
        "relocating the published symbol into the projects layer and updating "
        "the two _LAZY_EXPORTS maps plus interfaces/cli/gridalyn.py."
    ),
    (
        "gridalyn/projects/workflows/scripts/generate_digital_twin_dashboard_catalog.py",
        "gridalyn.interfaces.reporting.dashboard_catalog",
    ): (
        "A stage-script entry point that interfaces/cli dispatches downward "
        "into via run_module_as_script, so this closes an "
        "interfaces -> projects -> interfaces cycle rather than acting as a "
        "composition root. Scoped to this one file and NOT to the scripts "
        "package: the other 21 modules there already obey the direction. "
        "Removed by relocating interfaces/reporting/dashboard_catalog.py to a "
        "layer at or below projects -- its only gridalyn import is "
        "gridalyn.twin.network -- and updating its importers."
    ),
}


@dataclass(frozen=True)
class _FileScan:
    """Every ``gridalyn.*`` target referenced by one source file.

    Attributes:
        targets: ``(dotted_module, detection_source)`` pairs, in walk order.
        dynamic_import_module_calls: ``import_module(...)`` calls whose first
            argument is not a string constant, and which are therefore
            statically unresolvable.
    """

    targets: tuple[tuple[str, str], ...]
    dynamic_import_module_calls: int


def _layer_of_module(dotted: str) -> str | None:
    """Return the layer named by a dotted module path, if any.

    The layer is the *second* dotted component only, so
    ``gridalyn.interfaces.cli.gridalyn`` resolves to ``interfaces`` and a
    non-layer target such as ``gridalyn.version`` resolves to ``None``.

    Args:
        dotted: A dotted module path, e.g. ``gridalyn.projects.api``.

    Returns:
        The layer name, or ``None`` when the path names no ``gridalyn`` layer.
    """
    parts = dotted.split(".")
    if len(parts) < 2 or parts[0] != "gridalyn":
        return None
    return parts[1] if parts[1] in _LAYER_RANK else None


def _module_parts(path: Path) -> tuple[str, ...]:
    """Return the dotted module path of a file, as a tuple of components."""
    relative = path.resolve().relative_to(_REPO_ROOT).with_suffix("")
    parts = relative.parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _package_parts(path: Path) -> tuple[str, ...]:
    """Return the dotted path of the package *containing* a file.

    This -- not the module's own dotted path -- is what a relative import is
    measured from. ``from . import x`` inside ``a/b/c.py`` means ``a.b.x``, so
    the trailing module name must be dropped for anything but ``__init__.py``
    (where :func:`_module_parts` has already dropped it).
    """
    parts = _module_parts(path)
    if path.name != "__init__.py" and parts:
        parts = parts[:-1]
    return parts


def _layer_of_path(path: Path) -> str | None:
    """Return the layer a source file belongs to, or ``None`` if it has none.

    ``gridalyn/__init__.py`` sits above every layer rather than inside one, so
    it resolves to ``None`` and is not itself constrained.
    """
    parts = _module_parts(path)
    if len(parts) < 2 or parts[0] != "gridalyn":
        return None
    return parts[1] if parts[1] in _LAYER_RANK else None


def _string_constant(node: ast.expr) -> str | None:
    """Return the value of a string-constant node, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _called_name(node: ast.Call) -> str | None:
    """Return the bare callee name of a call, handling attribute access.

    Resolves both ``import_module(...)`` and ``importlib.import_module(...)``
    to ``import_module``.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _expand_root_facade(
    dotted: str, node: ast.ImportFrom, source: str
) -> list[tuple[str, str]]:
    """Expand ``from gridalyn import <layer>`` into the layer it really binds.

    A target of exactly ``gridalyn`` names no layer on its own, but the root
    ``__init__``'s ``_LAZY_EXPORTS`` publishes every layer under its bare name,
    so each imported alias is a real dependency on ``gridalyn.<alias>``.
    """
    if dotted != _ROOT_PACKAGE:
        return [(dotted, source)]
    return [(f"{_ROOT_PACKAGE}.{alias.name}", source) for alias in node.names]


def _targets_from_import_from(
    node: ast.ImportFrom, package: tuple[str, ...]
) -> list[tuple[str, str]]:
    """Return targets for one ``from ... import ...`` node.

    Absolute imports are taken verbatim. Relative imports are resolved against
    ``package`` -- the package *containing* the file, per :func:`_package_parts`
    -- where level 1 means that package itself and each extra level strips one
    trailing component. Either way a bare ``gridalyn`` target is expanded into
    the layers its imported names bind.
    """
    level = node.level or 0
    if level == 0:
        if not node.module:
            return []
        return _expand_root_facade(node.module, node, _SOURCE_IMPORT)
    keep = len(package) - (level - 1)
    if keep < 0:
        return []
    base = list(package[:keep])
    if node.module:
        base.append(node.module)
    if not base:
        return []
    return _expand_root_facade(".".join(base), node, _SOURCE_RELATIVE)


def _lazy_exports_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    """Return the bare names assigned by a plain or annotated assignment."""
    if isinstance(node, ast.AnnAssign):
        target = node.target
        return [target.id] if isinstance(target, ast.Name) else []
    return [t.id for t in node.targets if isinstance(t, ast.Name)]


def _targets_from_lazy_exports(
    node: ast.Assign | ast.AnnAssign,
) -> list[tuple[str, str]]:
    """Return targets from a ``_LAZY_EXPORTS = {...}`` assignment.

    Values are ``(module_path, attribute_name)`` tuples; the module path is the
    first element. A bare string value is also accepted. Both the plain and the
    annotated assignment form are read -- four packages in the tree declare the
    map as ``_LAZY_EXPORTS: dict[str, tuple[str, str]] = {...}``, and reading
    only ``ast.Assign`` would make every one of their entries invisible.
    """
    names = _lazy_exports_names(node)
    if _LAZY_EXPORTS_NAME not in names or not isinstance(node.value, ast.Dict):
        return []
    targets: list[tuple[str, str]] = []
    for value in node.value.values:
        dotted: str | None = None
        if isinstance(value, (ast.Tuple, ast.List)) and value.elts:
            dotted = _string_constant(value.elts[0])
        else:
            dotted = _string_constant(value)
        if dotted is not None:
            targets.append((dotted, _SOURCE_LAZY_EXPORTS))
    return targets


def _import_module_aliases(tree: ast.AST) -> set[str]:
    """Return every local name bound to ``importlib.import_module``.

    ``from importlib import import_module as _imp`` renames the call, which
    would otherwise hide both its resolvable and its dynamic uses from the
    scan. The canonical name is always included.
    """
    aliases = {_IMPORT_MODULE_NAME}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != _IMPORTLIB_NAME:
            continue
        for alias in node.names:
            if alias.name == _IMPORT_MODULE_NAME and alias.asname:
                aliases.add(alias.asname)
    return aliases


def _scan_tree(tree: ast.AST, package: tuple[str, ...]) -> _FileScan:
    """Collect every referenced module target from one parsed module."""
    targets: list[tuple[str, str]] = []
    dynamic = 0
    import_module_names = _import_module_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend((alias.name, _SOURCE_IMPORT) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.extend(_targets_from_import_from(node, package))
        elif isinstance(node, ast.Call):
            called = _called_name(node)
            if called in import_module_names:
                source = _SOURCE_IMPORT_MODULE
            elif called == _DUNDER_IMPORT_NAME:
                source = _SOURCE_DUNDER_IMPORT
            else:
                continue
            dotted = _string_constant(node.args[0]) if node.args else None
            if dotted is None:
                dynamic += 1
            else:
                targets.append((dotted, source))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets.extend(_targets_from_lazy_exports(node))
    return _FileScan(targets=tuple(targets), dynamic_import_module_calls=dynamic)


def _scan_file(path: Path) -> _FileScan:
    """Parse and scan one source file. Raises ``SyntaxError`` if unparsable."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _scan_tree(tree, _package_parts(path))


def _package_files() -> list[Path]:
    """Return every scannable ``.py`` file under ``gridalyn/``."""
    return sorted(
        path for path in _PACKAGE_DIR.rglob("*.py") if "__pycache__" not in path.parts
    )


@dataclass(frozen=True)
class _ScanReport:
    """Aggregate result of scanning the whole package."""

    violations: tuple[str, ...]
    excepted: tuple[tuple[str, str], ...]
    downward_edges: tuple[tuple[str, str, str], ...]
    parse_errors: tuple[str, ...]
    dynamic_import_module_calls: int
    lazy_export_targets: int
    files_scanned: int


def _scan_package() -> _ScanReport:
    """Scan every file under ``gridalyn/`` and classify each layer edge."""
    violations: list[str] = []
    excepted: list[tuple[str, str]] = []
    downward: list[tuple[str, str, str]] = []
    parse_errors: list[str] = []
    dynamic = 0
    lazy_targets = 0
    files = _package_files()

    for path in files:
        relative = path.resolve().relative_to(_REPO_ROOT).as_posix()
        try:
            scan = _scan_file(path)
        except SyntaxError as exc:  # never skip silently
            parse_errors.append(f"{relative}: SyntaxError: {exc}")
            continue
        dynamic += scan.dynamic_import_module_calls
        lazy_targets += sum(
            1 for _, detected_by in scan.targets if detected_by == _SOURCE_LAZY_EXPORTS
        )
        source_layer = _layer_of_path(path)
        if source_layer is None:
            continue
        for dotted, detected_by in scan.targets:
            target_layer = _layer_of_module(dotted)
            if target_layer is None:
                continue
            if _LAYER_RANK[target_layer] > _LAYER_RANK[source_layer]:
                if (relative, dotted) in _DOCUMENTED_EXCEPTIONS:
                    excepted.append((relative, dotted))
                    continue
                violations.append(
                    f"{relative}: {source_layer} -> {target_layer} "
                    f"(via {detected_by}) [{dotted}]"
                )
            elif _LAYER_RANK[target_layer] < _LAYER_RANK[source_layer]:
                downward.append((source_layer, target_layer, detected_by))

    return _ScanReport(
        violations=tuple(sorted(violations)),
        excepted=tuple(sorted(set(excepted))),
        downward_edges=tuple(downward),
        parse_errors=tuple(parse_errors),
        dynamic_import_module_calls=dynamic,
        lazy_export_targets=lazy_targets,
        files_scanned=len(files),
    )


_STRING_LITERAL_SNIPPET = """
from importlib import import_module

_LAZY_EXPORTS = {
    "Thing": ("gridalyn.projects.api", "Thing"),
}


def load():
    return import_module("gridalyn.interfaces.reporting")
"""

# The annotated form of the lazy map, plus the two aliased/builtin import calls
# a plain ``import_module`` matcher would miss.
_ANNOTATED_AND_ALIASED_SNIPPET = """
from importlib import import_module as _imp

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "Thing": ("gridalyn.projects.api", "Thing"),
}


def load_aliased():
    return _imp("gridalyn.interfaces.reporting")


def load_builtin():
    return __import__("gridalyn.operations.runs")
"""

# Every import call form whose argument is not a string constant. None is
# statically resolvable; all of them must still be counted.
_DYNAMIC_FORMS_SNIPPET = """
import importlib
from importlib import import_module, import_module as _imp


def a(name):
    return import_module(name)


def b(name):
    return importlib.import_module("gridalyn." + name)


def c(name):
    return _imp(name)


def d(name):
    return __import__(name)
"""

# The package a relative import inside gridalyn/foundation/platform/*.py is
# measured from. Written out so the expectations below are readable.
_FOUNDATION_PLATFORM_PACKAGE = ("gridalyn", "foundation", "platform")

# ``source snippet -> dotted module Python itself would import``. Every one of
# these binds a layer ranked above foundation, so each is a live evasion route
# if the resolver gets it wrong.
_UPWARD_RESOLUTION_CASES: dict[str, str] = {
    "from ... import projects": "gridalyn.projects",
    "from ...projects import api": "gridalyn.projects",
    "from gridalyn import projects": "gridalyn.projects",
    "from gridalyn import interfaces": "gridalyn.interfaces",
    "from ... import interfaces": "gridalyn.interfaces",
}


class LayerDirectionTests(unittest.TestCase):
    """Enforce the ordered seven-layer downward-import contract."""

    def test_gridalyn_imports_only_downward_layers(self) -> None:
        """No module imports a layer ranked above its own.

        Crossings listed in :data:`_DOCUMENTED_EXCEPTIONS` are permitted by
        exact ``(file, target)`` pair only, and every listed pair must still
        correspond to a real crossing.
        """
        report = _scan_package()

        self.assertEqual(
            list(report.parse_errors),
            [],
            "files under gridalyn/ failed to parse:\n" + "\n".join(report.parse_errors),
        )

        detail = "\n".join(report.violations)
        self.assertEqual(
            list(report.violations),
            [],
            "upward imports break the layer direction "
            + " -> ".join(_LAYER_ORDER)
            + f"\n{detail}\n"
            f"({report.files_scanned} files scanned; "
            f"{report.dynamic_import_module_calls} dynamic import_module "
            "call(s) are statically unresolvable and not covered)",
        )

        self.assertEqual(
            list(report.excepted),
            sorted(_DOCUMENTED_EXCEPTIONS),
            "every documented layer-direction exception must still match a "
            "real crossing; an entry that no longer matches has been fixed "
            "and must be deleted rather than left as a standing permission",
        )

    def test_scanner_finds_known_good_downward_imports(self) -> None:
        """The scanner is not vacuous: it finds the legitimate downward edges.

        A parser that extracted nothing would report zero violations while
        proving nothing, so require that the two sources present throughout the
        tree each yield real cross-layer downward edges.

        The ``_LAZY_EXPORTS`` floor is set just below the tree's true entry
        count (416 across 183 files) rather than at a token 1, because a
        partially blind extractor also reports zero violations: reading only
        ``ast.Assign`` saw 336 of those 416 and still passed a ``>= 1`` floor
        while four packages -- ``operations`` among them -- were wholly
        invisible.
        """
        report = _scan_package()
        self.assertGreater(report.files_scanned, 100, report.files_scanned)

        by_source: dict[str, int] = {}
        for _, _, detected_by in report.downward_edges:
            by_source[detected_by] = by_source.get(detected_by, 0) + 1

        self.assertGreaterEqual(by_source.get(_SOURCE_IMPORT, 0), 20, by_source)
        self.assertGreaterEqual(by_source.get(_SOURCE_LAZY_EXPORTS, 0), 5, by_source)

        self.assertGreaterEqual(
            report.lazy_export_targets,
            400,
            "the _LAZY_EXPORTS extractor found "
            f"{report.lazy_export_targets} entries; the tree declares ~416, so "
            "a shortfall means whole packages' maps are no longer being read",
        )

        distinct_pairs = {
            (source, target) for source, target, _ in report.downward_edges
        }
        self.assertGreaterEqual(len(distinct_pairs), 3, sorted(distinct_pairs))

    def test_extractors_read_string_literal_sources(self) -> None:
        """String-literal targets are extracted from both non-AST-import sources.

        Exercised against a synthetic snippet so this stays meaningful once the
        tree's own ``import_module`` string constant is resolved.
        """
        scan = _scan_tree(
            ast.parse(_STRING_LITERAL_SNIPPET), ("gridalyn", "foundation")
        )
        found = dict((dotted, src) for dotted, src in scan.targets)

        self.assertEqual(
            found.get("gridalyn.interfaces.reporting"),
            _SOURCE_IMPORT_MODULE,
            scan.targets,
        )
        self.assertEqual(
            found.get("gridalyn.projects.api"),
            _SOURCE_LAZY_EXPORTS,
            scan.targets,
        )

        annotated = _scan_tree(
            ast.parse(_ANNOTATED_AND_ALIASED_SNIPPET), _FOUNDATION_PLATFORM_PACKAGE
        )
        found = dict((dotted, src) for dotted, src in annotated.targets)
        self.assertEqual(
            found.get("gridalyn.projects.api"),
            _SOURCE_LAZY_EXPORTS,
            "an annotated _LAZY_EXPORTS map must be read like a plain one",
        )
        self.assertEqual(
            found.get("gridalyn.interfaces.reporting"),
            _SOURCE_IMPORT_MODULE,
            "import_module rebound under an alias must still be resolved",
        )
        self.assertEqual(
            found.get("gridalyn.operations.runs"),
            _SOURCE_DUNDER_IMPORT,
            "__import__ with a constant argument must still be resolved",
        )

    def test_relative_and_facade_targets_resolve(self) -> None:
        """Relative and root-facade imports resolve to the module Python binds.

        Both forms are evasion routes rather than mere blind spots: each one
        below expresses a foundation -> projects/interfaces dependency, and a
        resolver that answers ``gridalyn.foundation`` for them would report the
        tree green while the crossing stands.
        """
        self.assertEqual(
            _package_parts(_PACKAGE_DIR / "foundation" / "platform" / "validation.py"),
            _FOUNDATION_PLATFORM_PACKAGE,
            "a relative import is measured from the package containing the "
            "module, not from the module's own dotted path",
        )
        self.assertEqual(
            _package_parts(_PACKAGE_DIR / "foundation" / "platform" / "__init__.py"),
            _FOUNDATION_PLATFORM_PACKAGE,
        )

        for source, expected in _UPWARD_RESOLUTION_CASES.items():
            with self.subTest(source=source):
                scan = _scan_tree(ast.parse(source), _FOUNDATION_PLATFORM_PACKAGE)
                dotted = [target for target, _ in scan.targets]
                self.assertIn(expected, dotted, scan.targets)

                target_layer = _layer_of_module(expected)
                self.assertIsNotNone(target_layer, expected)
                assert target_layer is not None  # for the type checker
                self.assertGreater(
                    _LAYER_RANK[target_layer],
                    _LAYER_RANK["foundation"],
                    f"{source!r} must be classified as an upward crossing",
                )

    def test_dynamic_import_module_calls_are_measured(self) -> None:
        """The gate's static blind spot is counted, not hidden.

        ``import_module(module_name)`` with a variable argument cannot be
        resolved statically. The lazy-export ``__getattr__`` idiom uses exactly
        that call, so the count is expected to be non-zero; what matters is
        that it is measured and reported rather than silently dropped.

        The counter must cover every spelling of an unresolvable import call,
        not just the canonical one: a form that is neither resolved nor counted
        is a blind spot the metric would actively deny having.
        """
        forms = _scan_tree(
            ast.parse(_DYNAMIC_FORMS_SNIPPET), _FOUNDATION_PLATFORM_PACKAGE
        )
        self.assertEqual(
            forms.dynamic_import_module_calls,
            4,
            "import_module, importlib.import_module with a concatenated "
            "argument, an aliased import_module and __import__ must all be "
            f"counted; got {forms.dynamic_import_module_calls}",
        )

        report = _scan_package()
        self.assertGreaterEqual(
            report.dynamic_import_module_calls,
            1,
            "expected the lazy-export __getattr__ idiom to produce dynamic "
            "import_module calls; finding none suggests the counter is broken",
        )
        print(
            "\nlayer-direction blind spot: "
            f"{report.dynamic_import_module_calls} dynamic import_module "
            f"call(s) across {report.files_scanned} files are statically "
            "unresolvable"
        )


if __name__ == "__main__":
    unittest.main()

"""Gate on the SDK's public import surface and its introspectability.

Every ``gridalyn`` facade declares its public names in a ``_LAZY_EXPORTS`` map
and resolves them on first access through a module-level ``__getattr__``, so
that ``import gridalyn`` stays cheap and optional heavy dependencies are never
pulled until something needs them.

That design has one externally visible cost: a name that lives only in
``_LAZY_EXPORTS`` is absent from the module namespace until it is touched, so
``dir()`` and :func:`inspect.getmembers` do not list it. Tab completion, IDE
attribute discovery, ``help()``, and static documentation tooling all read the
surface that way, so a published SDK must not lose it. Each facade therefore
defines a ``__dir__`` that unions the live namespace with ``_LAZY_EXPORTS``.

This module gates two independent properties:

* **Resolvability.** Every one of the 416 declared entries, across all 17 lazy
  modules, must actually resolve. A typo in a target module path or attribute
  name is otherwise invisible until a user hits that one name at runtime.
* **Visibility.** Every name a *public layer facade* declares must appear in
  its ``dir()``.

Why visibility is asserted on 8 modules and resolvability on all 17
------------------------------------------------------------------
:data:`PUBLIC_LAYER_FACADES` is the surface the documentation and the layer
model promise to outside users: the top-level package plus one module per
layer. The remaining 9 lazy modules (``gridalyn.simulation.control``,
``gridalyn.twin.adapters``, ``gridalyn.operations.clearing`` and so on) are
second-level facades re-exported *through* those 8; they are reachable but are
not the advertised import path. They carry no ``__dir__`` today. Extending it
to them is a coherent follow-up, deliberately not asserted here so that this
gate states exactly what the package currently promises rather than a wish.

Non-vacuity
-----------
A discovery walk that silently returned nothing would make every parametrized
case vanish and the file would pass green while proving nothing. The counts in
:func:`test_lazy_export_discovery_is_not_vacuous` are pinned against exactly
that failure mode.
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "gridalyn"

#: The advertised public import surface: the top-level package and one module
#: per layer, in the documented downward order.
PUBLIC_LAYER_FACADES = (
    "gridalyn",
    "gridalyn.foundation",
    "gridalyn.twin",
    "gridalyn.assets",
    "gridalyn.simulation",
    "gridalyn.operations",
    "gridalyn.projects",
    "gridalyn.interfaces",
)

#: Number of modules in the tree that declare a ``_LAZY_EXPORTS`` map. Pinned so
#: that a discovery walk which stops finding them fails loudly instead of
#: quietly collecting zero parametrized cases. 17 -> 18 on 2026-08-06:
#: ``gridalyn.interfaces.reporting`` converted to a lazy facade (ledger #35,
#: removing the eager ``digital_twin`` import behind the runpy RuntimeWarning).
#: 18 -> 19 on 2026-08-07: ``gridalyn.simulation.backends`` was added and needs
#: the map, because every backend reaches ``pandapower`` (whose import carries
#: the truly-optional ``lightsim2grid``). 19 -> 20 on 2026-08-09:
#: ``gridalyn.simulation.surrogates`` was added with a map, because its
#: registry pulls the whole ``analytics.network_impact`` closure (pandas plus
#: the ``rdflib``-backed semantic profile) that a bare ``ErrorBound`` consumer
#: should not pay for.
EXPECTED_LAZY_MODULE_COUNT = 20

#: Total ``_LAZY_EXPORTS`` entries across those modules. Lower bound, not an
#: equality: adding a public export must not require editing this test.
MINIMUM_LAZY_EXPORT_ENTRIES = 400

#: Seconds a single clean-process ``dir()`` probe may take before it fails.
_PROBE_TIMEOUT_SECONDS = 120


def _module_name(path: Path) -> str:
    """Return the dotted module name for a file under the package root.

    Args:
        path: Path to a ``.py`` file inside ``gridalyn/``.

    Returns:
        The importable dotted name, with a trailing ``.__init__`` stripped so
        that a package maps to the package itself.
    """
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    name = ".".join(relative.parts)
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def _extract_lazy_exports(tree: ast.Module) -> dict[str, tuple[str, str]] | None:
    """Extract a module's ``_LAZY_EXPORTS`` map from its parsed source.

    Handles both a bare assignment and an annotated one
    (``_LAZY_EXPORTS: dict[str, tuple[str, str]] = {...}``); 4 of the 17 lazy
    modules use the annotated form, and an extractor that matched only
    :class:`ast.Assign` would silently skip them.

    Args:
        tree: Parsed module source.

    Returns:
        A mapping of exported name to ``(module path, attribute)``, or ``None``
        if the module declares no ``_LAZY_EXPORTS`` dict literal.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not any(getattr(t, "id", None) == "_LAZY_EXPORTS" for t in targets):
            continue
        if not isinstance(value, ast.Dict):
            continue
        return {
            key.value: (entry.elts[0].value, entry.elts[1].value)
            for key, entry in zip(value.keys, value.values, strict=True)
            if isinstance(key, ast.Constant)
            and isinstance(entry, ast.Tuple)
            and len(entry.elts) == 2
            and isinstance(entry.elts[0], ast.Constant)
            and isinstance(entry.elts[1], ast.Constant)
        }
    return None


def _discover_lazy_modules() -> dict[str, dict[str, tuple[str, str]]]:
    """Find every module in the package that declares a ``_LAZY_EXPORTS`` map.

    Returns:
        A mapping of dotted module name to that module's export map.
    """
    discovered: dict[str, dict[str, tuple[str, str]]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "_LAZY_EXPORTS" not in source:
            continue
        exports = _extract_lazy_exports(ast.parse(source))
        if exports:
            discovered[_module_name(path)] = exports
    return discovered


LAZY_MODULES = _discover_lazy_modules()

#: One case per declared export, so a single broken target names itself.
LAZY_EXPORT_CASES = [
    (module_name, export_name)
    for module_name, exports in sorted(LAZY_MODULES.items())
    for export_name in sorted(exports)
]


def _import_facade(module_name: str) -> ModuleType:
    """Import a facade module by dotted name.

    Args:
        module_name: Dotted module name to import.

    Returns:
        The imported module object.
    """
    return importlib.import_module(module_name)


#: Probe reporting ``dir()`` for one module, after optionally resolving the
#: names given as trailing arguments. Runs in its own interpreter -- see
#: :func:`_dir_in_clean_process` for why in-process would be a false green.
_DIR_PROBE = (
    "import importlib, json, sys\n"
    "module = importlib.import_module(sys.argv[1])\n"
    "for name in sys.argv[2:]:\n"
    "    getattr(module, name)\n"
    "json.dump(dir(module), sys.stdout)\n"
)


@lru_cache(maxsize=None)
def _dir_in_clean_process(
    module_name: str,
    touch: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return ``dir(module)`` as observed in a freshly started interpreter.

    Subprocess isolation is mandatory, not defensive. ``__getattr__`` caches
    each resolved export into the module's ``globals()``, so any earlier test
    that touches a name makes it appear in ``dir()`` from then on -- with or
    without a ``__dir__``. Probing in-process therefore passes even when
    ``__dir__`` has been deleted outright, which is precisely the regression
    this file exists to catch.

    Args:
        module_name: Dotted module name to import in the child process.
        touch: Exported names to resolve before calling ``dir()``, used to
            observe the module in the half-resolved state a real session
            reaches after its first attribute access.

    Returns:
        The names ``dir()`` reports for the module in the child process.
    """
    result = subprocess.run(
        [sys.executable, "-c", _DIR_PROBE, module_name, *touch],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"importing {module_name} in a clean process failed with exit "
            f"{result.returncode}: {result.stderr.strip()[-2000:]}"
        )
    return tuple(json.loads(result.stdout))


def test_lazy_export_discovery_is_not_vacuous() -> None:
    """Fail loudly if the discovery walk stops finding the lazy facades.

    Every other case in this file is parametrized off :data:`LAZY_MODULES`. If
    discovery returned an empty mapping, pytest would collect zero cases and
    report success, so the shape of the walk is asserted before its contents.
    """
    assert len(LAZY_MODULES) == EXPECTED_LAZY_MODULE_COUNT, (
        f"expected {EXPECTED_LAZY_MODULE_COUNT} modules declaring _LAZY_EXPORTS, "
        f"found {len(LAZY_MODULES)}: {sorted(LAZY_MODULES)}"
    )
    total_entries = sum(len(exports) for exports in LAZY_MODULES.values())
    assert total_entries >= MINIMUM_LAZY_EXPORT_ENTRIES, (
        f"expected at least {MINIMUM_LAZY_EXPORT_ENTRIES} lazy export entries, "
        f"found {total_entries}"
    )
    missing_facades = [n for n in PUBLIC_LAYER_FACADES if n not in LAZY_MODULES]
    assert (
        not missing_facades
    ), f"public layer facades are not declaring _LAZY_EXPORTS: {missing_facades}"


@pytest.mark.parametrize(
    ("module_name", "export_name"),
    LAZY_EXPORT_CASES,
    ids=[f"{module}:{name}" for module, name in LAZY_EXPORT_CASES],
)
def test_every_lazy_export_resolves(module_name: str, export_name: str) -> None:
    """Every declared export must actually resolve through ``__getattr__``.

    A wrong target module path or attribute name in a ``_LAZY_EXPORTS`` entry
    is otherwise undetectable until a user touches that one name.

    Args:
        module_name: Facade declaring the export.
        export_name: Public name the facade promises.
    """
    module = _import_facade(module_name)
    try:
        getattr(module, export_name)
    except AttributeError as exc:  # pragma: no cover - failure path
        target = LAZY_MODULES[module_name][export_name]
        pytest.fail(
            f"{module_name}.{export_name} does not resolve to "
            f"{target[0]}.{target[1]}: {exc}"
        )


@pytest.mark.parametrize("module_name", PUBLIC_LAYER_FACADES)
def test_public_facade_dir_lists_every_lazy_export(module_name: str) -> None:
    """``dir()`` on a public facade must list every name it exports.

    Without a ``__dir__``, ``dir()`` reports only the names already resolved
    into the module namespace, so the surface a user can discover depends on
    what happens to have been imported. That is the regression this gate keeps
    closed, which is why the probe runs in a clean process.

    Args:
        module_name: Public layer facade to check.
    """
    listed = set(_dir_in_clean_process(module_name))
    declared = set(LAZY_MODULES[module_name])
    hidden = sorted(declared - listed)
    assert not hidden, (
        f"{module_name} exports {len(hidden)} name(s) that dir() does not list, "
        f"so they are invisible to inspect.getmembers, help() and tab "
        f"completion: {hidden}"
    )


@pytest.mark.parametrize("module_name", PUBLIC_LAYER_FACADES)
def test_public_facade_dir_has_no_duplicates_after_resolution(
    module_name: str,
) -> None:
    """``dir()`` must not list a name twice once it has been resolved.

    ``dir()`` sorts what ``__dir__`` returns but does **not** deduplicate it,
    so this is a check that ``__dir__`` unions rather than concatenates. The
    distinction is invisible on an untouched module -- ``globals()`` and
    ``_LAZY_EXPORTS`` are disjoint until something is accessed -- so the probe
    resolves one export first, which is what puts the two sources in overlap.

    Args:
        module_name: Public layer facade to check.
    """
    declared = sorted(LAZY_MODULES[module_name])
    names = list(_dir_in_clean_process(module_name, (declared[0],)))
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, (
        f"dir({module_name}) lists {duplicates} more than once after resolving "
        f"{declared[0]!r}; __dir__ should union globals() with _LAZY_EXPORTS, "
        f"not concatenate them"
    )
    assert names == sorted(names), f"dir({module_name}) is not sorted"

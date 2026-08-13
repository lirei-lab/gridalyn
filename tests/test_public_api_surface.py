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
import inspect
import json
import re
import subprocess
import sys
import typing
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

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
#: should not pay for. 20 -> 21 on 2026-08-09: ``gridalyn.simulation.
#: observation`` was added with a map. Its contract reaches only pandas today,
#: so the map is defensive rather than required -- it keeps the first observer
#: for a ``pandapower``-backed producer from leaking ``lightsim2grid`` out of a
#: package import. 21 -> 22 on 2026-08-10: ``gridalyn.simulation.policies``
#: was added with a map. Its contract reaches only pandas/numpy today, so the
#: map is defensive rather than required -- the same reasoning ``observation``
#: carries, since a policy that measures its own sensitivity is expected to
#: reach ``pandapower`` eventually.
EXPECTED_LAZY_MODULE_COUNT = 22

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


# ---------------------------------------------------------------------------
# The gridalyn.twin facade-membership criterion, asserted mechanically.
#
# The twin facade's docstring states the criterion a name must meet to be
# exported: "a public entry point of the layer, or a type that appears in the
# signature of one". Until Phase 12 that criterion lived only in prose, so a
# name could be added to the map without meeting it and nothing went red.
# ``test_twin_facade_membership_criterion`` encodes it over the real
# ``_LAZY_EXPORTS`` map.
#
# The naive encoding was measured VACUOUS and is deliberately not used: a
# clause "the export is callable" admits everything including a ``Literal``
# alias, and a clause "appears in another exported *module-level callable's*
# signature" is false for 8 real exports (they are returned or accepted by
# METHODS of exported classes, not by module-level functions), while
# ``inspect.signature`` crashes with ``ValueError`` on exception types. The
# encoding below therefore harvests raw annotation *strings* from exported
# functions AND from public methods and field annotations of exported classes.
# ---------------------------------------------------------------------------

#: Exported classes that are API roots: users instantiate them to *start* a
#: flow, so no exported signature can reference them -- they are the origin,
#: not a value passed through one. EXTENSION-ONLY: later plans may APPEND a
#: name here with a one-line reason (12-04 appends its registry names); never
#: remove entries or weaken the mechanism.
ENTRY_POINT_CLASSES: tuple[str, ...] = (
    # Source adapter users construct to load a CIM parquet snapshot; it is the
    # producer at the head of the model data flow, so nothing signs it.
    "CimParquetAdapter",
    # Source adapter users construct to export the synthetic committed base;
    # same head-of-flow reasoning as CimParquetAdapter.
    "SyntheticPandapowerAdapter",
    # 12-04 append: users instantiate/hold the observation producer registry
    # as an API root. It also appears in default_observation_producer_registry's
    # return annotation, so the pool branch claims it first; this entry records
    # the API-root reason rather than deciding the branch.
    "ObservationProducerRegistry",
    # Review-cycle-1 append: the repository users construct (via from_parquet
    # or directly) to load and validate the canonical model -- the API root of
    # the model-loading flow, per the twin facade's own docstring. Exposed by
    # the candidate-exclusive pool fix: its only annotation naming it was its
    # own from_parquet return, i.e. it was self-signing.
    "NetworkModelRepository",
    # Review-cycle-1 append, same pool fix: the semantic-graph repository is
    # external-facing public API by recorded decision (Phase 9, finding G9 --
    # kept for external consumers despite zero internal ones), i.e. an API
    # root nothing in-repo signs by design.
    "SemanticGraphRepository",
)

#: Exported exception types. Exceptions are raised, not signed -- they appear
#: in ``Raises:`` docstring sections, never in annotations -- and
#: ``inspect.signature`` raises ``ValueError`` on builtin exception types.
#: EXTENSION-ONLY, same rule as :data:`ENTRY_POINT_CLASSES`.
EXCEPTION_EXPORTS: tuple[str, ...] = (
    "UnknownNetworkAdapterError",
    # 12-04 append: raised by the observation producer registry on an unknown
    # producer ID; exceptions are raised, not signed.
    "UnknownObservationProducerError",
)


def _annotation_strings(func: Any) -> list[str]:
    """Harvest a callable's annotations as raw source strings.

    ``__annotations__`` is the primary source: under ``from __future__ import
    annotations`` (repo-wide convention) it holds the annotation *source text*,
    so a typing-alias name like ``ObservationProvenance`` survives verbatim --
    ``typing.get_type_hints`` would resolve it to ``Literal[...]`` and lose the
    name. ``inspect.signature`` is consulted as a secondary source and wrapped
    in ``try/except (ValueError, TypeError)`` because it has no signature for
    builtin types such as exception classes.

    Args:
        func: Callable to harvest.

    Returns:
        Every annotation rendered as a string, parameters and return alike.
    """
    parts = [
        str(value) for value in (getattr(func, "__annotations__", None) or {}).values()
    ]
    try:
        signature = inspect.signature(func)
    except (ValueError, TypeError):
        return parts
    parts.extend(
        str(parameter.annotation)
        for parameter in signature.parameters.values()
        if parameter.annotation is not inspect.Parameter.empty
    )
    if signature.return_annotation is not inspect.Signature.empty:
        parts.append(str(signature.return_annotation))
    return parts


def _referenced_name_pool(resolved: dict[str, Any], *, exclude: str) -> str:
    """Collect the annotation strings reachable from the surface, minus one.

    Sources, per the membership criterion: annotations of every exported
    module-level function; annotations of every *public* method of every
    exported class (walking ``vars(cls)`` and unwrapping ``classmethod``,
    ``staticmethod`` and ``property``); and the class-level field annotation
    strings of every exported class (which is where dataclass fields live).

    The export named ``exclude`` contributes nothing: when the criterion
    asks whether export N appears in a public signature, N's own method and
    field annotations must not count -- a class trivially names itself
    (``from_frame(cls, ...) -> EntityJoin``), so a pool that included the
    candidate would let every class sign its own membership and the gate
    would stop distinguishing anything.

    Args:
        resolved: Exported name to resolved object.
        exclude: The candidate export whose own annotations are omitted.

    Returns:
        str: The pooled annotation text, newline-joined for whole-word
            searching.
    """
    parts: list[str] = []
    for export_name, obj in resolved.items():
        if export_name == exclude:
            continue
        if inspect.isfunction(obj):
            parts.extend(_annotation_strings(obj))
            continue
        if not inspect.isclass(obj):
            continue
        parts.extend(
            str(value)
            for value in (getattr(obj, "__annotations__", None) or {}).values()
        )
        for attr_name, attribute in vars(obj).items():
            if attr_name.startswith("_"):
                continue
            func = attribute
            if isinstance(attribute, (classmethod, staticmethod)):
                func = attribute.__func__
            elif isinstance(attribute, property):
                func = attribute.fget
            if not inspect.isfunction(func):
                continue
            parts.extend(_annotation_strings(func))
    return "\n".join(parts)


def _is_typing_alias(obj: Any) -> bool:
    """Return whether an export is a typing construct rather than a class."""
    return (
        typing.get_origin(obj) is not None or getattr(obj, "__module__", "") == "typing"
    )


def test_twin_facade_membership_criterion() -> None:
    """Every ``gridalyn.twin`` export must meet the facade-membership criterion.

    The criterion, from the facade docstring: a name belongs on the facade when
    it is a public entry point of the layer, or a type that appears in the
    signature of one. Encoded over the real ``_LAZY_EXPORTS`` map (AST-extracted
    by this file's discovery walk), an export passes when it is:

    1. a module-level function -- an entry point itself; or
    2. named, as a whole word, in its candidate-exclusive referenced-name
       pool -- the raw annotation strings of every exported function, every
       public method of every exported class, and every exported class's
       field annotations, EXCLUDING the candidate's own annotations, so a
       class cannot sign its own membership by naming itself; or
    3. a class listed in :data:`ENTRY_POINT_CLASSES` -- an API root users
       instantiate to start a flow, so nothing upstream can sign it; or
    4. an ``Exception`` subclass listed in :data:`EXCEPTION_EXPORTS` --
       exceptions are raised, not signed.

    :data:`ENTRY_POINT_CLASSES` and :data:`EXCEPTION_EXPORTS` are
    EXTENSION-ONLY: later plans may append a name with a one-line reason (12-04
    appends its registry names there), but must never remove entries or weaken
    the mechanism. A new map entry matching none of the four branches fails
    here and must either earn a signature reference or be appended to the
    matching allowlist with its reason.
    """
    exports = LAZY_MODULES["gridalyn.twin"]
    module = importlib.import_module("gridalyn.twin")
    resolved = {name: getattr(module, name) for name in exports}

    # Step 1: every export resolves and is a function, class or typing alias.
    for name, obj in resolved.items():
        assert (
            inspect.isfunction(obj) or inspect.isclass(obj) or _is_typing_alias(obj)
        ), (
            f"gridalyn.twin.{name} is neither a function, a class nor a typing "
            f"alias ({type(obj).__name__}); the facade exports entry points and "
            "the types in their signatures, not arbitrary objects"
        )

    # The allowlists must describe the map they gate, or they rot silently.
    for name in ENTRY_POINT_CLASSES:
        assert name in resolved, f"ENTRY_POINT_CLASSES lists {name!r}, not exported"
        assert inspect.isclass(resolved[name]), f"{name!r} is not a class"
    for name in EXCEPTION_EXPORTS:
        assert name in resolved, f"EXCEPTION_EXPORTS lists {name!r}, not exported"
        assert inspect.isclass(resolved[name]) and issubclass(
            resolved[name], Exception
        ), f"{name!r} is not an Exception subclass"

    # Steps 2-3: each export passes through exactly the four stated branches.
    # The pool is rebuilt per candidate, excluding the candidate's own
    # annotations, so no export signs its own membership.
    branch_hits = {"function": 0, "pool": 0, "entry_point": 0, "exception": 0}
    for name, obj in sorted(resolved.items()):
        if inspect.isfunction(obj):
            branch_hits["function"] += 1
            continue
        pool = _referenced_name_pool(resolved, exclude=name)
        if re.search(rf"\b{re.escape(name)}\b", pool):
            branch_hits["pool"] += 1
            continue
        if inspect.isclass(obj) and name in ENTRY_POINT_CLASSES:
            branch_hits["entry_point"] += 1
            continue
        if (
            inspect.isclass(obj)
            and issubclass(obj, Exception)
            and name in EXCEPTION_EXPORTS
        ):
            branch_hits["exception"] += 1
            continue
        pytest.fail(
            f"gridalyn.twin.{name} meets no membership branch: it is not a "
            "module-level function, no exported signature or field annotation "
            "names it, and it is in neither ENTRY_POINT_CLASSES nor "
            "EXCEPTION_EXPORTS. Either it belongs in a public signature, or "
            "append it to the matching allowlist with a one-line reason."
        )

    # Non-vacuity: the map must exercise every branch, or a broken pool (for
    # instance) would silently stop distinguishing anything.
    assert all(count > 0 for count in branch_hits.values()), (
        f"membership branches went unexercised: {branch_hits}; the pool or an "
        "allowlist has stopped describing the real map"
    )

    # Step 4: the documented exclusions hold -- the declared column contract is
    # an internal contract between the repository and its adapters, not SDK
    # surface, and must never quietly appear in the map.
    assert "BASE_TABLE_SCHEMAS" not in exports
    assert "table_schema" not in exports

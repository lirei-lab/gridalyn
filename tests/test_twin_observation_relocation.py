"""Gate the relocation of the observation contract into ``gridalyn.twin``.

Phase 10 created ``NetworkObservation`` under ``gridalyn.simulation.observation``
because that is where the need surfaced. Phase 11 moved it down to
``gridalyn.twin.observation``: what a solved network shows is a property of the
network, not of the solver, and ``twin`` sits below ``simulation``.

Five behaviours are held here:

(a) ``twin`` *owns* the contract -- the old path defines nothing;
(b) the old path warns;
(c) both paths yield the **same object**, not two classes with one name;
(d) importing ``gridalyn.twin.observation`` pulls no optional dependency;
(e) **no in-repo module imports through the shim.**

(e) is the correction of a real defect. Plan 11-04 left the seven modules that
had imported the contract through ``gridalyn.simulation.observation`` untouched,
on the reasoning that the shim proved they did not *need* editing. The
consequence was that ``python -W error::DeprecationWarning -c "import
gridalyn.operations.der_voltage"`` exited 1 and the warning appeared in the
suite's own warnings summary on every run. A deprecation shim exists to protect
*external* consumers; warning the repository at its own code trains every reader
to ignore the warning, which is the one thing that must not happen to it. Review
cycle 1 repointed all seven onto :data:`CANONICAL_MODULE`.

(a) is an :mod:`ast` scan of the shim rather than a grep, for the reason Phase-9
retrospective item 3 records: the shim's docstring names ``NetworkObservation``
in the prose explaining that it no longer defines it, so a text search would
match forever regardless of the code.

(d) runs in a subprocess. An in-process ``sys.modules`` assertion is worthless
once pytest has imported ``pandapower`` for another test in the same session --
the reasoning ``tests/test_import_hygiene.py`` documents.

**No state-producer registry exists, and that is deliberate.** See
:data:`MEASURED_PRODUCER_DEFERRAL`.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the contract lives now.
CANONICAL_MODULE = "gridalyn.twin.observation.contract"

#: The deprecated path, kept resolving for the public import surface shipped
#: 2026-08-11. It has **no in-repo consumer** -- see
#: :data:`REPOINTED_CONSUMERS` and
#: :func:`test_no_in_repo_module_imports_the_deprecated_path`.
SHIM_PACKAGE = "gridalyn.simulation.observation"

#: Names the contract publishes. Each must be one object under every path.
CONTRACT_NAMES = (
    "AS_OF_ABSENT_REASON",
    "BUS_VOLTAGE_COLUMN",
    "LINE_LOADING_COLUMN",
    "LINE_LOSS_COLUMN",
    "NetworkObservation",
    "observe_network",
)

#: Import surfaces that must all resolve to the *same* objects. The two
#: deprecated entries have no in-repo consumer left, so they are held here for
#: the external surface alone: an outside caller that pinned
#: ``from gridalyn.simulation.observation.contract import NetworkObservation``
#: must still receive the twin's class, not a second one wearing its name.
IMPORT_SURFACES = (
    "gridalyn.twin.observation.contract",
    "gridalyn.twin.observation",
    "gridalyn.simulation.observation.contract",
    "gridalyn.simulation.observation",
    "gridalyn.simulation",
)

#: The seven modules 11-04 left importing through the shim and review cycle 1
#: repointed onto :data:`CANONICAL_MODULE`. Importing any of them -- and
#: ``gridalyn`` itself -- must be silent under ``-W error::DeprecationWarning``.
REPOINTED_CONSUMERS = (
    "gridalyn.operations.der_voltage",
    "gridalyn.operations.prosumer_realtime",
    "gridalyn.simulation.environments.voltage_control",
    "gridalyn.simulation.policies.contract",
    "gridalyn.simulation.simulators.powerflow.artifacts",
    "gridalyn.simulation.simulators.powerflow.runner",
    "gridalyn.simulation.simulators.powerflow.scenarios",
)

#: Why no measured-state producer and no producer registry were built.
#:
#: The Phase-11 design called for two state producers -- simulated and measured
#: -- with provenance distinguishing them. Planning measured the only measured
#: dataset in the repository, ``datasets/hq``: ``consumption.h5`` and
#: ``heating.h5`` are 35,041 x 1000 at 15-minute resolution, and their columns
#: are the anonymous ordinals ``'0'`` .. ``'999'``. There is no key joining
#: them to the twin's ``building_id`` / ``bus_id`` namespace, so binding a home
#: to a building would be *inventing* the join rather than measuring it. The
#: user reopened that scope rather than substitute a producer.
#:
#: A registry was therefore **not** built. One real producer plus a placeholder
#: is precisely the speculative abstraction plan 10-03 declined for this same
#: contract -- it shipped one builder, ``observe_network``, and no registry --
#: and the >=2-consumer promotion rule is not triggered here either: relocating
#: an existing contract whose five call sites migrated in Phase 10 creates no
#: new boundary. This constant exists so a later reader inherits the finding
#: instead of reading the absence as an oversight.
MEASURED_PRODUCER_DEFERRAL = (
    "measured state producer deferred: datasets/hq carries 1000 anonymous "
    "ordinal columns '0'..'999' with no key joining to building_id/bus_id, so "
    "the join would be invented rather than measured; no producer registry "
    "was built, because one producer plus a placeholder is the speculative "
    "abstraction 10-03 declined for this contract"
)


def _run(code: str, *, flags: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a clean interpreter and return the completed process.

    Args:
        code: Source passed to ``python -c``.
        flags: Interpreter flags placed before ``-c``, such as ``-W``.

    Returns:
        The completed process, never raising on a non-zero exit -- the exit
        code is itself an assertion subject here.
    """
    return subprocess.run(
        [sys.executable, *flags, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


# --------------------------------------------------------------------------
# (a) twin owns the contract; the old path defines nothing
# --------------------------------------------------------------------------


def test_the_contract_is_defined_under_twin() -> None:
    """The class and its builder are declared in the twin layer."""
    from gridalyn.twin.observation.contract import NetworkObservation, observe_network

    assert NetworkObservation.__module__ == CANONICAL_MODULE
    assert observe_network.__module__ == CANONICAL_MODULE

    source = REPO_ROOT / "gridalyn/twin/observation/contract.py"
    assert source.is_file()
    declared = {
        node.name
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert {"NetworkObservation", "observe_network"} <= declared


def test_the_deprecated_path_declares_nothing_of_its_own() -> None:
    """The shim re-binds; it does not redefine.

    Asserted by walking the parsed shim rather than searching its text: its
    own docstring names ``NetworkObservation`` while explaining that it no
    longer defines one, so a grep would pass against any implementation.
    """
    for relative in (
        "gridalyn/simulation/observation/__init__.py",
        "gridalyn/simulation/observation/contract.py",
    ):
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        declared = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        assert not declared & set(CONTRACT_NAMES), f"{relative} redefines {declared}"

        imported_from = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert CANONICAL_MODULE in imported_from, relative


# --------------------------------------------------------------------------
# (b) the old path warns
# --------------------------------------------------------------------------


def test_importing_either_deprecated_path_warns() -> None:
    """Both the package and its ``contract`` submodule warn, once each."""
    for module in (SHIM_PACKAGE, f"{SHIM_PACKAGE}.contract"):
        result = _run(f"import {module}", flags=("-W", "error::DeprecationWarning"))

        assert result.returncode != 0, f"{module} did not warn: {result.stdout}"
        assert "DeprecationWarning" in result.stderr, result.stderr
        # The message must be actionable: it names where the contract went.
        assert "gridalyn.twin.observation" in result.stderr, result.stderr


def test_the_canonical_path_does_not_warn() -> None:
    """The anti-vacuity guard for the case above.

    If some unrelated import in the tree emitted a ``DeprecationWarning``, the
    previous test would pass without the shim doing anything. Importing the
    canonical path under the identical filter must succeed.
    """
    result = _run(
        f"import {CANONICAL_MODULE}; import gridalyn.simulation",
        flags=("-W", "error::DeprecationWarning"),
    )

    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# (c) both paths yield the same object
# --------------------------------------------------------------------------


def test_every_import_surface_yields_one_object() -> None:
    """Five import paths, one set of objects -- never a second class."""
    import importlib
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        modules = {name: importlib.import_module(name) for name in IMPORT_SURFACES}

    for attribute in CONTRACT_NAMES:
        resolved = {
            name: getattr(module, attribute)
            for name, module in modules.items()
            if hasattr(module, attribute)
        }
        # ``gridalyn.simulation`` publishes only the two headline names.
        assert len(resolved) >= 2, attribute
        identities = {id(value) for value in resolved.values()}
        assert len(identities) == 1, f"{attribute} has {len(identities)} identities"


def test_the_repointed_consumers_bind_the_twin_objects() -> None:
    """The repointed consumers bind the contract, not a look-alike.

    What each module's import statement actually bound is the proof, not the
    fact that it still parses -- a second class with the same name would parse
    just as well.
    """
    import importlib

    from gridalyn.twin.observation.contract import NetworkObservation, observe_network

    # The two of the seven that bind the class itself; the other five bind
    # only the builder, which the assertion below covers for one of them.
    for name in (
        "gridalyn.operations.der_voltage",
        "gridalyn.simulation.policies.contract",
    ):
        module = importlib.import_module(name)
        assert module.NetworkObservation is NetworkObservation, name

    assert (
        importlib.import_module("gridalyn.operations.der_voltage").observe_network
        is observe_network
    )


# --------------------------------------------------------------------------
# (d) the new package pulls no optional dependency
# --------------------------------------------------------------------------


def test_importing_twin_observation_pulls_no_optional_dependency() -> None:
    """A clean-process import of the new package leaks no optional module."""
    probe = (
        "import json, sys;"
        "import gridalyn.twin.observation;"
        "print(json.dumps(sorted("
        "{'lightsim2grid', 'cvxpy', 'osmnx'} & set(sys.modules))))"
    )
    result = _run(probe)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_the_leak_probe_would_notice_an_optional_dependency() -> None:
    """The probe above is not vacuous: it reports a leak when one exists."""
    probe = (
        "import json, sys;"
        "import gridalyn.twin.observation;"
        "import pandapower;"
        "print(json.dumps(sorted("
        "{'lightsim2grid', 'cvxpy', 'osmnx'} & set(sys.modules))))"
    )
    result = _run(probe)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["lightsim2grid"]


# --------------------------------------------------------------------------
# (e) no in-repo module imports through the shim
# --------------------------------------------------------------------------


def _shim_importers(source: str) -> list[str]:
    """Return every import in ``source`` that reaches the deprecated package.

    Walks the parsed module rather than matching text: the shim's own name
    appears in this file's docstring, in the shim's docstring and in several
    explanatory comments, so a grep would report offenders that are prose.
    Both statement forms count -- ``from gridalyn.simulation.observation...
    import x`` and a bare ``import gridalyn.simulation.observation`` -- because
    either one executes the package body and therefore fires the warning.

    Args:
        source: Python source of a module to scan.

    Returns:
        The offending module paths, in the order they appear.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        found += [
            name
            for name in names
            if name == SHIM_PACKAGE or name.startswith(f"{SHIM_PACKAGE}.")
        ]
    return found


def test_no_in_repo_module_imports_the_deprecated_path() -> None:
    """The shim serves external callers only.

    Scanned across the whole package rather than over
    :data:`REPOINTED_CONSUMERS`, so a *new* module reaching for the old path is
    caught as well as a regression in one of the seven.
    """
    package = REPO_ROOT / "gridalyn"
    shim_dir = package / "simulation" / "observation"

    offenders = {
        str(path.relative_to(REPO_ROOT)): imported
        for path in sorted(package.rglob("*.py"))
        if shim_dir not in path.parents
        for imported in [_shim_importers(path.read_text(encoding="utf-8"))]
        if imported
    }

    assert not offenders, (
        f"{len(offenders)} module(s) import the deprecated "
        f"{SHIM_PACKAGE!r}: {offenders}. Import {CANONICAL_MODULE!r} instead -- "
        "the shim is for external callers, and warning the repository at its "
        "own code trains readers to ignore the warning"
    )


def test_the_shim_scan_would_catch_a_reintroduced_import() -> None:
    """The scan is not vacuous: it finds both forms it exists to forbid."""
    assert _shim_importers(
        "from gridalyn.simulation.observation.contract import observe_network"
    ) == [f"{SHIM_PACKAGE}.contract"]
    assert _shim_importers("import gridalyn.simulation.observation") == [SHIM_PACKAGE]
    # Prose naming the path must not be mistaken for an import of it.
    assert _shim_importers("# gridalyn.simulation.observation was the old home") == []
    # The canonical path is not an offender.
    assert _shim_importers(f"from {CANONICAL_MODULE} import observe_network") == []


def test_importing_the_repointed_consumers_emits_no_deprecation() -> None:
    """The seven, plus ``gridalyn`` itself, are silent under -W error.

    This is the consequence the AST scan exists to prevent, asserted directly:
    before review cycle 1 each of these exited 1. One subprocess covers all
    eight -- a traceback names the module that failed, and eight separate
    interpreters would pay the pandapower import cost eight times.

    Its anti-vacuity guard is
    :func:`test_importing_either_deprecated_path_warns`, which proves the same
    flag really does turn *this* warning into a non-zero exit.
    """
    imports = "".join(
        f"import {module};" for module in ("gridalyn", *REPOINTED_CONSUMERS)
    )
    result = _run(imports, flags=("-W", "error::DeprecationWarning"))

    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# the deferral, recorded rather than implied
# --------------------------------------------------------------------------


def test_no_state_producer_registry_was_built() -> None:
    """``twin/observation`` ships a contract and no registry, deliberately.

    The absence is the decision, so it is asserted rather than left to be
    rediscovered. The reason travels with it in
    :data:`MEASURED_PRODUCER_DEFERRAL`.
    """
    package = REPO_ROOT / "gridalyn/twin/observation"
    modules = sorted(path.name for path in package.glob("*.py"))

    assert modules == ["__init__.py", "contract.py"], modules

    declared = {
        node.name
        for path in package.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert not [name for name in declared if "egistry" in name], declared

    assert "datasets/hq" in MEASURED_PRODUCER_DEFERRAL
    assert "no producer registry" in MEASURED_PRODUCER_DEFERRAL

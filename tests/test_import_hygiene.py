"""Behavioral enforcement of the capability-gating promise.

Importing any ``gridalyn`` sub-package must never pull a *truly-optional*
dependency into ``sys.modules``. A sub-package that does so raises
``ImportError`` on an install without the corresponding extra -- precisely
what capability gating exists to prevent.

Why this check is BEHAVIORAL, not syntactic
-------------------------------------------
The obvious cheap check -- assert every package ``__init__.py`` contains the
literal ``_LAZY_EXPORTS`` map -- is wrong here. Of the 36 ``__init__.py``
files in this tree, 19 carry that literal and 17 do not (measured 2026-08-07),
yet none of those 17 pulls an optional dependency: only 2 sub-packages ever
did, and both now carry the map. A syntactic check would therefore produce 17
false positives while proving nothing about what actually gets imported. This
test instead imports each sub-package for real and inspects the resulting
``sys.modules``.

Why the declared set is the derived set (pyproject keeps them honest)
---------------------------------------------------------------------
``OPTIONAL_CAPABILITY_MODULES`` declares only the *truly-optional* modules —
modules absent from ``pyproject.toml`` ``[project] dependencies`` — so there
is no runtime exclusion: the declared set and the derived set are the same
three modules (``lightsim2grid``, ``cvxpy``, ``osmnx``) since the ``semantic``
capability (``falkordb``) was removed on 2026-08-07. The
``derive_optional_modules`` subtraction is kept as the pyproject cross-check
that keeps the two honest: if a declared capability module ever migrates into
``[project] dependencies`` (as ``lightgbm`` did), it drops out of the derived
set and stops being asserted, and ``test_optional_set_is_nonempty_and_expected``
pins the derived set exactly so the sweep cannot narrow silently.

Why each import runs in its own subprocess
------------------------------------------
An in-process sweep leaks ``sys.modules`` between checks: the first package
to pull ``lightsim2grid`` would make every package checked after it look
dirty. Subprocess isolation is mandatory for a correct verdict.

Shared source of truth
----------------------
``derive_optional_modules`` below is the SINGLE source of the truly-optional
set for the whole suite: ``tests/test_operations_boundaries.py`` imports it to
build its stricter per-facade heavy-module contract. Changing its semantics
changes BOTH gates — that coupling is deliberate (Phase 6, #2), so the two
contracts cannot drift apart again.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gridalyn.foundation.platform.capabilities import OPTIONAL_CAPABILITY_MODULES

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Distribution names that differ from the module name they install. Defensive
#: only: no entry here currently appears in ``OPTIONAL_CAPABILITY_MODULES``, so
#: the mapping is a no-op today. It stays so that a distribution whose import
#: name differs is still subtracted correctly if one is declared optional later.
_DISTRIBUTION_TO_MODULE = {"scikit-learn": "sklearn"}

#: Characters that terminate the name portion of a PEP 508 requirement string.
_REQUIREMENT_NAME_TERMINATORS = "><=~![; "

#: Seconds any single sub-package import is allowed before it is a failure.
_IMPORT_TIMEOUT_SECONDS = 120

#: Number of ``gridalyn`` sub-packages the sweep must cover. Pinned so the
#: swept population cannot shrink unnoticed; update deliberately when a
#: package is added or removed. 36 -> 35 on 2026-08-06, when
#: ``gridalyn.projects.workflows.flexibility`` was deleted with the
#: orphaned-input chain (its two modules read an artifact that no command in
#: this repository produces), leaving the package empty. 35 -> 36 on
#: 2026-08-07, when ``gridalyn.simulation.backends`` was added: it is the one
#: place a power flow is solved, and it reaches ``lightsim2grid`` (and
#: ``pandapower``, whose import carries ``lightsim2grid``), so it is exactly
#: the kind of package this sweep exists to check. 36 -> 37 on 2026-08-09,
#: when ``gridalyn.simulation.surrogates`` was added: it reaches only base
#: dependencies, so it is expected to be clean, and this sweep is what proves
#: that rather than assumes it. 37 -> 38 on 2026-08-09, when
#: ``gridalyn.simulation.observation`` was added: it is the one definition of
#: what a solved network shows, and although its contract reaches only base
#: dependencies, it exists to be extended with observers for producers that do
#: reach ``pandapower``, so it belongs in the sweep. 38 -> 39 on 2026-08-10,
#: when ``gridalyn.simulation.policies`` was added: it registers
#: voltage-control policies, and although the contract itself reaches only
#: base dependencies, it exists to be extended with policies that do reach
#: ``pandapower``-backed measurement helpers, so it belongs in the sweep for
#: the same reason ``observation`` does. 39 -> 40 on 2026-08-12, when
#: ``gridalyn.twin.observation`` was added: Phase 11 moved the observation
#: contract down to the layer that owns network state, and
#: ``gridalyn.simulation.observation`` stayed behind as a deprecation shim, so
#: the sweep now covers both. This is an addition, not a relocation of the
#: count -- the shim is still a real package and still has to be proven clean.
_EXPECTED_SUBPACKAGE_COUNT = 41

_PROBE = """\
import json
import sys

import {package}

optional = {optional!r}
print(json.dumps(sorted(set(optional) & set(sys.modules))))
"""


def _normalize_requirement(requirement: str) -> str:
    """Return the lowercase module name a PEP 508 requirement string installs."""
    name = requirement.strip().lower()
    for index, character in enumerate(name):
        if character in _REQUIREMENT_NAME_TERMINATORS:
            name = name[:index]
            break
    return _DISTRIBUTION_TO_MODULE.get(name, name)


def base_dependency_modules(repo_root: Path) -> frozenset[str]:
    """Return the module names installed by ``[project].dependencies``."""
    pyproject = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]
    return frozenset(_normalize_requirement(item) for item in dependencies)


def derive_optional_modules(repo_root: Path) -> frozenset[str]:
    """Return the declared capability modules that are not base dependencies."""
    declared = {
        module for modules in OPTIONAL_CAPABILITY_MODULES.values() for module in modules
    }
    return frozenset(declared - base_dependency_modules(repo_root))


def discover_subpackages(root: Path) -> list[str]:
    """Return the dotted name of every package directory under ``gridalyn/``."""
    package_root = root / "gridalyn"
    names: list[str] = []
    for path in package_root.rglob("__init__.py"):
        relative = path.relative_to(root).parent
        if "__pycache__" in relative.parts:
            continue
        names.append(".".join(relative.parts))
    return sorted(names)


def leaked_modules(pkg: str, optional: frozenset[str]) -> list[str]:
    """Return the truly-optional modules importing ``pkg`` pulls in.

    The import runs in a dedicated subprocess so that ``sys.modules`` state
    cannot leak between packages. An import that fails, times out, or prints
    unparseable output is reported as a leak-shaped failure rather than being
    silently treated as clean.
    """
    snippet = _PROBE.format(package=pkg, optional=sorted(optional))
    try:
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            timeout=_IMPORT_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return [f"<timeout after {_IMPORT_TIMEOUT_SECONDS}s>"]

    if completed.returncode != 0:
        return [f"<import failed: {_exception_summary(completed.stderr)}>"]

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return ["<no probe output>"]
    try:
        return list(json.loads(lines[-1]))
    except json.JSONDecodeError:
        return [f"<unparseable probe output: {lines[-1]!r}>"]


def _exception_summary(stderr: str) -> str:
    """Return the exception type and message from a subprocess traceback."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    return lines[-1].strip() if lines else "unknown error"


class ImportHygieneTest(unittest.TestCase):
    def test_optional_set_is_nonempty_and_expected(self) -> None:
        # A guard, not a formality: if a later edit to capabilities.py or to
        # pyproject.toml empties this set, the sweep below would pass
        # vacuously while enforcing nothing.
        optional = derive_optional_modules(REPO_ROOT)

        # Pinned exactly, not as a subset: a module migrating into
        # ``[project].dependencies`` silently narrows the sweep, and that
        # migration has precedent (lightgbm became a base dependency in
        # 49a20ef5). Update this set deliberately when that is intended.
        self.assertEqual(
            {"cvxpy", "lightsim2grid", "osmnx"},
            set(optional),
            f"derived truly-optional set changed: {sorted(optional)}",
        )

    def test_no_subpackage_imports_optional_dependencies(self) -> None:
        optional = derive_optional_modules(REPO_ROOT)
        packages = discover_subpackages(REPO_ROOT)
        # Pinned, not a floor: a floor lets the swept population shrink
        # silently. Update this count deliberately when a package is added or
        # removed.
        self.assertEqual(_EXPECTED_SUBPACKAGE_COUNT, len(packages), packages)

        # Threads, not processes: the work is subprocess I/O, not CPU.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda pkg: leaked_modules(pkg, optional), packages)
            )

        offenders = [
            f"{pkg} -> {module}"
            for pkg, leaked in zip(packages, results, strict=True)
            for module in leaked
        ]

        self.assertEqual(
            [],
            offenders,
            "importing these sub-packages pulls a truly-optional dependency "
            "(they will raise ImportError without the matching extra):\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()

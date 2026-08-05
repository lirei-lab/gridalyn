"""Behavioral enforcement of the capability-gating promise.

Importing any ``gridalyn`` sub-package must never pull a *truly-optional*
dependency into ``sys.modules``. A sub-package that does so raises
``ImportError`` on an install without the corresponding extra -- precisely
what capability gating exists to prevent.

Why this check is BEHAVIORAL, not syntactic
-------------------------------------------
The obvious cheap check -- assert every package ``__init__.py`` contains the
literal ``_LAZY_EXPORTS`` map -- is wrong here. Of the 36 ``__init__.py``
files in this tree, 17 carry that literal and 19 do not, yet none of those 19
pulls an optional dependency: only 2 sub-packages ever did, and both now carry
the map. A syntactic check would therefore produce 19 false positives while
proving nothing about what actually gets imported. This test instead imports
each sub-package for real and inspects the resulting ``sys.modules``.

Why 6 of the 10 declared capability modules are excluded
--------------------------------------------------------
``OPTIONAL_CAPABILITY_MODULES`` names 10 modules, but ``pandapower``,
``geopandas``, ``shapely``, ``rdflib``, ``folium`` and ``leafmap`` are base
dependencies in ``pyproject.toml`` -- present on every supported install, so
importing them is legitimate and asserting against them would be wrong. The
truly-optional set is the declared capability modules MINUS the base
dependencies, derived here rather than hardcoded.

Why each import runs in its own subprocess
------------------------------------------
An in-process sweep leaks ``sys.modules`` between checks: the first package
to pull ``lightsim2grid`` would make every package checked after it look
dirty. Subprocess isolation is mandatory for a correct verdict.
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
#: package is added or removed.
_EXPECTED_SUBPACKAGE_COUNT = 36

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
            {"cvxpy", "falkordb", "lightsim2grid", "osmnx"},
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

"""Contract gate: every declared capability is truly optional and exercised.

``OPTIONAL_CAPABILITY_MODULES`` once listed six base dependencies (pandapower,
geopandas, shapely, rdflib, folium, leafmap) as optional -- checks that could
never fail on a supported install. This gate pins the reformed contract
(2026-08-06) on four axes:

(a) No declared module is a ``pyproject.toml`` base dependency -- a base
    dependency is present on every supported install, so requiring it is an
    always-green check.
(b) The declared capability keys are exactly {geo, sim, ops}, and
    every key names at least one module -- an empty capability is itself an
    always-green check. (The ``semantic`` capability, whose only module was
    the unconsumed ``falkordb``, was removed 2026-08-07.)
(c) Every key has at least one ``require_capabilities("<key>"`` call site
    under ``gridalyn/`` -- a real consumer that goes red without the extra.
    Generic map iteration (the ``_doctor`` pattern) deliberately does NOT
    count: it touches every key of any map, so it can never fail for one.
(d) An unknown capability key raises the located, enumerating ``KeyError``.

Phase 15 added axis (e): external ``gridalyn.capabilities`` declarations are
validated against the same honesty rules (non-empty, no core collision, dict
shape) and are honored by ``require_capabilities``.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from gridalyn.foundation.platform.capabilities import (
    OPTIONAL_CAPABILITY_MODULES,
    MissingCapabilityError,
    external_capability_modules,
    missing_capability_modules,
    require_capabilities,
)
from gridalyn.foundation.platform.extensions import EntryPointMetadata

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Distribution names that differ from the module name they install. Mirrors
#: ``tests/test_import_hygiene.py``; defensive only -- a no-op today, kept so a
#: distribution whose import name differs is still matched correctly if it
#: ever enters the dependency list or the capability map.
_DISTRIBUTION_TO_MODULE = {"scikit-learn": "sklearn"}

#: Characters that terminate the name portion of a PEP 508 requirement string.
_REQUIREMENT_NAME_TERMINATORS = "><=~![; "

#: The reformed capability contract. Update deliberately, never as drift.
_EXPECTED_CAPABILITY_KEYS = frozenset({"geo", "ops", "sim"})


def _normalize_requirement(requirement: str) -> str:
    """Return the lowercase module name a PEP 508 requirement string installs.

    Args:
        requirement: One entry from ``[project] dependencies``.

    Returns:
        The import-name form of the requirement, lowercased.
    """
    name = requirement.strip().lower()
    for index, character in enumerate(name):
        if character in _REQUIREMENT_NAME_TERMINATORS:
            name = name[:index]
            break
    return _DISTRIBUTION_TO_MODULE.get(name, name)


def base_dependency_modules(repo_root: Path) -> frozenset[str]:
    """Return the module names installed by ``[project].dependencies``.

    Args:
        repo_root: Repository root containing ``pyproject.toml``.

    Returns:
        Normalized module names of every base dependency.
    """
    pyproject = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]
    return frozenset(_normalize_requirement(item) for item in dependencies)


def _called_name(node: ast.Call) -> str | None:
    """Return the simple name a call expression invokes, when resolvable.

    Args:
        node: A call expression node.

    Returns:
        The function name for ``name(...)`` and ``obj.name(...)`` forms,
        ``None`` for anything else (e.g. calling a subscript).
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _capability_literals(node: ast.Call) -> list[str]:
    """Return every capability-key string literal a preflight call carries.

    Counts three spellings (S12): positional string constants, elements of a
    starred list/tuple literal, and keyword arguments other than ``context=``
    -- the ``context`` string describes the operation and must never be
    mistaken for a required key, even when it happens to equal one.

    Args:
        node: A call to ``require_capabilities``.

    Returns:
        The string literals found among the call's capability arguments.
    """
    candidates: list[ast.expr] = []
    for argument in node.args:
        if isinstance(argument, ast.Starred) and isinstance(
            argument.value, (ast.List, ast.Tuple)
        ):
            candidates.extend(argument.value.elts)
        else:
            candidates.append(argument)
    candidates.extend(
        keyword.value for keyword in node.keywords if keyword.arg != "context"
    )
    return [
        candidate.value
        for candidate in candidates
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
    ]


def capability_call_sites(repo_root: Path) -> dict[str, list[str]]:
    """Return per-capability ``require_capabilities`` call sites.

    AST-scans every Python file under ``gridalyn/`` for calls to
    ``require_capabilities`` whose capability arguments include the key as a
    string literal -- robust to line wrapping, unlike a grep for the literal
    call text, and robust to the spelling of the argument (positional, starred
    literal, or keyword; see :func:`_capability_literals`). Generic iteration
    over ``OPTIONAL_CAPABILITY_MODULES`` (the ``_doctor`` pattern) is
    deliberately not counted: it exercises every key of any map, so it cannot
    fail for a specific one.

    Args:
        repo_root: Repository root containing the ``gridalyn/`` package.

    Returns:
        A mapping from each declared capability key to the sorted repo-relative
        paths of the files that require it (possibly empty).
    """
    sites: dict[str, list[str]] = {key: [] for key in OPTIONAL_CAPABILITY_MODULES}
    for path in sorted((repo_root / "gridalyn").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node) != "require_capabilities":
                continue
            for literal in _capability_literals(node):
                if literal in sites:
                    sites[literal].append(str(path.relative_to(repo_root)))
    return sites


class CapabilityContractTest(unittest.TestCase):
    def test_no_declared_module_is_a_base_dependency(self) -> None:
        """Gate (a): every declared module is absent from the base deps."""
        base = base_dependency_modules(REPO_ROOT)
        offenders = sorted(
            f"{key} -> {module}"
            for key, modules in OPTIONAL_CAPABILITY_MODULES.items()
            for module in modules
            if module.lower() in base
        )
        self.assertEqual(
            [],
            offenders,
            "these capability modules are pyproject base dependencies, so "
            "their checks can never fail on a supported install (remove them "
            "from OPTIONAL_CAPABILITY_MODULES):\n" + "\n".join(offenders),
        )

    def test_capability_keys_are_exactly_the_contract(self) -> None:
        """Gate (b): keys are pinned and no capability is empty."""
        self.assertEqual(
            _EXPECTED_CAPABILITY_KEYS,
            frozenset(OPTIONAL_CAPABILITY_MODULES),
            "capability keys drifted from the reformed contract "
            f"{sorted(_EXPECTED_CAPABILITY_KEYS)}: "
            f"{sorted(OPTIONAL_CAPABILITY_MODULES)}",
        )
        empty = sorted(
            key for key, modules in OPTIONAL_CAPABILITY_MODULES.items() if not modules
        )
        self.assertEqual(
            [],
            empty,
            "these capabilities declare no modules, making require_capabilities "
            f"an always-green check for them: {empty}",
        )

    def test_every_capability_has_a_require_call_site(self) -> None:
        """Gate (c): every key is exercised by a real consumer."""
        sites = capability_call_sites(REPO_ROOT)
        unexercised = sorted(key for key, paths in sites.items() if not paths)
        self.assertEqual(
            [],
            unexercised,
            'no require_capabilities("<key>" call site exists under gridalyn/ '
            f"for: {unexercised} -- a capability nothing requires is dead "
            "weight in the contract (generic map iteration does not count)",
        )

    def test_unknown_capability_raises_enumerating_keyerror(self) -> None:
        """Gate (d): unknown keys fail located, naming the known set."""
        with self.assertRaises(KeyError) as caught:
            missing_capability_modules("definitely-not-a-capability")
        message = str(caught.exception)
        self.assertIn("unknown capability 'definitely-not-a-capability'", message)
        for key in sorted(_EXPECTED_CAPABILITY_KEYS):
            self.assertIn(key, message)


class ExternalCapabilityContractTest(unittest.TestCase):
    """Gate (e): external gridalyn.capabilities declarations are validated.

    An extra may declare NEW capability keys through the ``gridalyn.capabilities``
    entry-point group; the declaration must be a non-empty dict, must not
    collide with the core set, and must not be an always-green empty capability.
    Valid declarations are honored by ``require_capabilities``.
    """

    _VALID_FIXTURE = 'CAPABILITY_MODULES = {"hpc": ["mpi4py"]}\n'

    def _install_module(self, name: str, body: str) -> list[EntryPointMetadata]:
        """Write a real importable fixture module and return its metadata."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / f"{name}.py").write_text(body, encoding="utf-8")
        sys.path.insert(0, tmp.name)
        self.addCleanup(sys.path.remove, tmp.name)
        return [
            EntryPointMetadata(
                name=name,
                value=name,
                module=name,
                attr=None,
                distribution="fixture-ext",
                version="1.0.0",
            )
        ]

    def test_external_capability_modules_returns_declared_map(self) -> None:
        records = self._install_module("hpc_fixture_probe", self._VALID_FIXTURE)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            declared = external_capability_modules()
        self.assertEqual({"hpc": ["mpi4py"]}, declared)

    def test_declaration_without_dict_is_rejected(self) -> None:
        records = self._install_module("bad_cap_probe", "VALUE = 1\n")
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaisesRegex(ValueError, "CAPABILITY_MODULES"):
                external_capability_modules()

    def test_core_capability_collision_is_rejected(self) -> None:
        records = self._install_module(
            "collide_cap_probe", 'CAPABILITY_MODULES = {"sim": ["lightsim2grid"]}\n'
        )
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaisesRegex(ValueError, "collides with a core"):
                external_capability_modules()

    def test_empty_external_capability_is_rejected(self) -> None:
        records = self._install_module(
            "empty_cap_probe", 'CAPABILITY_MODULES = {"empty_cap": []}\n'
        )
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaisesRegex(ValueError, "always-green"):
                external_capability_modules()

    def test_require_capabilities_honors_external_key(self) -> None:
        records = self._install_module(
            "hpc_require_probe",
            'CAPABILITY_MODULES = {"hpc": ["mpi4py_definitely_missing"]}\n',
        )
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaises(MissingCapabilityError) as caught:
                require_capabilities("hpc", context="external fixture")
        self.assertIn("mpi4py_definitely_missing", str(caught.exception))

    def test_base_dependency_module_is_rejected(self) -> None:
        """Axis (e)(iii): external modules must not be pyproject base deps."""
        # ``pandas`` is a base dependency in this repo, so requiring it is an
        # always-green check — the same honesty rule axis (a) pins for the core
        # map. The base set is passed in because ``capabilities.py`` is
        # stdlib-only and does not know the repo root.
        records = self._install_module(
            "base_dep_cap_probe", 'CAPABILITY_MODULES = {"always": ["pandas"]}\n'
        )
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaisesRegex(ValueError, "base-dependency"):
                external_capability_modules(
                    base_modules=base_dependency_modules(REPO_ROOT)
                )

    def test_unknown_external_key_still_raises_located(self) -> None:
        # A valid external capability is declared so the located KeyError names
        # BOTH the core keys and the external key.
        records = self._install_module(
            "hpc_unknown_probe", 'CAPABILITY_MODULES = {"hpc": ["mpi4py"]}\n'
        )
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            with self.assertRaises(KeyError) as caught:
                missing_capability_modules("nope-not-declared")
        message = str(caught.exception)
        self.assertIn("nope-not-declared", message)
        for key in sorted(_EXPECTED_CAPABILITY_KEYS):
            self.assertIn(key, message)
        self.assertIn("hpc", message)


if __name__ == "__main__":
    unittest.main()

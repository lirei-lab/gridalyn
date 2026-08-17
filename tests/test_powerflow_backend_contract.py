"""Gate for the power-flow backend contract (Phase 10, plan 10-01).

Eleven call sites across four layers used to solve power flow directly, with
three different effective solver configurations and no record of which one a
run used. This file pins the five properties that make the reconciliation
safe to rely on:

(a) every registered backend satisfies the contract;
(b) an unknown ID raises a located error enumerating the available IDs;
(c) importing the package leaks neither ``lightsim2grid`` nor ``pandapower``;
(d) without the ``sim`` extra the lightsim backend raises
    ``MissingCapabilityError``, never a bare ``ImportError``, and the default
    backend still resolves;
(e) resolution is by explicit ID only -- no ``entry_points`` discovery, and an
    unregistered backend is not resolvable.

Why (c) runs in a subprocess
----------------------------
An in-process assertion on ``sys.modules`` is worthless here: pytest has
already imported ``pandapower`` for other tests in the same interpreter, so
the assertion would pass (or fail) for reasons unrelated to this package.
Subprocess isolation is mandatory for a correct verdict, the same reasoning
``tests/test_import_hygiene.py`` documents.

Why (d) needs two mechanisms
----------------------------
``require_capabilities`` decides through ``importlib.util.find_spec``, while a
real ``import lightsim2grid`` goes through ``sys.meta_path``. A meta-path
finder that raises makes ``find_spec`` *raise* rather than report absence
(verified), which is not what a missing install looks like. So the helper
below does both: it reports the module absent to ``find_spec`` and makes the
real import fail, which together reproduce an install without the extra.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.util
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from gridalyn.foundation.platform.capabilities import MissingCapabilityError
from gridalyn.simulation.backends import registry as registry_module
from gridalyn.simulation.backends.contract import (
    DEFAULT_POWERFLOW_BACKEND_ID,
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
    PowerFlowBackend,
    PowerFlowBackendDescriptor,
)
from gridalyn.simulation.backends.registry import (
    PowerFlowBackendRegistry,
    UnknownPowerFlowBackendError,
    default_powerflow_backend_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules that must not be in ``sys.modules`` after importing the package.
#: ``pandapower`` is included because importing it puts ``lightsim2grid``
#: into ``sys.modules`` on its own (measured, Phase 1) -- it is the carrier,
#: not a bystander.
_FORBIDDEN_AT_IMPORT = ("lightsim2grid", "pandapower")

_IMPORT_PROBE = """\
import json
import sys

import gridalyn.simulation.backends

print(json.dumps(sorted(set({forbidden!r}) & set(sys.modules))))
"""


class _HideLightSim2Grid:
    """A meta-path finder that makes ``lightsim2grid`` genuinely unimportable."""

    def find_spec(
        self, fullname: str, path: Any = None, target: Any = None
    ) -> None:  # noqa: D102 - importlib finder protocol
        if fullname == "lightsim2grid" or fullname.startswith("lightsim2grid."):
            raise ImportError("lightsim2grid blocked for test")
        return None


@contextlib.contextmanager
def _absent_lightsim2grid() -> Iterator[None]:
    """Make the environment look like an install without the ``sim`` extra.

    Evicting ``sys.modules`` is not optional: another test in the same pytest
    session may already have imported ``lightsim2grid``, and a cached module is
    returned without ever consulting ``sys.meta_path`` -- which would make the
    hider silently ineffective, and this gate order-dependent. The evicted
    entries are restored verbatim, so no later test sees a reimport.

    Yields:
        None, with ``lightsim2grid`` reported absent to capability detection
        and unimportable through ``sys.meta_path`` for the duration.
    """
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, package: str | None = None) -> Any:
        if name == "lightsim2grid" or name.startswith("lightsim2grid."):
            return None
        return real_find_spec(name, package)

    cached = {
        name: module
        for name, module in sys.modules.items()
        if name == "lightsim2grid" or name.startswith("lightsim2grid.")
    }
    for name in cached:
        del sys.modules[name]
    hider = _HideLightSim2Grid()
    sys.meta_path.insert(0, hider)
    try:
        with mock.patch.object(importlib.util, "find_spec", fake_find_spec):
            yield
    finally:
        sys.meta_path.remove(hider)
        sys.modules.update(cached)


class _UnregisteredBackend:
    """A contract-satisfying backend that is deliberately never registered."""

    DESCRIPTOR = PowerFlowBackendDescriptor(
        backend_id="never_registered_backend",
        name="a backend no registry knows about",
    )

    @property
    def descriptor(self) -> PowerFlowBackendDescriptor:
        return self.DESCRIPTOR

    def solve(self, net: Any, **kwargs: Any) -> None:
        raise AssertionError("must never be reached")


class _RegisteredProbeBackend:
    """A contract-satisfying backend used to populate a fresh registry."""

    DESCRIPTOR = PowerFlowBackendDescriptor(
        backend_id="probe_registered_backend",
        name="a backend that is registered",
    )

    @property
    def descriptor(self) -> PowerFlowBackendDescriptor:
        return self.DESCRIPTOR

    def solve(self, net: Any, **kwargs: Any) -> None:
        raise AssertionError("must never be reached")


class RegisteredBackendsSatisfyContractTest(unittest.TestCase):
    """(a) Every registered backend satisfies the contract."""

    def test_default_registry_registers_exactly_the_shipped_backends(self) -> None:
        registry = default_powerflow_backend_registry()
        self.assertEqual(
            [PANDAPOWER_NATIVE_BACKEND_ID, LIGHTSIM2GRID_BACKEND_ID],
            sorted(descriptor.backend_id for descriptor in registry.list_descriptors())[
                ::-1
            ],
        )

    def test_list_descriptors_is_sorted_by_backend_id(self) -> None:
        ids = [
            d.backend_id
            for d in default_powerflow_backend_registry().list_descriptors()
        ]
        self.assertEqual(sorted(ids), ids)

    def test_every_registered_backend_satisfies_the_protocol(self) -> None:
        registry = default_powerflow_backend_registry()
        for descriptor in registry.list_descriptors():
            with self.subTest(backend_id=descriptor.backend_id):
                backend = registry.create(descriptor.backend_id)
                self.assertIsInstance(backend, PowerFlowBackend)
                self.assertTrue(callable(backend.solve))
                self.assertEqual(descriptor.backend_id, backend.descriptor.backend_id)

    def test_every_descriptor_serialises_to_plain_json_for_provenance(self) -> None:
        for descriptor in default_powerflow_backend_registry().list_descriptors():
            with self.subTest(backend_id=descriptor.backend_id):
                payload = descriptor.as_dict()
                self.assertEqual(
                    {
                        "backend_id",
                        "name",
                        "capability",
                        "settings",
                        "contract_version",
                    },
                    set(payload),
                )
                self.assertIsInstance(payload["settings"], dict)
                self.assertIn(type(payload["capability"]).__name__, {"str", "NoneType"})

    def test_default_backend_needs_no_optional_capability(self) -> None:
        # The default must resolve on every supported install; a default that
        # needed an extra would make the contract unusable without it.
        descriptor = default_powerflow_backend_registry().get_descriptor(
            DEFAULT_POWERFLOW_BACKEND_ID
        )
        self.assertIsNone(descriptor.capability)

    def test_caller_kwargs_override_backend_settings(self) -> None:
        # This is what preserves each caller-parametrised call site verbatim.
        backend = default_powerflow_backend_registry().create(
            PANDAPOWER_NATIVE_BACKEND_ID
        )
        recorded: dict[str, Any] = {}

        class _Spy:
            @staticmethod
            def runpp(net: Any, **kwargs: Any) -> None:
                recorded.update(kwargs)

        with mock.patch.dict(sys.modules, {"pandapower": _Spy}):
            backend.solve(object(), algorithm="bfsw", max_iteration=100)

        self.assertEqual(
            {"algorithm": "bfsw", "init": "auto", "max_iteration": 100}, recorded
        )


class UnknownBackendErrorTest(unittest.TestCase):
    """(b) Unknown-ID resolution raises a located error enumerating the IDs."""

    def test_unknown_id_raises_located_error_enumerating_available_ids(self) -> None:
        registry = default_powerflow_backend_registry()
        with self.assertRaises(UnknownPowerFlowBackendError) as ctx:
            registry.create("nope")
        message = str(ctx.exception)
        self.assertIn("nope", message)
        self.assertIn("available backends:", message)
        for backend_id in (PANDAPOWER_NATIVE_BACKEND_ID, LIGHTSIM2GRID_BACKEND_ID):
            self.assertIn(backend_id, message)

    def test_get_descriptor_uses_the_same_located_error(self) -> None:
        with self.assertRaises(UnknownPowerFlowBackendError):
            default_powerflow_backend_registry().get_descriptor("nope")

    def test_empty_registry_says_none_registered_rather_than_blank(self) -> None:
        with self.assertRaises(UnknownPowerFlowBackendError) as ctx:
            PowerFlowBackendRegistry().create("anything")
        self.assertIn("none registered", str(ctx.exception))

    def test_duplicate_registration_is_refused_without_replace(self) -> None:
        # Phase 14: the default registry is a cached singleton, so
        # registration-mechanics tests build their own registry rather than
        # mutating the shared default.
        registry = PowerFlowBackendRegistry()
        already = _UnregisteredBackend.DESCRIPTOR
        registry.register(_UnregisteredBackend, descriptor=already)
        with self.assertRaises(ValueError) as ctx:
            registry.register(_UnregisteredBackend, descriptor=already)
        self.assertIn(already.backend_id, str(ctx.exception))
        self.assertIn("replace=True", str(ctx.exception))
        # ... and replace=True is the deliberate override.
        registry.register(_UnregisteredBackend, descriptor=already, replace=True)
        self.assertIsInstance(registry.create(already.backend_id), _UnregisteredBackend)


class ImportHygieneTest(unittest.TestCase):
    """(c) Importing the package leaks no heavy or optional dependency."""

    def test_importing_backends_leaks_no_optional_dependency(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _IMPORT_PROBE.format(forbidden=list(_FORBIDDEN_AT_IMPORT)),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=120,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        leaked = completed.stdout.strip().splitlines()[-1]
        self.assertEqual(
            "[]",
            leaked,
            "importing gridalyn.simulation.backends pulled: " + leaked,
        )


class MissingCapabilityTest(unittest.TestCase):
    """(d) Without the ``sim`` extra: MissingCapabilityError, not ImportError."""

    def test_the_hider_actually_hides(self) -> None:
        # Without this, the two tests below could pass vacuously.
        with _absent_lightsim2grid():
            self.assertIsNone(importlib.util.find_spec("lightsim2grid"))
            with self.assertRaises(ImportError):
                importlib.import_module("lightsim2grid")

    def test_lightsim_backend_raises_missing_capability_not_import_error(self) -> None:
        registry = default_powerflow_backend_registry()
        with _absent_lightsim2grid():
            with self.assertRaises(MissingCapabilityError) as ctx:
                registry.create(LIGHTSIM2GRID_BACKEND_ID)
        message = str(ctx.exception)
        self.assertIn("'sim' extra", message)
        self.assertIn('pip install "gridalyn[sim]"', message)
        self.assertIn("gridalyn doctor", message)
        # MissingCapabilityError is a RuntimeError, so a caller catching
        # ImportError to degrade silently cannot swallow it.
        self.assertNotIsInstance(ctx.exception, ImportError)

    def test_default_backend_still_resolves_without_the_sim_extra(self) -> None:
        registry = default_powerflow_backend_registry()
        with _absent_lightsim2grid():
            backend = registry.create(DEFAULT_POWERFLOW_BACKEND_ID)
        self.assertEqual(PANDAPOWER_NATIVE_BACKEND_ID, backend.descriptor.backend_id)


class NoEntryPointsDiscoveryTest(unittest.TestCase):
    """(e) Resolution is by explicit ID only; nothing is auto-discovered."""

    def _registry_module_sources(self) -> dict[str, str]:
        package_dir = Path(registry_module.__file__).parent
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(package_dir.glob("*.py"))
        }

    def test_no_entry_points_call_anywhere_in_the_backends_package(self) -> None:
        # An AST check, not a grep: a grep counts the explanatory comments
        # in contract.py and registry.py that document why discovery is
        # absent, and would fail on the documentation rather than on code.
        offenders: list[str] = []
        for name, source in self._registry_module_sources().items():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Attribute) and node.attr == "entry_points":
                    offenders.append(f"{name}:{node.lineno} attribute entry_points")
                elif isinstance(node, ast.Name) and node.id == "entry_points":
                    offenders.append(f"{name}:{node.lineno} name entry_points")
        self.assertEqual([], offenders, offenders)

    def test_backends_package_imports_no_plugin_discovery_module(self) -> None:
        forbidden = {"pkg_resources", "importlib.metadata", "entrypoints", "stevedore"}
        offenders: list[str] = []
        for name, source in self._registry_module_sources().items():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    offenders += [
                        f"{name}: import {a.name}"
                        for a in node.names
                        if a.name in forbidden
                    ]
                elif isinstance(node, ast.ImportFrom) and node.module in forbidden:
                    offenders.append(f"{name}: from {node.module} import ...")
        self.assertEqual([], offenders, offenders)

    def test_an_unregistered_backend_is_not_resolvable(self) -> None:
        # Phase 14: use a fresh registry; the shared default must not be
        # mutated by a registration-mechanics test. The registry is populated
        # first so this distinguishes "unregistered" from "empty registry".
        registry = PowerFlowBackendRegistry()
        registry.register(_RegisteredProbeBackend)
        backend_id = _UnregisteredBackend.DESCRIPTOR.backend_id
        with self.assertRaises(UnknownPowerFlowBackendError):
            registry.create(backend_id)
        # Explicit registration -- and only that -- makes it resolvable.
        registry.register(_UnregisteredBackend)
        self.assertIsInstance(registry.create(backend_id), _UnregisteredBackend)


class RegistrationSourceTrackingTest(unittest.TestCase):
    """Per-registration source: shipped 'core', extensions 'host' (16-02)."""

    def test_shipped_backends_record_source_core(self) -> None:
        registry = PowerFlowBackendRegistry()
        registry.register(_RegisteredProbeBackend)
        self.assertEqual(
            "core", registry.registration_source("probe_registered_backend")
        )
        self.assertIsNone(registry.registration_version("probe_registered_backend"))

    def test_host_extension_records_source_host_and_version(self) -> None:
        from gridalyn.simulation.backends.registry import (
            register_powerflow_backend_extension,
        )

        registry = PowerFlowBackendRegistry()
        register_powerflow_backend_extension(
            _RegisteredProbeBackend,
            descriptor=PowerFlowBackendDescriptor(
                backend_id="host_probe_backend",
                name="Host-registered probe backend",
            ),
            registry=registry,
            version="2.0.0",
        )
        self.assertEqual("host", registry.registration_source("host_probe_backend"))
        self.assertEqual("2.0.0", registry.registration_version("host_probe_backend"))

    def test_default_registry_ships_everything_as_core(self) -> None:
        registry = default_powerflow_backend_registry()
        for descriptor in registry.list_descriptors():
            with self.subTest(backend_id=descriptor.backend_id):
                self.assertEqual(
                    "core", registry.registration_source(descriptor.backend_id)
                )
                self.assertIsNone(registry.registration_version(descriptor.backend_id))


class SolveSiteReconciliationTest(unittest.TestCase):
    """Zero direct ``pp.runpp`` outside the backends package (AST-derived)."""

    def test_no_direct_runpp_call_outside_the_backends_package(self) -> None:
        package = REPO_ROOT / "gridalyn"
        backends = package / "simulation" / "backends"
        offenders: list[str] = []
        for path in sorted(package.rglob("*.py")):
            if backends in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "runpp"
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        self.assertEqual(
            [],
            offenders,
            "solve power flow through gridalyn.simulation.backends, "
            "not by calling runpp directly:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()

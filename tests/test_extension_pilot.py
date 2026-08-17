"""External-pilot role proof (Phase 18, plan 18-01).

The flagship R21 claim is "components register without editing gridalyn". This
pins it at the ROLE level with a real, committed, outside-gridalyn component:
``examples/extensions/pilot_backend/`` is a conformant power-flow backend that
registers through the declared host mechanism
(``register_powerflow_backend_extension``) and — when a study resolves it — is
recorded in ``provenance.powerflow_backend`` as ``extension_id`` +
``extension_source="host"``.

Isolation: the process-global backend registry is never mutated in-process —
the role-provenance test patches ``default_powerflow_backend_registry`` to a
fresh registry (the Phase-16 pattern).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gridalyn.projects import init_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import _powerflow_backend_provenance
from gridalyn.simulation.backends.pandapower_native import PandapowerNativeBackend
from gridalyn.simulation.backends.registry import PowerFlowBackendRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = REPO_ROOT / "examples" / "extensions" / "pilot_backend"


def _pilot_backend_module() -> object:
    """Import and return the committed external backend module."""
    sys.path.insert(0, str(PILOT_DIR))
    import pilot_backend

    sys.path.remove(str(PILOT_DIR))
    return pilot_backend


def _grid_study_declaring_backend(tmp: str, backend_id: str) -> Path:
    """Scaffold a grid-study project that declares ``backend_id``."""
    import yaml

    target = Path(tmp) / "pilot_case"
    init_project(target, name="pilot_case", template="grid-study")
    project_file = target / "project.yaml"
    data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    data["spec"]["simulation"]["powerflowBackend"] = backend_id
    project_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def _fresh_registry_with_pilot_backend() -> PowerFlowBackendRegistry:
    """A fresh registry: the shipped pandapower-native (core) + the pilot (host)."""
    import pilot_backend

    registry = PowerFlowBackendRegistry()
    registry.register(PandapowerNativeBackend, source="core")
    pilot_backend.register(registry=registry, version="0.1.0")
    return registry


class ExternalRoleExtensionTest(unittest.TestCase):
    """An outside-gridalyn backend serves a role and is recorded (18-01)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pilot = _pilot_backend_module()

    def test_external_backend_descriptor_is_conformant(self) -> None:
        descriptor = self.pilot.descriptor
        self.assertEqual("pilot_native_backend", descriptor.backend_id)
        self.assertIsNone(descriptor.capability)
        self.assertEqual("1", descriptor.contract_version)
        # JSON-native for the manifest (no custom encoder).
        self.assertEqual(
            descriptor.as_dict(), json.loads(json.dumps(descriptor.as_dict()))
        )

    def test_external_backend_registers_as_host(self) -> None:
        registry = PowerFlowBackendRegistry()
        self.pilot.register(registry=registry, version="0.1.0")
        self.assertEqual("host", registry.registration_source("pilot_native_backend"))
        self.assertEqual("0.1.0", registry.registration_version("pilot_native_backend"))

    def test_external_backend_appears_in_backend_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, "pilot_native_backend")
            with mock.patch(
                "gridalyn.simulation.backends.registry"
                ".default_powerflow_backend_registry",
                return_value=_fresh_registry_with_pilot_backend(),
            ):
                provenance = _powerflow_backend_provenance(
                    load_project(target / "project.yaml")
                )
        backend = provenance
        self.assertEqual("pilot_native_backend", backend["backend_id"])
        self.assertEqual("pilot_native_backend", backend["extension_id"])
        self.assertEqual("host", backend["extension_source"])
        self.assertEqual("0.1.0", backend["extension_version"])


if __name__ == "__main__":
    unittest.main()

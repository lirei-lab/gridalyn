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
import subprocess
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
PILOT_SCRIPT = REPO_ROOT / "examples" / "extensions" / "pilot" / "run_pilot.py"


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


class EndToEndPilotTest(unittest.TestCase):
    """The external-pilot run reproduces and populates provenance (18-02).

    Runs ``examples/extensions/pilot/run_pilot.py`` as a subprocess — the pilot
    registers extensions into the process-global registries, so it must run in
    its own process (the Phase-14/16 isolation rule). Pins the ROADMAP criteria
    "end-to-end run reproduces" (determinism) and "provenance.extensions
    present" (host and entry_point sources).
    """

    def _run(self, *extra: str) -> tuple[int, str, str]:
        completed = subprocess.run(
            [sys.executable, str(PILOT_SCRIPT), *extra],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=180,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr

    def test_host_pilot_populates_provenance(self) -> None:
        code, stdout, stderr = self._run()
        self.assertEqual(0, code, stderr[-2000:])
        summary = json.loads(stdout)
        extension_ids = {row["extension_id"] for row in summary["extensions"]}
        self.assertEqual({"pilot_data_source"}, extension_ids)
        self.assertEqual("host", summary["extensions"][0]["source"])
        backend = summary["powerflow_backend"]
        self.assertEqual("pilot_native_backend", backend["extension_id"])
        self.assertEqual("host", backend["extension_source"])

    def test_entry_point_pilot_populates_provenance(self) -> None:
        code, stdout, stderr = self._run("--entry-point")
        self.assertEqual(0, code, stderr[-2000:])
        summary = json.loads(stdout)
        extension_ids = {row["extension_id"] for row in summary["extensions"]}
        self.assertEqual({"hello_world"}, extension_ids)
        self.assertEqual("entry_point", summary["extensions"][0]["source"])
        backend = summary["powerflow_backend"]
        self.assertEqual("pilot_native_backend", backend["extension_id"])
        self.assertEqual("host", backend["extension_source"])

    def test_pilot_run_is_deterministic(self) -> None:
        # Both variants are deterministic — the host extension and the
        # entry-point hello_world (content-hash module_hash is stable per
        # checkout) must print byte-identical summaries across runs.
        for extra in ((), ("--entry-point",)):
            code1, out1, _ = self._run(*extra)
            code2, out2, _ = self._run(*extra)
            self.assertEqual(0, code1, extra)
            self.assertEqual(out1, out2, extra)

    def test_pilot_does_not_touch_projects(self) -> None:
        # R7 guard: the pilot writes only to its system temp dir; projects/
        # must remain untouched. The git returncode is asserted so a git
        # failure (not an empty status) cannot make the guard pass vacuously.
        code, _, stderr = self._run()
        self.assertEqual(0, code, stderr[-2000:])
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "projects"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(0, status.returncode)
        self.assertEqual("", status.stdout)


if __name__ == "__main__":
    unittest.main()

"""CLI tests for the declared-extension discovery surface (Phase 15, 15-02).

The CLI is the awareness/resolution face: ``gridalyn extension list`` reports
installed extensions without importing them (the no-import property itself is
pinned at the engine layer in ``tests/test_extensions.py``), and ``gridalyn
extension validate`` loads only the declared IDs — side-effect free — reporting
provenance facts and exiting non-zero on any undeclared, unimportable, or
unready (missing-capability) ID.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from gridalyn.foundation.platform.extensions import (
    DEFAULT_REGISTRY,
    EntryPointMetadata,
    ExtensionDescriptor,
    UnknownExtensionError,
)
from gridalyn.interfaces.cli import extension


def _descriptor(extension_id: str = "acme-backend") -> ExtensionDescriptor:
    """A resolved-looking entry-point descriptor for CLI output tests."""
    return ExtensionDescriptor(
        extension_id=extension_id,
        role="powerflow_backend",
        name="ACME Backend",
        version="1.2.0",
        contract_version="1",
        source="entry_point",
        entry_point_group="gridalyn.extensions",
    )


class ExtensionListCliTest(unittest.TestCase):
    """``gridalyn extension list`` is the awareness path — no imports."""

    def test_list_prints_descriptor_roster(self) -> None:
        # The no-import property is pinned at the engine layer
        # (test_extensions.py::TestEntryPointDiscovery); this test pins the
        # CLI's output wiring for the roster.
        with mock.patch(
            "gridalyn.interfaces.cli.extension.list_installed_extensions",
            return_value=[_descriptor()],
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = extension.main(["list"])
        self.assertEqual(0, code)
        self.assertIn("acme-backend", stdout.getvalue())
        self.assertIn("entry_point", stdout.getvalue())
        self.assertIn("v1.2.0", stdout.getvalue())

    def test_list_json_is_machine_readable(self) -> None:
        with mock.patch(
            "gridalyn.interfaces.cli.extension.list_installed_extensions",
            return_value=[_descriptor()],
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = extension.main(["list", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("acme-backend", payload[0]["extension_id"])
        self.assertEqual("entry_point", payload[0]["source"])


class ExtensionValidateCliTest(unittest.TestCase):
    """``gridalyn extension validate`` is declared-only resolution."""

    def test_validate_resolves_a_declared_id(self) -> None:
        with (
            mock.patch(
                "gridalyn.interfaces.cli.extension.load_entry_point_extensions",
                return_value=[_descriptor()],
            ),
            mock.patch("gridalyn.interfaces.cli.extension._check_capability_readiness"),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = extension.main(["validate", "acme-backend"])
        self.assertEqual(0, code)
        self.assertIn("acme-backend: OK", stdout.getvalue())
        self.assertIn("contract_version=1", stdout.getvalue())

    def test_validate_undeclared_id_exits_nonzero_with_located_error(self) -> None:
        def _raise(group: str, declared_ids: list[str], **kwargs: object) -> None:
            raise UnknownExtensionError(
                "declared extension 'ghost' is not installed in entry-point "
                "group 'gridalyn.extensions'"
            )

        with mock.patch(
            "gridalyn.interfaces.cli.extension.load_entry_point_extensions",
            side_effect=_raise,
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = extension.main(["validate", "ghost"])
        self.assertEqual(1, code)
        self.assertIn("ghost", stderr.getvalue())
        self.assertIn("not installed", stderr.getvalue())

    def test_validate_requires_at_least_one_id(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = extension.main(["validate"])
        self.assertEqual(2, code)
        self.assertIn("at least one extension ID", stderr.getvalue())


class ExtensionValidateReadinessTest(unittest.TestCase):
    """The capability-readiness gate runs on validate (never silently accepted).

    Uses real fixture modules so the whole chain executes: the CLI loads the
    module through the loader, then ``require_extension_capabilities`` reads its
    ``REQUIRED_CAPABILITIES`` and raises ``MissingCapabilityError`` when they
    cannot be met — the only thing faked is module availability.
    """

    _READY_BODY = """\
from gridalyn.foundation.platform.extensions import ExtensionDescriptor

descriptor = ExtensionDescriptor(
    extension_id="cli-ready-ext",
    role="powerflow_backend",
    name="Ready",
    version="1.0.0",
    contract_version="1",
)

def factory():
    return "ready"
"""

    _UNREADY_BODY = """\
from gridalyn.foundation.platform.extensions import ExtensionDescriptor

REQUIRED_CAPABILITIES = ("sim",)

descriptor = ExtensionDescriptor(
    extension_id="cli-unready-ext",
    role="powerflow_backend",
    name="Unready",
    version="1.0.0",
    contract_version="1",
)

def factory():
    return "unready"
"""

    def _install(self, name: str, body: str) -> list[EntryPointMetadata]:
        """Write a real importable fixture module and return its metadata."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / f"{name}.py").write_text(body, encoding="utf-8")
        sys.path.insert(0, tmp.name)
        self.addCleanup(sys.path.remove, tmp.name)
        return [
            EntryPointMetadata(
                name=f"{name}-ext",
                value=name,
                module=name,
                attr=None,
                distribution="fixture",
                version="1.0.0",
            )
        ]

    def test_validate_accepts_ready_extension(self) -> None:
        records = self._install("cli_ready_a_probe", self._READY_BODY)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = extension.main(["validate", "cli_ready_a_probe-ext"])
        self.assertEqual(0, code)
        self.assertIn("cli_ready_a_probe-ext: OK", stdout.getvalue())

    def test_validate_surfaces_unready_extension(self) -> None:
        records = self._install("cli_unready_b_probe", self._UNREADY_BODY)
        with (
            mock.patch(
                "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
                return_value=records,
            ),
            mock.patch(
                "gridalyn.foundation.platform.capabilities.missing_capability_modules",
                return_value=["lightsim2grid"],
            ),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = extension.main(["validate", "cli_unready_b_probe-ext"])
        self.assertEqual(1, code)
        self.assertIn("cli_unready_b_probe-ext", stderr.getvalue())
        self.assertIn("sim", stderr.getvalue())

    def test_validate_does_not_mutate_default_registry(self) -> None:
        before = [d.extension_id for d in DEFAULT_REGISTRY.list_descriptors()]
        records = self._install("cli_ready_c_probe", self._READY_BODY)
        with mock.patch(
            "gridalyn.foundation.platform.extensions.list_entry_point_metadata",
            return_value=records,
        ):
            code = extension.main(["validate", "cli_ready_c_probe-ext"])
        self.assertEqual(0, code)
        after = [d.extension_id for d in DEFAULT_REGISTRY.list_descriptors()]
        self.assertEqual(before, after)

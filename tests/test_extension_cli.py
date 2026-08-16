"""CLI tests for the declared-extension discovery surface (Phase 15, 15-02).

The CLI is the awareness/resolution face: ``gridalyn extension list`` reports
installed extensions without importing them, and ``gridalyn extension validate``
loads only the declared IDs, reporting provenance facts and exiting non-zero on
any undeclared or unimportable ID.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from gridalyn.foundation.platform.extensions import (
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

    def test_list_reports_installed_extensions_without_importing(self) -> None:
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
        def _raise(group: str, declared_ids: list[str]) -> None:
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

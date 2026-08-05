"""Tests for optional-capability preflight checks and install hints."""

from __future__ import annotations

import unittest
from unittest import mock

from gridalyn.foundation.platform import capabilities


class TestMissingCapabilityModules(unittest.TestCase):
    def test_unknown_capability_lists_known_ones(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            capabilities.missing_capability_modules("does-not-exist")
        self.assertIn("known:", str(ctx.exception))

    def test_all_modules_present_returns_empty(self) -> None:
        with mock.patch.object(
            capabilities.importlib.util, "find_spec", return_value=object()
        ):
            self.assertEqual(capabilities.missing_capability_modules("ops"), [])

    def test_absent_modules_are_reported(self) -> None:
        with mock.patch.object(
            capabilities.importlib.util, "find_spec", return_value=None
        ):
            # lightgbm is deliberately absent: it moved to base dependencies
            # because a missing runtime silently swaps the load generator's
            # macro model, and a base dependency listed as an optional
            # capability is a check that can never fail.
            self.assertEqual(
                capabilities.missing_capability_modules("ops"),
                ["cvxpy"],
            )


class TestRequireCapabilities(unittest.TestCase):
    def test_raises_with_install_hint(self) -> None:
        with mock.patch.object(
            capabilities.importlib.util, "find_spec", return_value=None
        ):
            with self.assertRaises(capabilities.MissingCapabilityError) as ctx:
                capabilities.require_capabilities("ops", context="flexibility commands")

        message = str(ctx.exception)
        self.assertIn("flexibility commands", message)
        self.assertIn("'ops' extra", message)
        self.assertIn('pip install "gridalyn[ops]"', message)
        self.assertIn("gridalyn doctor", message)

    def test_noop_when_everything_installed(self) -> None:
        with mock.patch.object(
            capabilities.importlib.util, "find_spec", return_value=object()
        ):
            capabilities.require_capabilities("ops", "sim", "geo")


class TestDoctorStillUsesSharedRegistry(unittest.TestCase):
    def test_cli_imports_shared_capability_modules(self) -> None:
        from gridalyn.interfaces.cli.gridalyn import OPTIONAL_CAPABILITY_MODULES

        self.assertIs(
            OPTIONAL_CAPABILITY_MODULES,
            capabilities.OPTIONAL_CAPABILITY_MODULES,
        )


if __name__ == "__main__":
    unittest.main()

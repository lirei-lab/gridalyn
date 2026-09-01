"""A weaker local flake8 must announce itself rather than report a clean tree.

The gate loads ``flake8-bugbear`` and ``flake8-docstrings``. A flake8 without
them does not fail differently -- it reports **zero** on a tree the gate
rejects, which is worse than an error, because the contributor is shown a
passing result. This repository has already paid for that once: 0 measured
locally against 67 at the gate.

These tests make the divergence loud at the moment it exists.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRECOMMIT = REPO_ROOT / ".pre-commit-config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: The plugins the gate loads. A local flake8 without these is a different check.
REQUIRED_PLUGINS = ("flake8-bugbear", "flake8-docstrings")

_REMEDY = (
    "Your flake8 is weaker than the gate's and will report a clean tree that "
    "CI rejects. Reinstall the dev extra: pip install -e '.[dev]' (or "
    "uv sync --extra dev), then confirm `flake8 --version` lists "
    + " and ".join(REQUIRED_PLUGINS)
    + "."
)


class TestFlake8PluginParity(unittest.TestCase):
    def test_dev_extra_declares_every_plugin_the_gate_loads(self) -> None:
        """The dev extra and the pre-commit hook must load the same plugins."""
        packaged = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        dev = " ".join(packaged["project"]["optional-dependencies"]["dev"])
        hook = PRECOMMIT.read_text(encoding="utf-8")
        for plugin in REQUIRED_PLUGINS:
            self.assertIn(
                plugin,
                hook,
                f"{plugin} is expected in .pre-commit-config.yaml; if the gate "
                "dropped it, drop it here too rather than diverging",
            )
            self.assertIn(
                plugin,
                dev,
                f"{plugin} is loaded by the gate but absent from the dev extra "
                "-- a dev install would run a strictly weaker check",
            )

    def test_the_installed_flake8_loads_them(self) -> None:
        """Fail loudly here rather than let a weak flake8 report a clean tree."""
        executable = shutil.which("flake8")
        if executable is None:
            self.skipTest(
                "flake8 is not installed in this environment, so no misleading "
                "clean result can be produced by it; install the dev extra to "
                "run the same check the gate runs"
            )
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        missing = [p for p in REQUIRED_PLUGINS if p not in version]
        self.assertEqual(
            missing,
            [],
            f"flake8 --version does not list {', '.join(missing)}.\n{_REMEDY}\n"
            f"Reported: {version.strip()}",
        )


if __name__ == "__main__":
    unittest.main()

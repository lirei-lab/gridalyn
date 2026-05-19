"""Runtime environment defaults for Gridalyn command-line entrypoints."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def configure_cli_environment() -> None:
    """Set quiet, writable defaults before optional plotting imports run."""
    if "MPLCONFIGDIR" in os.environ:
        return
    cache_dir = Path(tempfile.gettempdir()) / "gridalyn-matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)

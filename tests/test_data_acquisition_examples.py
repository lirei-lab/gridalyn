from __future__ import annotations

import subprocess
import sys


def test_download_and_create_grid_osmnx_help_exits_before_work() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "examples/data_acquisition/download_and_create_grid_osmnx.py",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Download OSM building footprints and build a tutorial grid" in result.stdout
    assert "Grid visualization saved" not in result.stdout
    assert "Matplotlib" not in result.stderr

#!/usr/bin/env python3
"""Compatibility wrapper for `python -m gridalyn.interfaces.cli.digital_twin build`."""

from __future__ import annotations

import sys

from gridalyn.interfaces.cli import digital_twin

main = digital_twin.main

COMMANDS = {"build", "scenarios", "timeseries", "base", "powerflow",
            "verify-scenarios", "verify-timeseries", "verify-powerflow",
            "asset-registry", "overload-report", "dashboard-catalog"}


def normalize_argv(argv: list[str]) -> list[str]:
    if not argv or argv[0] not in COMMANDS:
        return ["build", *argv]
    return argv


if __name__ == "__main__":
    raise SystemExit(main(normalize_argv(sys.argv[1:])))

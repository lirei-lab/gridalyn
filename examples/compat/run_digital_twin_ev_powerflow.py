#!/usr/bin/env python3
"""Compatibility wrapper for gridalyn.workflows.scripts.run_digital_twin_ev_powerflow."""

from __future__ import annotations

from gridalyn.interfaces.cli.compat import run_module_as_script


def main(argv: list[str] | None = None) -> int:
    return run_module_as_script("gridalyn.workflows.scripts.run_digital_twin_ev_powerflow", argv)


if __name__ == "__main__":
    raise SystemExit(main())

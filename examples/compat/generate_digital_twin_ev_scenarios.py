#!/usr/bin/env python3
"""Compatibility wrapper for `python -m gridalyn.interfaces.cli.digital_twin scenarios`."""

from __future__ import annotations

from gridalyn.workflows.digital_twin.ev_scenarios import main


if __name__ == "__main__":
    raise SystemExit(main())

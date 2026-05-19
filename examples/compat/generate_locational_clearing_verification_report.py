#!/usr/bin/env python3
"""Compatibility wrapper for `python -m gridalyn.interfaces.cli.flexibility verify-clearing`."""

from __future__ import annotations

from gridalyn.workflows.flexibility.locational_verification import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Helpers for invoking workflow modules from CLI subcommands."""

from __future__ import annotations

import runpy
import sys


def run_module_as_script(module_name: str, argv: list[str] | None = None) -> int:
    """Run a workflow module with script-like argv semantics."""
    previous_argv = sys.argv
    script_args = sys.argv[1:] if argv is None else argv
    sys.argv = [module_name, *script_args]
    try:
        runpy.run_module(module_name, run_name="__main__")
    finally:
        sys.argv = previous_argv
    return 0

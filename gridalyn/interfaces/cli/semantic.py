"""Semantic graph command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.interfaces.cli.script_runner import run_module_as_script

ROOT = Path(__file__).resolve().parents[3]


def _script_handler(script_name: str):
    def handler(args: argparse.Namespace) -> int:
        module_name = f"gridalyn.projects.workflows.scripts.{script_name.removesuffix('.py')}"
        return run_module_as_script(module_name, getattr(args, "script_args", []))

    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scripts = {
        "build": "generate_digital_twin_semantic_graph.py",
        "validate": "validate_digital_twin_semantics.py",
    }
    for command, script_name in scripts.items():
        subcommand = subparsers.add_parser(command)
        subcommand.set_defaults(handler=_script_handler(script_name))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn semantic`` command group.

    Dispatches ``build`` (generate the digital-twin semantic graph) and
    ``validate`` (check the graph against the ontology profile), after
    confirming the optional ``semantic`` capability is installed.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand, or ``2`` if the ``semantic``
        capability is missing.
    """
    from gridalyn.foundation.platform.capabilities import (
        MissingCapabilityError,
        require_capabilities,
    )

    try:
        require_capabilities("semantic", context="semantic graph commands")
    except MissingCapabilityError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args, _extra_args = parse_args(argv)
    return args.handler(args)


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    if extra_args:
        args.script_args = [*getattr(args, "script_args", []), *extra_args]
    return args, extra_args


if __name__ == "__main__":
    raise SystemExit(main())

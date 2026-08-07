"""Semantic graph command line interface."""

from __future__ import annotations

import argparse

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

# The imports below deliberately follow that call, so the E402 they raise is
# waived per-line rather than silenced file-wide. configure_cli_environment()
# sets MPLCONFIGDIR, and matplotlib reads it once at import time -- hoisting
# these imports above the call would leave the variable set too late to have
# any effect, which is a silent failure rather than a loud one.

from gridalyn.interfaces.cli.script_runner import run_module_as_script  # noqa: E402


def _script_handler(script_name: str):
    def handler(args: argparse.Namespace) -> int:
        module_name = (
            f"gridalyn.projects.workflows.scripts.{script_name.removesuffix('.py')}"
        )
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
    ``validate`` (check the graph against the ontology profile). The commands
    are parquet-only and need no optional extra (the former ``semantic``
    capability, whose only module was the unconsumed ``falkordb``, was removed
    2026-08-07).

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand.
    """
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

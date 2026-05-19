"""Dashboard artifact command line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from gridalyn.interfaces.cli.compat import run_module_as_script

ROOT = Path(__file__).resolve().parents[3]


def _script_handler(script_name: str):
    def handler(args: argparse.Namespace) -> int:
        module_name = f"gridalyn.workflows.scripts.{script_name.removesuffix('.py')}"
        return run_module_as_script(module_name, getattr(args, "script_args", []))

    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scripts = {
        "catalog": "generate_digital_twin_dashboard_catalog.py",
        "verify": "verify_dashboard_consistency.py",
    }
    for command, script_name in scripts.items():
        subcommand = subparsers.add_parser(command)
        subcommand.set_defaults(handler=_script_handler(script_name))
    return parser


def main(argv: list[str] | None = None) -> int:
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

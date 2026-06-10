"""Flexibility and network impact command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.interfaces.cli.script_runner import run_module_as_script
from gridalyn.projects.workflows.flexibility import locational_verification


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
        "providers": "generate_digital_twin_flexibility_providers.py",
        "surrogate": "generate_network_impact_surrogate.py",
        "locational-clearing": "generate_locational_flexibility_clearing.py",
        "perturbation-samples": "generate_network_impact_perturbation_samples.py",
        "train-physics-surrogate": "train_network_impact_physics_surrogate.py",
        "verify-network-impact": "generate_network_impact_verification_report.py",
        "shadow-report": "generate_provider_selection_shadow_report.py",
        "scorecard": "generate_flexibility_clearing_scorecard.py",
        "network-impact-catalog": "generate_network_impact_dashboard_catalog.py",
    }
    for command, script_name in scripts.items():
        subcommand = subparsers.add_parser(command)
        subcommand.set_defaults(handler=_script_handler(script_name))

    verify_clearing = subparsers.add_parser("verify-clearing")
    verify_clearing.set_defaults(handler=_workflow_handler(locational_verification.main))
    return parser


def _workflow_handler(main_func):
    def handler(args: argparse.Namespace) -> int:
        return main_func(getattr(args, "script_args", []))

    return handler


def main(argv: list[str] | None = None) -> int:
    from gridalyn.foundation.platform.capabilities import (
        MissingCapabilityError,
        require_capabilities,
    )

    try:
        require_capabilities("ops", context="flexibility commands")
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

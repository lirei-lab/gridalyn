"""Flexibility and network impact command line interface."""

from __future__ import annotations

import argparse
import sys

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


#: One line per subcommand, so ``--help`` explains the surface it exposes.
_HELP = {
    "providers": "Generate the flexibility providers available on the twin",
    "surrogate": "Fit the network-impact surrogate the clearing decides on",
    "locational-clearing": "Clear flexibility locationally against network constraints",
    "network-impact-catalog": "Generate the network-impact dashboard catalog",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    # ``verify-clearing``, ``perturbation-samples``, ``verify-network-impact``,
    # ``shadow-report``, ``scorecard`` and ``train-physics-surrogate`` were
    # RETIRED on 2026-08-06 together
    # together with the input they depended on. All five read
    # ``flexibility/market_dispatch_timeseries.parquet``, which no command in
    # this repository writes -- it came from a study that was consolidated
    # away -- so they could not succeed anywhere here.
    # ``train-physics-surrogate`` went with them: its labels parquet was
    # written only by ``perturbation-samples``, so retiring that command left
    # it with no producer either. See
    # docs/development/instruction-verification.md.
    scripts = {
        "providers": "generate_digital_twin_flexibility_providers.py",
        "surrogate": "generate_network_impact_surrogate.py",
        "locational-clearing": "generate_locational_flexibility_clearing.py",
        "network-impact-catalog": "generate_network_impact_dashboard_catalog.py",
    }
    for command, script_name in scripts.items():
        subcommand = subparsers.add_parser(command, help=_HELP[command])
        subcommand.set_defaults(handler=_script_handler(script_name))

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn market`` command group.

    Dispatches the flexibility and network-impact commands -- provider
    registry, network-impact surrogate, locational clearing and the
    network-impact catalog -- after confirming the optional
    ``ops`` capability is installed.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand, or ``2`` if the ``ops``
        capability is missing.
    """
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

"""Platform governance command line interface."""

from __future__ import annotations

import argparse
import json

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.foundation.platform.artifacts import check_artifact_policy
from gridalyn.foundation.platform.workspace import workspace_from_path


def _check_artifacts(args: argparse.Namespace) -> int:
    payload = _artifact_policy_payload(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


def _artifact_policy_payload(args: argparse.Namespace) -> dict[str, object]:
    workspace = workspace_from_path(args.root)
    report = check_artifact_policy(workspace.root)
    payload = report.to_dict()
    if args.summary_only:
        payload = {
            "valid": payload["valid"],
            "error_count": len(payload["errors"]),
            "warning_count": len(payload["warnings"]),
            "summary": payload["summary"],
        }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_artifacts = subparsers.add_parser(
        "check-artifacts",
        help="Check Git artifact policy and the minimal demo dataset contract.",
    )
    check_artifacts.add_argument("--root", default=".")
    check_artifacts.add_argument("--summary-only", action="store_true")
    check_artifacts.set_defaults(handler=_check_artifacts)
    return parser


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    return args, extra_args


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn platform`` command group.

    Dispatches the governance commands, currently ``check-artifacts``, which
    checks the Git artifact policy and the minimal demo dataset contract.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand handler.
    """
    args, _extra_args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

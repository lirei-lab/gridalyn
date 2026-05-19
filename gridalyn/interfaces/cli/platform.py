"""Platform governance command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.foundation.platform.artifacts import check_artifact_policy


ROOT = Path(__file__).resolve().parents[3]


def _check_artifacts(args: argparse.Namespace) -> int:
    report = check_artifact_policy(Path(args.root))
    payload = report.to_dict()
    if args.summary_only:
        payload = {
            "valid": payload["valid"],
            "error_count": len(payload["errors"]),
            "warning_count": len(payload["warnings"]),
            "summary": payload["summary"],
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.valid else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_artifacts = subparsers.add_parser(
        "check-artifacts",
        help="Check Git artifact policy and the minimal demo dataset contract.",
    )
    check_artifacts.add_argument("--root", default=ROOT)
    check_artifacts.add_argument("--summary-only", action="store_true")
    check_artifacts.set_defaults(handler=_check_artifacts)
    return parser


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    return args, extra_args


def main(argv: list[str] | None = None) -> int:
    args, _extra_args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

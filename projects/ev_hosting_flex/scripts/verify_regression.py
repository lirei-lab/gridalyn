"""Verify EV hosting flexibility outputs against the project regression baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.projects.regression import (
    DEFAULT_BASELINE,
    DEFAULT_REPORT,
    run_project_regression,
)

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_project_regression(
        project_root=args.project_root,
        baseline=args.baseline,
        report=args.report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

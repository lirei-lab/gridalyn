"""Project workspace command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.foundation.platform.projects import (
    init_project,
    load_project,
    plan_project,
    project_regression,
    project_sense_check,
    project_status,
    project_verify,
    run_workflow,
    validate_project,
)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _init(args: argparse.Namespace) -> int:
    created = init_project(
        Path(args.project),
        name=args.name,
        force=args.force,
        template=args.template,
    )
    _print_json(
        {
            "created": str(created.root),
            "project_file": str(created.project_file),
            "workflow_file": str(created.workflow_file),
        }
    )
    return 0


def _validate(args: argparse.Namespace) -> int:
    report = validate_project(
        Path(args.project),
        check_artifacts=args.check_artifacts,
    )
    _print_json(report.__dict__)
    return 0 if report.valid else 1


def _plan(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    _print_json(
        {
            "project": project.name,
            "stages": [
                {"id": stage.id, "command": stage.command}
                for stage in plan_project(project)
            ],
        }
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    executed = run_workflow(
        Path(args.project),
        dry_run=args.dry_run,
        manifest_path=Path(args.manifest_path) if args.manifest_path else None,
    )
    _print_json({"executed": executed})
    return 0


def _status(args: argparse.Namespace) -> int:
    _print_json(
        project_status(
            Path(args.project),
            check_artifacts=args.check_artifacts,
        )
    )
    return 0


def _regression(args: argparse.Namespace) -> int:
    report = project_regression(Path(args.project))
    _print_json(report)
    return 0 if report.get("valid") else 1


def _sense_check(args: argparse.Namespace) -> int:
    report = project_sense_check(Path(args.project), write=not args.no_write)
    _print_json(report)
    return 0 if report.get("valid") else 1


def _verify(args: argparse.Namespace) -> int:
    report = project_verify(Path(args.project), write=not args.no_write)
    _print_json(report)
    return 0 if report.get("valid") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("project")
    init_parser.add_argument("--name")
    init_parser.add_argument(
        "--template",
        default="minimal",
        choices=["minimal", "grid-study"],
        help="Project scaffold template to create.",
    )
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=_init)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("project")
    validate_parser.add_argument("--check-artifacts", action="store_true")
    validate_parser.set_defaults(handler=_validate)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("project")
    plan_parser.set_defaults(handler=_plan)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("project")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--manifest-path")
    run_parser.set_defaults(handler=_run)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("project")
    status_parser.add_argument("--check-artifacts", action="store_true")
    status_parser.set_defaults(handler=_status)

    regression_parser = subparsers.add_parser("regression")
    regression_parser.add_argument("project")
    regression_parser.set_defaults(handler=_regression)

    sense_parser = subparsers.add_parser("sense-check")
    sense_parser.add_argument("project")
    sense_parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run checks without writing outputs/reports/project_sense_check_report.json.",
    )
    sense_parser.set_defaults(handler=_sense_check)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("project")
    verify_parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run verification without writing outputs/reports/project_sense_check_report.json.",
    )
    verify_parser.set_defaults(handler=_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

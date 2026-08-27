from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages, run_project
from gridalyn.projects.validation import validate_project_file


def _validate(args: argparse.Namespace) -> int:
    report = validate_project_file(
        Path(args.project),
        check_artifacts=args.check_artifacts,
    )
    print(json.dumps(report.__dict__, indent=2))
    return 0 if report.valid else 1


def _plan(args: argparse.Namespace) -> int:
    report = validate_project_file(Path(args.project))
    if not report.valid:
        print(json.dumps(report.__dict__, indent=2))
        return 1
    project = load_project(Path(args.project))
    for index, stage in enumerate(plan_stages(project), start=1):
        print(f"{index}. {stage.id}: {stage.command}")
    return 0


def _run(args: argparse.Namespace) -> int:
    report = validate_project_file(Path(args.project))
    if not report.valid:
        print(json.dumps(report.__dict__, indent=2))
        return 1
    project = load_project(Path(args.project))
    executed = run_project(
        project,
        dry_run=args.dry_run,
        manifest_path=Path(args.manifest_path) if args.manifest_path else None,
    )
    print(json.dumps({"executed": executed}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m gridalyn.projects.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Check project.yaml/workflow.yaml against the schema"
    )
    validate_parser.add_argument("project")
    validate_parser.add_argument("--check-artifacts", action="store_true")
    validate_parser.set_defaults(func=_validate)

    plan_parser = subparsers.add_parser(
        "plan", help="Print the stage DAG in execution order without running anything"
    )
    plan_parser.add_argument("project")
    plan_parser.set_defaults(func=_plan)

    run_parser = subparsers.add_parser(
        "run", help="Execute the workflow stages and write governed artifacts"
    )
    run_parser.add_argument("project")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--manifest-path")
    run_parser.set_defaults(func=_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

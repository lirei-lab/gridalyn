"""Project workspace command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

# The imports below deliberately follow that call, so the E402 they raise is
# waived per-line rather than silenced file-wide. configure_cli_environment()
# sets MPLCONFIGDIR, and matplotlib reads it once at import time -- hoisting
# these imports above the call would leave the variable set too late to have
# any effect, which is a silent failure rather than a loud one.

from gridalyn.projects.api import (  # noqa: E402
    init_project,
    list_projects,
    load_project,
    plan_project,
    prepare_project_workspace,
    project_regression,
    project_sense_check,
    project_status,
    project_verify,
    project_verify_all,
    run_workflow,
    validate_project,
)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _list_templates(args: argparse.Namespace) -> int:
    from gridalyn.projects.templates import TEMPLATES

    _print_json(
        {
            "templates": [
                {"name": template.name, "description": template.description}
                for template in TEMPLATES.values()
            ]
        }
    )
    return 0


def _init(args: argparse.Namespace) -> int:
    if args.list_templates:
        return _list_templates(args)
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
        echo=not args.quiet,
        stages=args.stage or None,
    )
    _print_json({"executed": executed})
    return 0


def _prepare_workspace(args: argparse.Namespace) -> int:
    report = prepare_project_workspace(Path(args.project))
    _print_json(report.to_dict())
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


def _list(args: argparse.Namespace) -> int:
    _print_json({"projects": list_projects(Path(args.root))})
    return 0


def _verify_all(args: argparse.Namespace) -> int:
    report = project_verify_all(Path(args.root), write=args.write)
    _print_json(report)
    return 0 if report.get("valid") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    from gridalyn.projects.templates import TEMPLATES

    init_parser = subparsers.add_parser(
        "init", help="Scaffold a new study directory from a template"
    )
    init_parser.add_argument("project", nargs="?", default=".")
    init_parser.add_argument("--name")
    init_parser.add_argument(
        "--template",
        default="minimal",
        choices=sorted(TEMPLATES),
        help="Project scaffold template to create.",
    )
    init_parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available templates and exit.",
    )
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=_init)

    validate_parser = subparsers.add_parser(
        "validate",
        help=(
            "Check project.yaml/workflow.yaml against the schema "
            "(is the contract well-formed?)"
        ),
    )
    validate_parser.add_argument("project")
    validate_parser.add_argument("--check-artifacts", action="store_true")
    validate_parser.set_defaults(handler=_validate)

    plan_parser = subparsers.add_parser(
        "plan", help="Print the stage DAG in execution order without running anything"
    )
    plan_parser.add_argument("project")
    plan_parser.set_defaults(handler=_plan)

    run_parser = subparsers.add_parser(
        "run", help="Execute the workflow stages and write governed artifacts"
    )
    run_parser.add_argument("project")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--manifest-path")
    run_parser.add_argument(
        "--stage",
        action="append",
        help="Run only this stage and its dependencies (repeatable).",
    )
    run_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable per-stage progress output.",
    )
    run_parser.set_defaults(handler=_run)

    prepare_parser = subparsers.add_parser(
        "prepare-workspace",
        help="Create the outputs/ directories a study's stages write into",
    )
    prepare_parser.add_argument("project")
    prepare_parser.set_defaults(handler=_prepare_workspace)

    status_parser = subparsers.add_parser(
        "status", help="Report which artifacts and reports a study has produced so far"
    )
    status_parser.add_argument("project")
    status_parser.add_argument("--check-artifacts", action="store_true")
    status_parser.set_defaults(handler=_status)

    regression_parser = subparsers.add_parser(
        "regression",
        help="Compare results against baselines/results_baseline.json (did the numbers move?)",
    )
    regression_parser.add_argument("project")
    regression_parser.set_defaults(handler=_regression)

    sense_parser = subparsers.add_parser(
        "sense-check",
        help="Run the study's objective plausibility checks (do the numbers make sense?)",
    )
    sense_parser.add_argument("project")
    sense_parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run checks without writing outputs/reports/project_sense_check_report.json.",
    )
    sense_parser.set_defaults(handler=_sense_check)

    verify_parser = subparsers.add_parser(
        "verify",
        help=(
            "Run the ladder: contract + artifact status + sense checks, "
            "as one payload. Excludes regression"
        ),
    )
    verify_parser.add_argument("project")
    verify_parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run verification without writing "
        "outputs/reports/project_sense_check_report.json.",
    )
    verify_parser.set_defaults(handler=_verify)

    list_parser = subparsers.add_parser(
        "list", help="List the studies found under a workspace root"
    )
    list_parser.add_argument("--root", default=".")
    list_parser.set_defaults(handler=_list)

    verify_all_parser = subparsers.add_parser(
        "verify-all",
        help="Run the verify ladder over every study under a workspace root",
    )
    verify_all_parser.add_argument("--root", default=".")
    verify_all_parser.add_argument(
        "--write", action="store_true", help="Write project sense-check reports."
    )
    verify_all_parser.set_defaults(handler=_verify_all)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn project`` command group.

    Dispatches the project-workspace lifecycle commands — ``init``,
    ``validate``, ``plan``, ``run``, ``prepare-workspace``, ``status``,
    ``regression``, ``sense-check``, ``verify``, ``verify-all`` and ``list``.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand handler.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

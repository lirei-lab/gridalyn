"""Gridalyn product command line interface."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn.foundation.platform.capabilities import OPTIONAL_CAPABILITY_MODULES
from gridalyn.foundation.platform.validation import validate_workspace
from gridalyn.projects.api import list_projects


DOMAIN_MODULES: dict[str, tuple[str, str, list[str]]] = {
    "twin": ("gridalyn.interfaces.cli.digital_twin", "Build and inspect digital-twin artifacts.", ["dt", "model"]),
    "project": ("gridalyn.interfaces.cli.project", "Create, validate, plan, and run project workflows.", ["projects"]),
    "market": ("gridalyn.interfaces.cli.flexibility", "Run flexibility-market and network-impact commands.", ["flex", "flexibility"]),
    "semantic": ("gridalyn.interfaces.cli.semantic", "Build and validate the semantic graph.", ["semantics"]),
    "dashboard": ("gridalyn.interfaces.cli.dashboard", "Generate and validate dashboard catalogs.", ["dash"]),
    "platform": ("gridalyn.interfaces.cli.platform", "Run platform governance and artifact checks.", ["governance"]),
}


def _domain_module_name(token: str) -> str | None:
    for name, (module_name, _help_text, aliases) in DOMAIN_MODULES.items():
        if token == name or token in aliases:
            return module_name
    return None


def _delegate_domain_help(argv: list[str] | None) -> int | None:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if len(tokens) >= 2 and tokens[1] in {"-h", "--help"}:
        module_name = _domain_module_name(tokens[0])
        if module_name is None:
            return None
        module = importlib.import_module(module_name)
        return module.main(["--help"])
    return None


def _delegate_module(module_name: str):
    def handler(args: argparse.Namespace) -> int:
        module = importlib.import_module(module_name)
        return module.main(getattr(args, "subcommand_args", []))

    return handler


def _validate(args: argparse.Namespace) -> int:
    payload = validate_workspace(
        Path(args.root),
        projects=args.project,
        check_project_artifacts=args.check_project_artifacts,
        run_regression=args.regression,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


def _doctor(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = validate_workspace(root)
    projects = list_projects(root)
    try:
        version = importlib.metadata.version("gridalyn")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    optional = {
        capability: {
            module_name: importlib.util.find_spec(module_name) is not None
            for module_name in module_names
        }
        for capability, module_names in OPTIONAL_CAPABILITY_MODULES.items()
    }
    payload = {
        "valid": bool(workspace.get("valid")),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "gridalyn": {
            "version": version,
        },
        "workspace": {
            "root": str(root.resolve()),
            "valid": workspace.get("valid"),
            "errors": workspace.get("errors", []),
            "warnings": workspace.get("warnings", []),
        },
        "projects": {
            "count": len(projects),
            "items": projects,
        },
        "optional_capabilities": optional,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


def _quickstart(args: argparse.Namespace) -> int:
    from gridalyn.foundation.platform.capabilities import (
        MissingCapabilityError,
        require_capabilities,
    )
    from gridalyn.projects.api import init_project, run_workflow

    try:
        require_capabilities("sim", context="the quickstart power-flow demo")
    except MissingCapabilityError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    target = Path(args.project)
    created = init_project(target, name=args.name, template="powerflow-demo")
    print(f"created project workspace: {created.root}", file=sys.stderr)
    run_workflow(created.root, echo=True)

    figure = created.root / "outputs" / "figures" / "powerflow_demo_voltage_profile.png"
    report = created.root / "outputs" / "reports" / "powerflow_demo_report.json"
    print("", file=sys.stderr)
    print("Quickstart complete. Artifacts:", file=sys.stderr)
    print(f"  figure: {figure}", file=sys.stderr)
    print(f"  report: {report}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Next steps:", file=sys.stderr)
    print(f"  gridalyn project status {target} --check-artifacts", file=sys.stderr)
    print(f"  gridalyn project verify {target}", file=sys.stderr)
    print(f"  edit {target}/scripts/run_powerflow_study.py to make it yours", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gridalyn",
        description=(
            "Gridalyn utility digital-twin platform CLI. "
            "Use a domain command followed by that domain's subcommand."
        ),
    )
    subparsers = parser.add_subparsers(dest="domain", required=True)

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Create and run a small power-flow demo project (first simulation in one command).",
    )
    quickstart_parser.add_argument("project", help="Directory to create the demo project in.")
    quickstart_parser.add_argument("--name", help="Project name (defaults to the directory name).")
    quickstart_parser.set_defaults(handler=_quickstart)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Run the unified workspace validation ladder.",
    )
    validate_parser.add_argument("--root", default=".")
    validate_parser.add_argument(
        "--project",
        action="append",
        help="Project path to validate. May be provided multiple times.",
    )
    validate_parser.add_argument(
        "--check-project-artifacts",
        dest="check_project_artifacts",
        action="store_true",
        default=False,
        help="Also check required project reports and figures exist.",
    )
    validate_parser.add_argument(
        "--regression",
        action="store_true",
        help="Also run configured project regression checks.",
    )
    validate_parser.set_defaults(handler=_validate)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect the local Gridalyn installation, workspace, projects, and optional capabilities.",
    )
    doctor_parser.add_argument("--root", default=".")
    doctor_parser.set_defaults(handler=_doctor)

    for name, (module_name, help_text, aliases) in DOMAIN_MODULES.items():
        command = subparsers.add_parser(name, aliases=aliases, help=help_text)
        command.set_defaults(handler=_delegate_module(module_name))
    return parser


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    args.subcommand_args = extra_args
    return args, extra_args


def main(argv: list[str] | None = None) -> int:
    delegated_help = _delegate_domain_help(argv)
    if delegated_help is not None:
        return delegated_help
    args, _extra_args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

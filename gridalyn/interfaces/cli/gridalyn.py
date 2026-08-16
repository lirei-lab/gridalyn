"""Gridalyn product command line interface."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

# The imports below deliberately follow that call, so the E402 they raise is
# waived per-line rather than silenced file-wide. configure_cli_environment()
# sets MPLCONFIGDIR, and matplotlib reads it once at import time -- hoisting
# these imports above the call would leave the variable set too late to have
# any effect, which is a silent failure rather than a loud one.

from gridalyn.foundation.platform.capabilities import (  # noqa: E402
    OPTIONAL_CAPABILITY_MODULES,
)

# ``_looks_like_workspace`` is the single source of truth for what counts as a
# workspace; re-deriving the marker set here would drift. ``find_workspace_root``
# falls back to returning its start path, so the predicate is the only way to
# tell "found" from "not found".
from gridalyn.foundation.platform.workspace import (  # noqa: E402
    _looks_like_workspace,
    find_workspace_root,
)
from gridalyn.projects.api import list_projects  # noqa: E402
from gridalyn.projects.validation import validate_workspace  # noqa: E402

DOMAIN_MODULES: dict[str, tuple[str, str, list[str]]] = {
    "twin": (
        "gridalyn.interfaces.cli.digital_twin",
        "Build and inspect digital-twin artifacts.",
        ["dt", "model"],
    ),
    "project": (
        "gridalyn.interfaces.cli.project",
        "Create, validate, plan, and run project workflows.",
        ["projects"],
    ),
    "market": (
        "gridalyn.interfaces.cli.flexibility",
        "Run flexibility-market and network-impact commands.",
        ["flex", "flexibility"],
    ),
    "semantic": (
        "gridalyn.interfaces.cli.semantic",
        "Build and validate the semantic graph.",
        ["semantics"],
    ),
    "dashboard": (
        "gridalyn.interfaces.cli.dashboard",
        "Generate and validate dashboard catalogs.",
        ["dash"],
    ),
    "platform": (
        "gridalyn.interfaces.cli.platform",
        "Run platform governance and artifact checks.",
        ["governance"],
    ),
    "extension": (
        "gridalyn.interfaces.cli.extension",
        "List, validate, and inspect installed extensions.",
        ["extensions"],
    ),
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


def _delegate_module(module_name: str) -> Any:
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
    try:
        version = importlib.metadata.version("gridalyn")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    python_section = {
        "version": sys.version.split()[0],
        "executable": sys.executable,
    }
    optional = {
        capability: {
            module_name: importlib.util.find_spec(module_name) is not None
            for module_name in module_names
        }
        for capability, module_names in OPTIONAL_CAPABILITY_MODULES.items()
    }
    if not _looks_like_workspace(find_workspace_root(root)):
        # A pip-installed gridalyn with no checkout nearby is a healthy
        # installation -- there is simply no workspace to lint. Running
        # ``validate_workspace`` here would apply gridalyn's own artifact
        # policy to an arbitrary directory and exit 1 over nothing the user
        # can act on.
        payload = {
            "valid": True,
            "python": python_section,
            "gridalyn": {"version": version},
            "workspace": {
                "found": False,
                "searched_from": str(root.resolve()),
                "note": (
                    f"no Gridalyn workspace found at or above {root.resolve()}; "
                    "create one with 'gridalyn quickstart <directory>' or point "
                    "doctor at an existing workspace with --root <workspace>"
                ),
            },
            "projects": {"count": 0, "items": []},
            "optional_capabilities": optional,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    # Artifact checks are deliberately off, matching `gridalyn validate`'s own
    # argparse default: project ``outputs/`` are git-ignored, so requiring them
    # here would make doctor exit 1 on every fresh checkout -- the same
    # "nothing the user can act on" failure the no-workspace branch avoids.
    # `gridalyn validate --check-project-artifacts` remains the opt-in.
    workspace = validate_workspace(root, check_project_artifacts=False)
    projects = list_projects(root)
    payload = {
        "valid": bool(workspace.get("valid")),
        "python": python_section,
        "gridalyn": {
            "version": version,
        },
        "workspace": {
            "found": True,
            "root": str(root.resolve()),
            "valid": workspace.get("valid"),
            # `validate_workspace` returns {valid, checks, summary} -- it has no
            # top-level "errors"/"warnings". Reading those keys returned an empty
            # list unconditionally, so doctor exited 1 while reporting nothing a
            # user could act on. The failing checks are the diagnosis.
            "failed_checks": [
                check
                for check in workspace.get("checks", [])
                if not check.get("valid", True)
            ],
            "summary": workspace.get("summary", {}),
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
    # No capability preflight: the demo imports only pandapower, a base
    # dependency that is always present on a supported install.
    from gridalyn.projects.api import init_project, run_workflow

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
    print(
        f"  edit {target}/scripts/run_powerflow_study.py to make it yours",
        file=sys.stderr,
    )
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
        help="Create and run a small power-flow demo project "
        "(first simulation in one command).",
    )
    quickstart_parser.add_argument(
        "project", help="Directory to create the demo project in."
    )
    quickstart_parser.add_argument(
        "--name", help="Project name (defaults to the directory name)."
    )
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
        help="Inspect the local Gridalyn installation, workspace, "
        "projects, and optional capabilities.",
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
    """Run the root ``gridalyn`` command.

    Handles the top-level ``quickstart``, ``validate`` and ``doctor`` commands,
    and otherwise delegates to the domain CLI registered in
    :data:`DOMAIN_MODULES` — ``twin``, ``project``, ``market``, ``semantic``,
    ``dashboard`` or ``platform`` — including their aliases and ``--help``.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected command or delegated domain CLI.
    """
    delegated_help = _delegate_domain_help(argv)
    if delegated_help is not None:
        return delegated_help
    args, _extra_args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Digital twin command line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

# The imports below deliberately follow that call, so the E402 they raise is
# waived per-line rather than silenced file-wide. configure_cli_environment()
# sets MPLCONFIGDIR, and matplotlib reads it once at import time -- hoisting
# these imports above the call would leave the variable set too late to have
# any effect, which is a silent failure rather than a loud one.

from gridalyn.foundation import ArtifactLayout  # noqa: E402
from gridalyn.interfaces.cli.script_runner import run_module_as_script  # noqa: E402
from gridalyn.projects.workflows.digital_twin import (  # noqa: E402
    ev_scenarios,
    ev_timeseries,
)
from gridalyn.projects.workflows.digital_twin.build import (  # noqa: E402
    run_digital_twin_build,
)
from gridalyn.twin.geoprocess import (  # noqa: E402
    clip_buildings_by_polygon,
    download_osm_building_footprints,
    load_polygon_coordinates,
    prepare_microsoft_building_footprints,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__: in an installed wheel that resolves to
# site-packages, where reads return {} and writes land inside the package.
_DEFAULT_ROOT = Path(".")


def _require_workspace_root(root: Path) -> Path:
    """Resolve and validate a CLI-provided workspace root.

    Args:
        root: Root passed on the command line; defaults to the current
            directory.

    Returns:
        The resolved, existing root directory.

    Raises:
        FileNotFoundError: If ``root`` does not exist or is not a directory.
            The message names the root and the remedy so a misconfigured
            ``--root`` cannot silently write into (or read from) the wrong
            location.
    """
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"{resolved}: not an existing directory; the digital-twin build "
            "reads and writes under <root>/instances/default/digital_twin, "
            "with every path composed from ArtifactLayout. Run from a "
            "workspace root, or pass --root <workspace>."
        )
    return resolved


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _parse_capabilities(value: str | None) -> set[str] | None:
    """Parse a comma-separated ``--capabilities`` value into a declared set.

    ``None`` keeps the legacy build (``ev-hosting`` + ``flexibility`` assumed);
    an empty string declares an explicit empty set, i.e. a generic model-first
    build with no capability layers.
    """

    if value is None:
        return None
    return {cap.strip() for cap in value.split(",") if cap.strip()}


def _set_instance_environment(args: argparse.Namespace) -> None:
    """Thread the selected twin instance into a dispatched layer script.

    Layer scripts resolve their artifact layout from
    ``GRIDALYN_INSTANCE``/``GRIDALYN_WORKSPACE_ROOT`` via
    ``layout_from_environment``, so a single general script can materialize on
    any named twin instance of any workspace root. Both variables default to
    the canonical ``default`` instance and current directory when unset, so
    running a script directly resolves exactly what it did before these
    variables existed.
    """

    root = getattr(args, "root", None)
    if root is not None:
        os.environ["GRIDALYN_WORKSPACE_ROOT"] = str(Path(root).resolve())
    os.environ["GRIDALYN_INSTANCE"] = getattr(args, "instance", "default")


#: One line per loop-registered subcommand, so ``--help`` explains the surface
#: it exposes rather than listing bare verbs.
_HELP = {
    "scenarios": "Generate EV adoption scenarios over the twin",
    "timeseries": "Generate EV charging time series for the scenarios",
    "base": "Export the twin's base network model",
    "building-models": "Generate building models for the twin's dwellings",
    "scenario-models": "Generate per-scenario network models",
    "powerflow": "Run power flow over the twin's EV scenarios",
    "verify-scenarios": "Check the generated EV scenarios for contract violations",
    "verify-timeseries": "Check the generated EV time series for contract violations",
    "verify-powerflow": "Check the EV power-flow results for contract violations",
    "asset-registry": "Generate the twin's device and asset registry",
    "overload-report": "Report MV/LV transformers loaded past their rating",
    "dashboard-catalog": "Generate the twin's dashboard catalog",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build or plan digital twin artifacts.")
    build.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help=(
            "Workspace root containing instances/<instance>/digital_twin "
            "(default: current directory)."
        ),
    )
    build.add_argument(
        "--instance",
        default="default",
        help=(
            "Named twin instance under <root>/instances/<instance>/digital_twin "
            "(default: default). Build any project's twin by selecting its "
            "instance."
        ),
    )
    build.add_argument(
        "--capabilities",
        default=None,
        help=(
            "Comma-separated capability layers to include (default: the legacy "
            "ev-hosting,flexibility build). Pass an empty value for a generic "
            "model-first build with no capability layers."
        ),
    )
    build.add_argument("--skip-heavy", action="store_true")
    build.add_argument("--include-network-impact", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--continue-on-error", action="store_true")
    build.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Destination for the build manifest (default: "
            "<root>/instances/<instance>/digital_twin/reports/"
            "digital_twin_build_manifest.json)."
        ),
    )
    build.set_defaults(handler=handle_build)

    clip = subparsers.add_parser(
        "clip-buildings", help="Clip building GeoJSON to a polygon."
    )
    clip.add_argument("--buildings-file", type=Path, required=True)
    clip.add_argument("--polygon-file", type=Path, required=True)
    clip.add_argument("--output-file", type=Path, required=True)
    clip.set_defaults(handler=handle_clip_buildings)

    osm = subparsers.add_parser(
        "download-osm-buildings", help="Download OSM building footprints with OSMnx."
    )
    osm.add_argument("--polygon-file", type=Path, required=True)
    osm.add_argument("--output-file", type=Path, required=True)
    osm.set_defaults(handler=handle_download_osm_buildings)

    microsoft = subparsers.add_parser(
        "prepare-microsoft-buildings",
        help="Convert local Microsoft building-footprint partitions to GeoJSON.",
    )
    microsoft.add_argument("--input-file", type=Path, required=True)
    microsoft.add_argument("--output-file", type=Path, required=True)
    microsoft.add_argument("--polygon-file", type=Path)
    microsoft.add_argument("--limit", type=int)
    microsoft.set_defaults(handler=handle_prepare_microsoft_buildings)

    workflow_commands = {
        "scenarios": ev_scenarios.main,
        "timeseries": ev_timeseries.main,
    }
    for command, main_func in workflow_commands.items():
        subcommand = subparsers.add_parser(command, help=_HELP[command])
        subcommand.add_argument(
            "--root",
            type=Path,
            default=_DEFAULT_ROOT,
            help="Workspace root (default: current directory).",
        )
        subcommand.add_argument(
            "--instance",
            default="default",
            help="Named twin instance (default: default).",
        )
        subcommand.set_defaults(handler=_workflow_handler(main_func))

    scripts = {
        "base": "export_digital_twin_base.py",
        "building-models": "generate_digital_twin_building_models.py",
        "scenario-models": "generate_digital_twin_scenario_models.py",
        "powerflow": "run_digital_twin_ev_powerflow.py",
        "verify-scenarios": "verify_digital_twin_ev_scenarios.py",
        "verify-timeseries": "verify_digital_twin_ev_timeseries.py",
        "verify-powerflow": "verify_digital_twin_ev_powerflow.py",
        "asset-registry": "generate_digital_twin_asset_registry.py",
        "overload-report": "report_mv_lv_transformer_overloads.py",
        "dashboard-catalog": "generate_digital_twin_dashboard_catalog.py",
    }
    for command, script_name in scripts.items():
        subcommand = subparsers.add_parser(command, help=_HELP[command])
        subcommand.add_argument(
            "--root",
            type=Path,
            default=_DEFAULT_ROOT,
            help="Workspace root (default: current directory).",
        )
        subcommand.add_argument(
            "--instance",
            default="default",
            help="Named twin instance (default: default).",
        )
        subcommand.set_defaults(handler=_script_handler(script_name))
    return parser


def _workflow_handler(main_func):
    def handler(args: argparse.Namespace) -> int:
        _set_instance_environment(args)
        return main_func(getattr(args, "script_args", []))

    return handler


def _script_handler(script_name: str):
    def handler(args: argparse.Namespace) -> int:
        _set_instance_environment(args)
        module_name = (
            f"gridalyn.projects.workflows.scripts.{script_name.removesuffix('.py')}"
        )
        return run_module_as_script(module_name, getattr(args, "script_args", []))

    return handler


def handle_build(args: argparse.Namespace) -> int:
    root = _require_workspace_root(args.root)
    layout = ArtifactLayout(root, instance=args.instance)
    manifest_path = args.manifest or (
        layout.reports / "digital_twin_build_manifest.json"
    )
    manifest = run_digital_twin_build(
        root=root,
        skip_heavy=args.skip_heavy,
        include_network_impact=args.include_network_impact,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        manifest_path=manifest_path,
        instance=args.instance,
        capabilities=_parse_capabilities(args.capabilities),
    )
    print(
        json.dumps(
            {
                "dry_run": manifest["dry_run"],
                "instance": manifest.get("instance", "default"),
                "step_count": manifest["step_count"],
                "manifest": _display_path(manifest_path),
                "steps": [step["name"] for step in manifest["steps"]],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def handle_clip_buildings(args: argparse.Namespace) -> int:
    clip_buildings_by_polygon(
        buildings_file=args.buildings_file,
        polygon_coordinates=load_polygon_coordinates(args.polygon_file),
        output_file=args.output_file,
    )
    print(
        json.dumps(
            {"output_file": _display_path(args.output_file)}, indent=2, sort_keys=True
        )
    )
    return 0


def handle_download_osm_buildings(args: argparse.Namespace) -> int:
    download_osm_building_footprints(
        polygon_coordinates=load_polygon_coordinates(args.polygon_file),
        output_file=args.output_file,
    )
    print(
        json.dumps(
            {"output_file": _display_path(args.output_file)}, indent=2, sort_keys=True
        )
    )
    return 0


def handle_prepare_microsoft_buildings(args: argparse.Namespace) -> int:
    count = prepare_microsoft_building_footprints(
        input_path=args.input_file,
        output_path=args.output_file,
        polygon_path=args.polygon_file,
        limit=args.limit,
    )
    print(
        json.dumps(
            {"feature_count": count, "output_file": _display_path(args.output_file)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the ``gridalyn twin`` command group.

    Dispatches ``build`` (assemble twin artifacts), ``clip-buildings``, and
    ``download-osm-buildings`` to their handlers.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code from the selected subcommand handler.
    """
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

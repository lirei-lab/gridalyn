"""Digital twin command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridalyn.interfaces.cli.compat import run_module_as_script
from gridalyn.twin.geoprocess import (
    clip_buildings_by_polygon,
    download_osm_building_footprints,
    load_polygon_coordinates,
    prepare_microsoft_building_footprints,
)
from gridalyn.workflows.digital_twin.build import run_digital_twin_build
from gridalyn.workflows.digital_twin import ev_scenarios, ev_timeseries


ROOT = Path(__file__).resolve().parents[3]


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build or plan digital twin artifacts.")
    build.add_argument("--skip-heavy", action="store_true")
    build.add_argument("--include-network-impact", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--continue-on-error", action="store_true")
    build.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "instances" / "default" / "digital_twin" / "reports" / "digital_twin_build_manifest.json",
    )
    build.set_defaults(handler=handle_build)

    clip = subparsers.add_parser("clip-buildings", help="Clip building GeoJSON to a polygon.")
    clip.add_argument("--buildings-file", type=Path, required=True)
    clip.add_argument("--polygon-file", type=Path, required=True)
    clip.add_argument("--output-file", type=Path, required=True)
    clip.set_defaults(handler=handle_clip_buildings)

    osm = subparsers.add_parser("download-osm-buildings", help="Download OSM building footprints with OSMnx.")
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
        subcommand = subparsers.add_parser(command)
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
        subcommand = subparsers.add_parser(command)
        subcommand.set_defaults(handler=_script_handler(script_name))
    return parser


def _workflow_handler(main_func):
    def handler(args: argparse.Namespace) -> int:
        return main_func(getattr(args, "script_args", []))

    return handler


def _script_handler(script_name: str):
    def handler(args: argparse.Namespace) -> int:
        module_name = f"gridalyn.workflows.scripts.{script_name.removesuffix('.py')}"
        return run_module_as_script(module_name, getattr(args, "script_args", []))

    return handler


def handle_build(args: argparse.Namespace) -> int:
    manifest = run_digital_twin_build(
        root=ROOT,
        skip_heavy=args.skip_heavy,
        include_network_impact=args.include_network_impact,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "dry_run": manifest["dry_run"],
                "step_count": manifest["step_count"],
                "manifest": _display_path(args.manifest),
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
    print(json.dumps({"output_file": _display_path(args.output_file)}, indent=2, sort_keys=True))
    return 0


def handle_download_osm_buildings(args: argparse.Namespace) -> int:
    download_osm_building_footprints(
        polygon_coordinates=load_polygon_coordinates(args.polygon_file),
        output_file=args.output_file,
    )
    print(json.dumps({"output_file": _display_path(args.output_file)}, indent=2, sort_keys=True))
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

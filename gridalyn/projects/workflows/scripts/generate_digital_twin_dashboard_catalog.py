#!/usr/bin/env python3
"""Generate the generic dashboard catalog for the digital twin grid viewer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import layout_from_environment  # noqa: E402

DEFAULT_LAYOUT = layout_from_environment(default_root=ROOT)

from gridalyn.projects.dashboard_catalog import (  # noqa: E402
    build_dashboard_catalog,
    write_dashboard_catalog,
)
from gridalyn.projects.loader import load_project  # noqa: E402
from gridalyn.twin.network import NetworkModelRepository  # noqa: E402

DEFAULT_SCENARIO_INDEX = DEFAULT_LAYOUT.scenarios / "index.json"
DEFAULT_BASE_DIR = DEFAULT_LAYOUT.base
DEFAULT_POWERFLOW_SUMMARY = DEFAULT_LAYOUT.timeseries / "powerflow_smoke_summary.json"
DEFAULT_SEMANTIC_DIR = DEFAULT_LAYOUT.semantic
DEFAULT_SCENARIO_ASSETS = DEFAULT_LAYOUT.scenarios / "asset_registry.parquet"
DEFAULT_OBSERVATIONS_DIR = DEFAULT_LAYOUT.observations
DEFAULT_OUT = DEFAULT_LAYOUT.dashboard / "catalog.json"
DEFAULT_EXTENSIONS = {
    "network_impact": DEFAULT_LAYOUT.flexibility / "network_impact_catalog.json",
    "clearing_scorecard": DEFAULT_LAYOUT.flexibility
    / "flexibility_clearing_scorecard.json",
    "operations": DEFAULT_LAYOUT.operations / "operations_catalog.json",
}


def _discover_projects(root: Path) -> list:
    """Load every governed study under ``projects/``, skipping broken ones.

    A study whose ``project.yaml`` will not parse must not take the whole
    catalog down with it: the twin's scenarios and geography are unrelated to
    it. The failure is echoed to stderr rather than swallowed, so a study that
    silently stops appearing in the dashboard still says why.
    """
    projects = []
    for manifest in sorted((root / "projects").glob("*/project.yaml")):
        try:
            projects.append(load_project(manifest))
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            print(
                f"warning: skipping {manifest}: {error}",
                file=sys.stderr,
                flush=True,
            )
    return projects


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-index", type=Path, default=DEFAULT_SCENARIO_INDEX)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument(
        "--powerflow-summary", type=Path, default=DEFAULT_POWERFLOW_SUMMARY
    )
    parser.add_argument("--semantic-dir", type=Path, default=DEFAULT_SEMANTIC_DIR)
    parser.add_argument("--scenario-assets", type=Path, default=DEFAULT_SCENARIO_ASSETS)
    parser.add_argument(
        "--observations-dir", type=Path, default=DEFAULT_OBSERVATIONS_DIR
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = build_dashboard_catalog(
        scenario_index=_load_json(args.scenario_index),
        powerflow_summary=_load_json(args.powerflow_summary),
        optional_extensions=DEFAULT_EXTENSIONS,
        root=ROOT,
        network_repository=NetworkModelRepository.from_parquet(args.base_dir),
        projects=_discover_projects(ROOT),
        semantic_dir=args.semantic_dir,
        scenario_assets=args.scenario_assets,
        observations_dir=args.observations_dir,
    )
    write_dashboard_catalog(args.out, catalog)
    print(
        json.dumps(
            {
                "out": _relpath(args.out),
                "scenario_count": len(catalog["scenarios"]),
                "report_id": catalog["report_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

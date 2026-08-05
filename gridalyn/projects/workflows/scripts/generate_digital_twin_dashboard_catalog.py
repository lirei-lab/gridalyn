#!/usr/bin/env python3
"""Generate the generic dashboard catalog for the digital twin grid viewer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

# LAYER-DIRECTION EXCEPTION: projects -> gridalyn.interfaces.reporting.dashboard_catalog.
# `build_dashboard_catalog` / `write_dashboard_catalog` are pure catalog
# builders whose only gridalyn dependency is `gridalyn.twin.network`, but they
# are filed under `interfaces.reporting`, so reaching them from here crosses
# upward. This module is a stage-script entry point (see the package docstring:
# "script entrypoints, not domain logic"), yet it is not a top-of-stack
# composition root: `gridalyn.interfaces.cli.dashboard` and
# `gridalyn.interfaces.cli.digital_twin` dispatch *downward* into it via
# `run_module_as_script`, so this import closes an
# interfaces -> projects -> interfaces cycle.
# The exception is scoped to this one file, deliberately NOT to the scripts
# package: the other 21 modules in this directory import only foundation,
# twin, assets, simulation and operations, and already obey the direction.
# Removing it means relocating
# `gridalyn/interfaces/reporting/dashboard_catalog.py` to a layer at or below
# `projects` (`twin` suffices, given its only import) and updating its
# importers -- outside this change's scope.
# Registered in tests/test_layer_direction.py::_DOCUMENTED_EXCEPTIONS.
from gridalyn.interfaces.reporting.dashboard_catalog import (
    build_dashboard_catalog,
    write_dashboard_catalog,
)
from gridalyn.twin.network import NetworkModelRepository

DEFAULT_SCENARIO_INDEX = DEFAULT_LAYOUT.scenarios / "index.json"
DEFAULT_BASE_DIR = DEFAULT_LAYOUT.base
DEFAULT_POWERFLOW_SUMMARY = DEFAULT_LAYOUT.timeseries / "powerflow_smoke_summary.json"
DEFAULT_OUT = DEFAULT_LAYOUT.dashboard / "catalog.json"
DEFAULT_EXTENSIONS = {
    "network_impact": DEFAULT_LAYOUT.flexibility / "network_impact_catalog.json",
    "clearing_scorecard": DEFAULT_LAYOUT.flexibility
    / "flexibility_clearing_scorecard.json",
    "operations": DEFAULT_LAYOUT.operations / "operations_catalog.json",
}


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

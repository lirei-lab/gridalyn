#!/usr/bin/env python3
"""Generate the dashboard catalog for scenario-specific Network Impact reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.simulation.analytics.network_impact.catalog import (
    build_network_impact_catalog,
    write_network_impact_catalog,
)


DEFAULT_SCENARIO_INDEX = DEFAULT_LAYOUT.scenarios / "index.json"
DEFAULT_OUT = DEFAULT_LAYOUT.flexibility / "network_impact_catalog.json"
DEFAULT_REPORTS = {
    "physicsLabels": DEFAULT_LAYOUT.flexibility / "network_impact_physics_labels_report.json",
    "physicsSurrogate": DEFAULT_LAYOUT.flexibility / "network_impact_physics_surrogate_report.json",
    "topologyVerification": DEFAULT_LAYOUT.flexibility / "network_impact_verification_report.json",
    "physicsVerification": DEFAULT_LAYOUT.flexibility / "network_impact_physics_verification_report.json",
}


def _expected_scenarios(index_path: Path) -> list[str]:
    if not index_path.exists():
        return ["S0", "S1", "S2", "S3", "S4"]
    index = json.loads(index_path.read_text())
    scenarios = [
        str(item["scenario_id"])
        for item in index.get("scenarios", [])
        if item.get("scenario_id")
    ]
    return scenarios or ["S0", "S1", "S2", "S3", "S4"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-index", type=Path, default=DEFAULT_SCENARIO_INDEX)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = build_network_impact_catalog(
        DEFAULT_REPORTS,
        expected_scenarios=_expected_scenarios(args.scenario_index),
        root=ROOT,
    )
    write_network_impact_catalog(args.out, catalog)
    print(
        json.dumps(
            {
                "out": str(args.out.relative_to(ROOT)),
                "available_scenarios": catalog["available_scenarios"],
                "expected_scenarios": catalog["expected_scenarios"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

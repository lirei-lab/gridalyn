#!/usr/bin/env python3
"""Generate a policy scorecard for flexibility clearing intelligence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.operations.market.scorecard import (
    build_flexibility_clearing_scorecard,
    write_flexibility_clearing_scorecard,
)


DEFAULT_REPORT_DIR = DEFAULT_LAYOUT.flexibility
DEFAULT_TOPOLOGY_REPORT = DEFAULT_REPORT_DIR / "network_impact_verification_report.json"
DEFAULT_PHYSICS_REPORT = DEFAULT_REPORT_DIR / "network_impact_physics_verification_report.json"
DEFAULT_MARKET_REPORT = DEFAULT_REPORT_DIR / "market_clearing_report.json"
DEFAULT_LOCATIONAL_REPORT = DEFAULT_REPORT_DIR / "locational_clearing_verification_report.json"
DEFAULT_OUT = DEFAULT_REPORT_DIR / "flexibility_clearing_scorecard.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_optional_json(path: Path) -> dict | None:
    return _load_json(path) if path.exists() else None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--physics-report", type=Path, default=DEFAULT_PHYSICS_REPORT)
    parser.add_argument("--market-report", type=Path, default=DEFAULT_MARKET_REPORT)
    parser.add_argument("--locational-report", type=Path, default=DEFAULT_LOCATIONAL_REPORT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    topology_report = _load_json(args.topology_report)
    physics_report = _load_optional_json(args.physics_report)
    market_report = _load_optional_json(args.market_report)
    locational_report = _load_optional_json(args.locational_report)
    scorecard = build_flexibility_clearing_scorecard(
        topology_report=topology_report,
        physics_report=physics_report,
        market_report=market_report,
        locational_report=locational_report,
    )
    scorecard["inputs"] = {
        "topology_report": _relpath(args.topology_report),
        "physics_report": _relpath(args.physics_report) if args.physics_report.exists() else None,
        "market_report": _relpath(args.market_report) if args.market_report.exists() else None,
        "locational_report": _relpath(args.locational_report) if args.locational_report.exists() else None,
    }
    write_flexibility_clearing_scorecard(args.out, scorecard)
    print(
        json.dumps(
            {
                "out": _relpath(args.out),
                "scenario_id": scorecard["scenario_id"],
                "summary": scorecard["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

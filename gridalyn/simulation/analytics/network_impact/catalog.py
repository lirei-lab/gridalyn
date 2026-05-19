"""Scenario catalog for dashboard network-impact report discovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _web_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        relative = path
    return "/" + str(relative).replace("\\", "/")


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def build_network_impact_catalog(
    report_paths: dict[str, Path],
    *,
    expected_scenarios: list[str],
    root: Path,
) -> dict[str, Any]:
    """Group existing Network Impact reports by their declared scenario_id."""
    scenarios: dict[str, dict[str, Any]] = {
        scenario_id: {
            "scenario_id": scenario_id,
            "status": "not_generated",
            "reports": {},
            "reason": "No network-impact report artifacts found for this scenario.",
        }
        for scenario_id in expected_scenarios
    }

    for report_name, path in report_paths.items():
        report = _load_report(path)
        if not report:
            continue
        scenario_id = str(report.get("scenario_id") or "").strip()
        if not scenario_id:
            continue
        scenario = scenarios.setdefault(
            scenario_id,
            {
                "scenario_id": scenario_id,
                "status": "not_generated",
                "reports": {},
                "reason": "Scenario discovered from network-impact report artifact.",
            },
        )
        scenario["status"] = "available"
        scenario["reason"] = None
        scenario["reports"][report_name] = _web_path(path, root)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "network_impact_catalog",
        "schema_version": "1.0",
        "expected_scenarios": expected_scenarios,
        "available_scenarios": [
            scenario_id
            for scenario_id, scenario in sorted(scenarios.items())
            if scenario["status"] == "available"
        ],
        "scenarios": dict(sorted(scenarios.items())),
    }


def write_network_impact_catalog(path: Path, catalog: dict[str, Any]) -> Path:
    """Write the dashboard Network Impact catalog."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True))
    return path

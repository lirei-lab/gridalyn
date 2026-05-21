"""Verify the current digital-twin dashboard catalog contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.workspace import ArtifactLayout, find_workspace_root

ROOT = find_workspace_root(__file__)
LAYOUT = ArtifactLayout(ROOT)
DEFAULT_CATALOG = LAYOUT.dashboard / "catalog.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_repo_path(web_path: str) -> Path:
    return ROOT / web_path.lstrip("/")


def verify_dashboard_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    """Validate dashboard catalog metadata and referenced scenario files."""
    errors: list[str] = []
    if not path.exists():
        return {
            "valid": False,
            "catalog": str(path),
            "scenario_count": 0,
            "errors": [f"missing dashboard catalog: {path}"],
        }

    catalog = _load_json(path)
    if catalog.get("report_id") != "digital_twin_dashboard_catalog":
        errors.append("catalog report_id must be digital_twin_dashboard_catalog")
    if catalog.get("schema_version") != "1.0":
        errors.append("catalog schema_version must be 1.0")

    scenarios = catalog.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("catalog must include at least one scenario")
        scenarios = []

    scenario_ids: list[str] = []
    for index, scenario in enumerate(scenarios):
        scenario_id = str(scenario.get("scenario_id") or "")
        if not scenario_id:
            errors.append(f"scenario[{index}] missing scenario_id")
            continue
        scenario_ids.append(scenario_id)
        paths = scenario.get("paths")
        if not isinstance(paths, dict):
            errors.append(f"scenario {scenario_id} paths must be a mapping")
            continue
        for kind in ("nodes", "lines", "power", "transformers"):
            value = paths.get(kind)
            if not value:
                errors.append(f"scenario {scenario_id} missing {kind} path")
                continue
            if "dashboard/public" in str(value):
                errors.append(f"scenario {scenario_id} uses removed dashboard/public path: {value}")
                continue
            if not _existing_repo_path(str(value)).exists():
                errors.append(f"scenario {scenario_id} missing referenced {kind} file: {value}")

    duplicates = sorted({scenario_id for scenario_id in scenario_ids if scenario_ids.count(scenario_id) > 1})
    for scenario_id in duplicates:
        errors.append(f"duplicate scenario_id: {scenario_id}")

    return {
        "valid": not errors,
        "catalog": str(path),
        "scenario_count": len(scenario_ids),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    report = verify_dashboard_catalog(args.catalog)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

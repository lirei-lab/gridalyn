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

SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("1.0", "1.1", "1.2", "1.3", "1.4")
"""Catalog schema versions this verifier accepts, oldest first.

A *set* rather than a single literal, because the checks below read only the
keys 1.0 introduced. Pinning one version turned every additive bump into a
false failure -- 1.1 added ``network_model.geography`` and changed nothing this
function reads, yet the equality check would have rejected it. 1.2
(``projects``), 1.3 (``semantic``) and 1.4 (``observation``) are additive on the
same terms. A version that genuinely removes or repurposes a key read here
should be left out of this tuple, which is what makes the omission meaningful.
"""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_repo_path(web_path: str) -> Path:
    return ROOT / web_path.lstrip("/")


def _scenario_path_errors(scenario_id: str, paths: Any) -> list[str]:
    """Return every problem with one scenario's declared artifact paths.

    Split out of :func:`verify_dashboard_catalog` so that function stays under
    the complexity ceiling; the checks themselves are unchanged.

    Args:
        scenario_id: Scenario the paths belong to, used to locate each message.
        paths: The scenario's ``paths`` value, validated here rather than
            assumed to be a mapping.

    Returns:
        Located error strings, empty when every declared path resolves.
    """
    if not isinstance(paths, dict):
        return [f"scenario {scenario_id} paths must be a mapping"]
    errors: list[str] = []
    for kind in ("nodes", "lines", "power", "transformers"):
        value = paths.get(kind)
        if not value:
            errors.append(f"scenario {scenario_id} missing {kind} path")
        elif "dashboard/public" in str(value):
            errors.append(
                f"scenario {scenario_id} uses removed dashboard/public "
                f"path: {value}"
            )
        elif not _existing_repo_path(str(value)).exists():
            errors.append(
                f"scenario {scenario_id} missing referenced {kind} file: {value}"
            )
    return errors


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
    schema_version = catalog.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"catalog schema_version {schema_version!r} is not supported "
            f"(supported: {', '.join(SUPPORTED_SCHEMA_VERSIONS)}); regenerate "
            "the catalog with `gridalyn dashboard catalog`"
        )

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
        errors.extend(_scenario_path_errors(scenario_id, scenario.get("paths")))

    duplicates = sorted(
        {
            scenario_id
            for scenario_id in scenario_ids
            if scenario_ids.count(scenario_id) > 1
        }
    )
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

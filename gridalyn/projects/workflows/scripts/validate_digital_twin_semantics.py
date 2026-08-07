"""Validate generated semantic graph artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import ArtifactLayout, find_workspace_root
from gridalyn.twin.semantic.mappings import north_america_profile
from gridalyn.twin.semantic.validation import (
    validate_semantic_graph,
    write_validation_report,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__ (Phase 9, finding G7).
_DEFAULT_ROOT = Path(".")

DEFAULT_LAYOUT = ArtifactLayout(_DEFAULT_ROOT)

DEFAULT_SEMANTIC_DIR = DEFAULT_LAYOUT.semantic
DEFAULT_SCENARIO_DIR = DEFAULT_LAYOUT.scenarios


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def _expected_counts_from_asset_summary(
    scenario_dir: Path,
) -> dict[str, dict[str, int]]:
    summary_path = scenario_dir / "asset_registry_summary.json"
    if not summary_path.exists():
        return {}
    summary = _load_json(summary_path)
    return {
        scenario["scenario_id"]: {
            "n_ev": int(scenario["n_ev"]),
            "n_soft_participants": int(scenario["n_soft_participants"]),
            "n_hard_preferred": int(scenario["n_hard_preferred"]),
        }
        for scenario in summary.get("scenarios", [])
    }


def validate_semantic_artifacts(
    *,
    semantic_dir: Path,
    scenario_dir: Path,
    root: Path | None = None,
) -> dict[str, Any]:
    semantic_dir = semantic_dir.resolve()
    scenario_dir = scenario_dir.resolve()
    nodes = pd.read_parquet(semantic_dir / "nodes.parquet")
    edges = pd.read_parquet(semantic_dir / "edges.parquet")
    report = validate_semantic_graph(
        nodes,
        edges,
        north_america_profile(),
        expected_scenario_counts=_expected_counts_from_asset_summary(scenario_dir),
    )
    report_path = semantic_dir / "validation_report.json"
    write_validation_report(report, report_path)

    manifest_path = semantic_dir / "graph_manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        workspace_root = (
            Path(root).resolve()
            if root is not None
            else find_workspace_root(semantic_dir)
        )
        try:
            report_rel = str(report_path.resolve().relative_to(workspace_root))
        except ValueError as exc:
            raise RuntimeError(
                f"validation report {report_path} is outside the workspace root "
                f"{workspace_root}; run from a workspace root or pass --root=<workspace>"
            ) from exc
        manifest["validation"] = {
            "valid": bool(report["valid"]),
            "error_count": int(report["error_count"]),
            "warning_count": int(report["warning_count"]),
            "report": report_rel,
        }
        with manifest_path.open("w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate digital-twin semantic graph artifacts."
    )
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--semantic-dir", type=Path, default=DEFAULT_SEMANTIC_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    args = parser.parse_args()

    report = validate_semantic_artifacts(
        semantic_dir=args.semantic_dir,
        scenario_dir=args.scenario_dir,
        root=find_workspace_root(args.root),
    )
    print(
        f"Semantic validation valid={report['valid']} "
        f"errors={report['error_count']} warnings={report['warning_count']}"
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate generated semantic graph artifacts.

A graph is validated against the profile it was **built** with: the
capabilities its ``graph_manifest.json`` records. Until 2026-09-10 this script
validated every graph against the model-first core profile, so the default full
graph -- built with the ``flexibility`` capability -- failed with 40 errors while
being valid (measured on the shipped twin).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import find_workspace_root, layout_from_environment
from gridalyn.twin.semantic.mappings import (
    profile_with_capabilities,
    resolve_declared_capabilities,
)
from gridalyn.twin.semantic.validation import (
    validate_semantic_graph,
    write_validation_report,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__ (Phase 9, finding G7).
_DEFAULT_ROOT = Path(".")

DEFAULT_LAYOUT = layout_from_environment(default_root=_DEFAULT_ROOT)

DEFAULT_SEMANTIC_DIR = DEFAULT_LAYOUT.semantic
DEFAULT_SCENARIO_DIR = DEFAULT_LAYOUT.scenarios

#: Recorded when a graph predates manifests that name their capabilities.
LEGACY_CAPABILITIES_WARNING = (
    "graph manifest records no semantic capabilities; validated against the "
    "legacy default ({capabilities}) -- rebuild the graph with "
    "`gridalyn semantic build` to record them"
)


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


def _split_expected_counts(
    expected: dict[str, dict[str, int]], profile: dict[str, Any]
) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Keep the counts the profile has a rule for; name the ones it has not.

    A core-only graph built beside a scenario registry cannot count EVs, and
    that is not the graph's error -- but it is not silently fine either, so the
    skipped keys are returned for the report to state.
    """
    rules = profile.get("scenario_counts", {})
    skipped = sorted(
        {key for counts in expected.values() for key in counts} - set(rules)
    )
    kept = {
        scenario_id: {key: value for key, value in counts.items() if key in rules}
        for scenario_id, counts in expected.items()
    }
    return kept, skipped


def validate_semantic_artifacts(
    *,
    semantic_dir: Path,
    scenario_dir: Path,
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate a materialized graph and record the verdict in its manifest.

    Args:
        semantic_dir: Directory holding ``nodes.parquet``, ``edges.parquet``
            and ``graph_manifest.json``.
        scenario_dir: Directory holding ``asset_registry_summary.json``.
        root: Workspace root for manifest-relative paths; discovered when unset.

    Returns:
        The validation report, also written to ``validation_report.json``.
    """
    semantic_dir = semantic_dir.resolve()
    scenario_dir = scenario_dir.resolve()
    nodes = pd.read_parquet(semantic_dir / "nodes.parquet")
    edges = pd.read_parquet(semantic_dir / "edges.parquet")
    manifest_path = semantic_dir / "graph_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {}
    recorded = manifest.get("capabilities")
    capabilities = resolve_declared_capabilities(
        None if recorded is None else [str(capability) for capability in recorded]
    )
    profile = profile_with_capabilities(capabilities)
    expected, skipped = _split_expected_counts(
        _expected_counts_from_asset_summary(scenario_dir), profile
    )
    report = validate_semantic_graph(
        nodes, edges, profile, expected_scenario_counts=expected
    )
    declared = ", ".join(sorted(capabilities)) or "none"
    if recorded is None:
        report["warnings"].append(
            LEGACY_CAPABILITIES_WARNING.format(capabilities=declared)
        )
    if skipped:
        report["warnings"].append(
            f"scenario counts {', '.join(skipped)} were not checked: the profile "
            f"for capabilities [{declared}] declares no rule for them"
        )
    report["warning_count"] = len(report["warnings"])
    report["capabilities"] = sorted(capabilities)
    report_path = semantic_dir / "validation_report.json"
    write_validation_report(report, report_path)

    if manifest_path.exists():
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

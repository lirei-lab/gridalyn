"""Build canonical reports from digital-twin artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from gridalyn.foundation import ArtifactLayout
from gridalyn.interfaces.reporting.schemas import (
    canonical_report,
    load_json,
    now_iso,
    relpath,
    write_json,
    write_report,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__: in an installed wheel that resolves to
# site-packages, where reads return {} and writes land inside the package.
_DEFAULT_ROOT = Path(".")


def _load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.exists() else {}


def build_digital_twin_reports(
    *,
    root: Path = _DEFAULT_ROOT,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the canonical digital-twin reports for a workspace root.

    Args:
        root: Workspace root containing ``instances/default/digital_twin``.
            Defaults to the current directory, matching ``ArtifactLayout``.
        out_dir: Destination directory for the canonical reports; defaults to
            ``<root>/instances/default/digital_twin/reports/canonical``.

    Returns:
        The canonical report manifest, mapping report ids to written paths.

    Raises:
        FileNotFoundError: If ``root`` holds no digital-twin artifact tree —
            the guard that keeps an installed package from reading empty
            inputs and writing degenerate reports outside a workspace.
    """
    root = root.resolve()
    layout = ArtifactLayout(root)
    if not layout.digital_twin.is_dir():
        raise FileNotFoundError(
            f"{layout.digital_twin}: no digital-twin artifact tree under root "
            f"{root}; canonical reports would be built from empty inputs and "
            "written outside a workspace. Run from a workspace root containing "
            "instances/default/digital_twin, or pass root=<workspace> "
            "(--root on the command line)."
        )
    out_dir = (out_dir or (layout.reports / "canonical")).resolve()
    reports_dir = layout.reports
    semantic_dir = layout.semantic
    scenarios_dir = layout.scenarios

    transformer_path = reports_dir / "mv_lv_transformer_overload_report.json"
    semantic_manifest_path = semantic_dir / "graph_manifest.json"
    semantic_validation_path = semantic_dir / "validation_report.json"
    asset_summary_path = scenarios_dir / "asset_registry_summary.json"

    transformer = _load_optional_json(transformer_path)
    semantic_manifest = _load_optional_json(semantic_manifest_path)
    semantic_validation = _load_optional_json(semantic_validation_path)
    asset_summary = _load_optional_json(asset_summary_path)

    report_paths: dict[str, str] = {}

    network_report = canonical_report(
        report_id="network_capacity",
        title="Digital Twin Network Capacity and Transformer Loading",
        root=root,
        inputs=[transformer_path],
        metrics={
            "overall": transformer.get("overall", {}),
            "scenarios": transformer.get("scenarios", []),
        },
        artifacts={
            "mv_lv_transformer_overload_report": (
                relpath(transformer_path, root) if transformer_path.exists() else None
            ),
        },
        stage="network_capacity",
        source_domain="digital_twin",
        project_name="digital_twin",
    )
    report_paths["network_capacity"] = write_report(
        out_dir / "network_capacity_report.json", network_report, root=root
    )

    asset_report = canonical_report(
        report_id="scenario_registry",
        title="Digital Twin Scenario and Asset Registry",
        root=root,
        inputs=[asset_summary_path],
        metrics={
            "n_scenarios": asset_summary.get("n_scenarios"),
            "scenarios": asset_summary.get("scenarios", []),
            "soft_participation_rate": asset_summary.get("soft_participation_rate"),
            "soft_assignment_seed": asset_summary.get("soft_assignment_seed"),
        },
        artifacts={
            "asset_registry": "instances/default/digital_twin/scenarios/asset_registry.parquet",
            "asset_registry_summary": (
                relpath(asset_summary_path, root)
                if asset_summary_path.exists()
                else None
            ),
        },
        stage="scenario_registry",
        source_domain="digital_twin",
        project_name="digital_twin",
    )
    report_paths["scenario_registry"] = write_report(
        out_dir / "scenario_registry_report.json", asset_report, root=root
    )

    semantic_report = canonical_report(
        report_id="semantic_graph",
        title="North America Semantic Graph",
        root=root,
        inputs=[semantic_manifest_path, semantic_validation_path],
        metrics={
            "semantic_profile": semantic_manifest.get("semantic_profile"),
            "node_count": semantic_manifest.get("node_count"),
            "edge_count": semantic_manifest.get("edge_count"),
            "validation": semantic_manifest.get("validation", semantic_validation),
            "count_checks": semantic_manifest.get("count_checks", {}),
            "namespaces": semantic_manifest.get("namespaces", {}),
        },
        artifacts={
            "graph_manifest": (
                relpath(semantic_manifest_path, root)
                if semantic_manifest_path.exists()
                else None
            ),
            "nodes": semantic_manifest.get("artifacts", {}).get("nodes"),
            "edges": semantic_manifest.get("artifacts", {}).get("edges"),
            "validation_report": semantic_manifest.get("artifacts", {}).get(
                "validation_report"
            ),
        },
        stage="semantic_graph",
        source_domain="digital_twin",
        project_name="digital_twin",
    )
    report_paths["semantic_graph"] = write_report(
        out_dir / "semantic_graph_report.json", semantic_report, root=root
    )

    manifest = {
        "report_id": "digital_twin_report_manifest",
        "schema_version": "1.0",
        "created_at": now_iso(),
        "source_domain": "digital_twin",
        "reports": report_paths,
    }
    write_json(out_dir / "digital_twin_report_manifest.json", manifest)
    return manifest


def main() -> None:
    """Build canonical digital-twin reports for a workspace root."""
    parser = argparse.ArgumentParser(
        description="Build canonical digital-twin reports."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help=(
            "Workspace root containing instances/default/digital_twin "
            "(default: current directory)."
        ),
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    manifest = build_digital_twin_reports(root=args.root, out_dir=args.out_dir)
    print(f"Built digital-twin canonical reports: {len(manifest['reports'])} reports")


if __name__ == "__main__":
    main()

"""Generate the federated semantic graph artifacts for the digital twin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import find_workspace_root, layout_from_environment
from gridalyn.twin.network import NetworkModelRepository
from gridalyn.twin.semantic.mappings import build_semantic_graph, write_profile

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__: in an installed wheel that resolves to
# site-packages, not the workspace (Phase 9, finding G7).
_DEFAULT_ROOT = Path(".")

DEFAULT_LAYOUT = layout_from_environment(default_root=_DEFAULT_ROOT)

DEFAULT_BASE_DIR = DEFAULT_LAYOUT.base
DEFAULT_SCENARIO_DIR = DEFAULT_LAYOUT.scenarios
DEFAULT_FLEXIBILITY_DIR = DEFAULT_LAYOUT.flexibility
DEFAULT_TIMESERIES_DIR = DEFAULT_LAYOUT.timeseries
DEFAULT_OUT_DIR = DEFAULT_LAYOUT.semantic


def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _resolve_root(root: Path | None, fallback_dir: Path) -> Path:
    """Return the workspace root, discovered from the fallback dir if unset."""
    if root is not None:
        return Path(root).resolve()
    return find_workspace_root(fallback_dir)


def _relpath(path: Path, root: Path) -> str:
    """Return ``path`` relative to the workspace root, failing loudly outside."""
    try:
        return str(path.resolve().relative_to(Path(root).resolve()))
    except ValueError as exc:
        raise RuntimeError(
            f"artifact {path} is outside the workspace root {root}; run the "
            "script from a workspace root or pass --root=<workspace>"
        ) from exc


def generate_semantic_graph(
    *,
    profile: str,
    base_dir: Path,
    scenario_dir: Path,
    flexibility_dir: Path,
    timeseries_dir: Path,
    out_dir: Path,
    root: Path | None = None,
    capabilities: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if profile != "north_america":
        raise ValueError(
            "Only the north_america semantic profile is currently supported"
        )
    # ``None`` preserves the pre-Phase-21 graph (flexibility assumed) so
    # existing study invocations stay value-identical (R7); an explicit set is
    # the model-first declared-capability contract.
    capabilities = {"flexibility"} if capabilities is None else set(capabilities)
    base_dir = base_dir.resolve()
    scenario_dir = scenario_dir.resolve()
    flexibility_dir = flexibility_dir.resolve()
    timeseries_dir = timeseries_dir.resolve()
    out_dir = out_dir.resolve()

    network_repository = NetworkModelRepository.from_parquet(base_dir)
    validation = network_repository.validate_integrity()
    if not validation.valid:
        raise RuntimeError(
            "Base digital twin network validation failed: "
            + "; ".join(validation.errors[:5])
        )
    network_model = network_repository.load_model()
    asset_registry = pd.read_parquet(scenario_dir / "asset_registry.parquet")
    provider_registry_path = flexibility_dir / "provider_registry.parquet"
    provider_registry = (
        pd.read_parquet(provider_registry_path)
        if provider_registry_path.exists()
        else pd.DataFrame()
    )
    timeseries_manifests = {
        "powerflow_summary": _load_json_or_empty(
            timeseries_dir / "powerflow_smoke_summary.json"
        ),
        "ev_load_summary": _load_json_or_empty(timeseries_dir / "ev_load_summary.json"),
    }

    nodes, edges, manifest = build_semantic_graph(
        buses=network_model.buses,
        lines=network_model.lines,
        transformers=network_model.transformers,
        buildings=network_model.buildings,
        connectivity=network_model.connectivity,
        asset_registry=asset_registry,
        provider_registry=provider_registry,
        timeseries_manifests=timeseries_manifests,
        capabilities=capabilities,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    nodes.to_parquet(out_dir / "nodes.parquet", index=False)
    edges.to_parquet(out_dir / "edges.parquet", index=False)
    write_profile(out_dir / "profile_north_america.json", capabilities=capabilities)
    workspace_root = _resolve_root(root, out_dir)
    manifest["artifacts"] = {
        "nodes": _relpath(out_dir / "nodes.parquet", workspace_root),
        "edges": _relpath(out_dir / "edges.parquet", workspace_root),
        "profile": _relpath(out_dir / "profile_north_america.json", workspace_root),
        "validation_report": _relpath(
            out_dir / "validation_report.json", workspace_root
        ),
    }
    # Regression pins live at the workflow layer, not in mappings.py (G8).
    expected_counts = {
        "buildings": 3235,
        "buses": 3562,
        "lines": 3398,
        "transformers": 163,
        "scenarios": 5,
    }
    manifest["count_checks"] = {
        key: {
            "expected": expected,
            "actual": manifest["source_counts"].get(key),
            "ok": manifest["source_counts"].get(key) == expected,
        }
        for key, expected in expected_counts.items()
    }
    with (out_dir / "graph_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return nodes, edges, manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate digital-twin semantic graph artifacts."
    )
    parser.add_argument("--profile", default="north_america")
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--flexibility-dir", type=Path, default=DEFAULT_FLEXIBILITY_DIR)
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--semantic-capabilities",
        nargs="*",
        default=None,
        help=(
            "Declared semantic capabilities (e.g. 'flexibility'). Defaults to "
            "flexibility for backwards compatibility (R7); pass an empty list "
            "for a model-first core-only graph."
        ),
    )
    args = parser.parse_args()

    nodes, edges, manifest = generate_semantic_graph(
        profile=args.profile,
        base_dir=args.base_dir,
        scenario_dir=args.scenario_dir,
        flexibility_dir=args.flexibility_dir,
        timeseries_dir=args.timeseries_dir,
        out_dir=args.out_dir,
        root=find_workspace_root(args.root),
        capabilities=(
            set(args.semantic_capabilities)
            if args.semantic_capabilities is not None
            else None
        ),
    )
    print(
        f"Generated semantic graph {manifest['semantic_profile']} "
        f"with {len(nodes)} nodes and {len(edges)} edges at {args.out_dir}"
    )


if __name__ == "__main__":
    main()

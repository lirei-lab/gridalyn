"""Generate the federated semantic graph artifacts for the digital twin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.twin.network import NetworkModelRepository
from gridalyn.twin.semantic.mappings import build_semantic_graph, write_profile


DEFAULT_BASE_DIR = ROOT / "instances" / "default" / "digital_twin" / "base"
DEFAULT_SCENARIO_DIR = ROOT / "instances" / "default" / "digital_twin" / "scenarios"
DEFAULT_FLEXIBILITY_DIR = ROOT / "instances" / "default" / "digital_twin" / "flexibility"
DEFAULT_TIMESERIES_DIR = ROOT / "instances" / "default" / "digital_twin" / "timeseries"
DEFAULT_OUT_DIR = ROOT / "instances" / "default" / "digital_twin" / "semantic"


def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def generate_semantic_graph(
    *,
    profile: str,
    base_dir: Path,
    scenario_dir: Path,
    flexibility_dir: Path,
    timeseries_dir: Path,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if profile != "north_america":
        raise ValueError("Only the north_america semantic profile is currently supported")
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
        "powerflow_summary": _load_json_or_empty(timeseries_dir / "powerflow_smoke_summary.json"),
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
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    nodes.to_parquet(out_dir / "nodes.parquet", index=False)
    edges.to_parquet(out_dir / "edges.parquet", index=False)
    write_profile(out_dir / "profile_north_america.json")
    manifest["artifacts"] = {
        "nodes": _relpath(out_dir / "nodes.parquet"),
        "edges": _relpath(out_dir / "edges.parquet"),
        "profile": _relpath(out_dir / "profile_north_america.json"),
        "validation_report": _relpath(out_dir / "validation_report.json"),
    }
    with (out_dir / "graph_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return nodes, edges, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate digital-twin semantic graph artifacts.")
    parser.add_argument("--profile", default="north_america")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--flexibility-dir", type=Path, default=DEFAULT_FLEXIBILITY_DIR)
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    nodes, edges, manifest = generate_semantic_graph(
        profile=args.profile,
        base_dir=args.base_dir,
        scenario_dir=args.scenario_dir,
        flexibility_dir=args.flexibility_dir,
        timeseries_dir=args.timeseries_dir,
        out_dir=args.out_dir,
    )
    print(
        f"Generated semantic graph {manifest['semantic_profile']} "
        f"with {len(nodes)} nodes and {len(edges)} edges at {args.out_dir}"
    )


if __name__ == "__main__":
    main()

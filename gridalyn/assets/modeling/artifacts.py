"""Read and write building model artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.assets.modeling.archetypes import (
    NORTH_AMERICA_RESIDENTIAL_ARCHETYPES,
    NORTH_AMERICA_RESIDENTIAL_PROFILE,
)
from gridalyn.assets.modeling.environment import ModelingEnvironment
from gridalyn.assets.modeling.synthesis import synthesize_building_model_tables
from gridalyn.foundation import ArtifactLayout
from gridalyn.twin.network import NetworkModelRepository

TABLE_FILENAMES = {
    "building_models": "building_models.parquet",
    "thermal_zones": "thermal_zones.parquet",
    "device_registry": "device_registry.parquet",
    "end_use_loads": "end_use_loads.parquet",
}
DEFAULT_ROOT = Path(".")
DEFAULT_LAYOUT = ArtifactLayout(DEFAULT_ROOT)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def load_base_inputs(
    base_dir: Path = DEFAULT_LAYOUT.base,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Load canonical digital-twin building inputs."""

    model = NetworkModelRepository.from_parquet(base_dir).load_model()
    connectivity = None if model.connectivity.empty else model.connectivity
    return model.buildings, connectivity


def write_building_model_artifacts(
    buildings: pd.DataFrame,
    connectivity: pd.DataFrame | None = None,
    *,
    out_dir: Path = DEFAULT_LAYOUT.models,
    root: Path = DEFAULT_ROOT,
    profile: str = NORTH_AMERICA_RESIDENTIAL_PROFILE,
    tables: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Write synthesized model tables plus a portable manifest."""

    out_dir.mkdir(parents=True, exist_ok=True)
    table_data = tables or synthesize_building_model_tables(
        buildings,
        connectivity,
        profile=profile,
    )

    artifacts: dict[str, str] = {}
    counts: dict[str, int] = {}
    for table_name, filename in TABLE_FILENAMES.items():
        if table_name not in table_data:
            raise ValueError(f"Missing synthesized table: {table_name}")
        path = out_dir / filename
        table_data[table_name].to_parquet(path, index=False)
        artifacts[table_name] = _relative(path, root)
        counts[table_name] = int(len(table_data[table_name]))

    device_registry = table_data["device_registry"]
    evse_devices = (
        int((device_registry["device_type"] == "evse_l2").sum())
        if len(device_registry)
        else 0
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "building_model_manifest",
        "schema_version": "1.0",
        "model_profile": profile,
        "source_standard": "pycity-inspired",
        "environment": ModelingEnvironment(model_profile=profile).to_record(),
        "counts": {
            **counts,
            "archetypes": len(NORTH_AMERICA_RESIDENTIAL_ARCHETYPES),
            "evse_devices": evse_devices,
        },
        "inputs": {
            "buildings": "instances/default/digital_twin/base/buildings.parquet",
            "connectivity": (
                "instances/default/digital_twin/base/"
                "building_grid_connectivity.parquet"
            ),
        },
        "artifacts": artifacts,
        "root": ".",
    }

    manifest_path = out_dir / "building_model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    manifest["manifest_path"] = _relative(manifest_path, root)
    return manifest

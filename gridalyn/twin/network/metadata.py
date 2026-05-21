"""Metadata manifest builder for base digital-twin network snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation.platform.governance import build_model_version
from gridalyn.twin.network.repository import NetworkModelRepository


BASE_METADATA_SCHEMA_VERSION = "1.0"
DEFAULT_SOURCE_ADAPTER = "SyntheticPandapowerAdapter"
DEFAULT_SOURCE_STANDARD = "pandapower"
DEFAULT_ADAPTER_ID = "synthetic_pandapower"
DEFAULT_SOURCE_FORMAT = "pandapower-cache"

BASE_ARTIFACTS = {
    "grid_buses": "grid_buses.parquet",
    "grid_lines": "grid_lines.parquet",
    "grid_transformers": "grid_transformers.parquet",
    "buildings": "buildings.parquet",
    "building_grid_connectivity": "building_grid_connectivity.parquet",
}


def build_base_metadata(
    *,
    base_dir: Path,
    root: Path,
    config_path: Path,
    config_hash: str,
    cache_dir: Path,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    source_adapter: str = DEFAULT_SOURCE_ADAPTER,
    source_standard: str = DEFAULT_SOURCE_STANDARD,
    source_format: str = DEFAULT_SOURCE_FORMAT,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    adapter_validation_report: Path | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Build a repository-centric manifest for a base digital-twin snapshot."""
    repo = NetworkModelRepository.from_parquet(base_dir)
    model = repo.load_model()
    validation = repo.validate_integrity()
    artifact_metadata = _artifact_metadata(
        base_dir=base_dir,
        root=root,
        frames={
            "grid_buses": model.buses,
            "grid_lines": model.lines,
            "grid_transformers": model.transformers,
            "buildings": model.buildings,
            "building_grid_connectivity": model.connectivity,
        },
    )
    validation_payload = {
        "valid": bool(validation.valid),
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "summary": validation.summary,
    }
    model_version = build_model_version(
        source_system=adapter_id,
        source_adapter=source_adapter,
        source_standard=source_standard,
        source_format=source_format,
        artifact_metadata=artifact_metadata,
        counts=model.counts,
        validation=validation_payload,
        lineage={
            "config_hash": config_hash,
            "config_path": _relpath(config_path, root),
            "cache_dir": _relpath(cache_dir, root),
            "base_dir": _relpath(base_dir, root),
        },
    )

    metadata = {
        "report_id": "digital_twin_base_metadata",
        "schema_version": BASE_METADATA_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_version_id": model_version.id,
        "model_version": model_version.to_dict(),
        "adapter_id": adapter_id,
        "source_adapter": source_adapter,
        "source_standard": source_standard,
        "source_format": source_format,
        "adapter_capabilities": list(adapter_capabilities or []),
        "source_tables": list(BASE_ARTIFACTS.keys()),
        "config_path": _relpath(config_path, root),
        "config_hash": config_hash,
        "cache_dir": _relpath(cache_dir, root),
        "base_dir": _relpath(base_dir, root),
        "counts": model.counts,
        "artifacts": artifact_metadata,
        "validation": validation_payload,
        "notes": notes or [],
    }
    if adapter_validation_report is not None:
        metadata["adapter_validation_report"] = _relpath(adapter_validation_report, root)
    return metadata


def write_base_metadata(
    *,
    base_dir: Path,
    root: Path,
    config_path: Path,
    config_hash: str,
    cache_dir: Path,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    source_adapter: str = DEFAULT_SOURCE_ADAPTER,
    source_standard: str = DEFAULT_SOURCE_STANDARD,
    source_format: str = DEFAULT_SOURCE_FORMAT,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    adapter_validation_report: Path | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Write `metadata.json` for a base digital-twin snapshot."""
    metadata = build_base_metadata(
        base_dir=base_dir,
        root=root,
        config_path=config_path,
        config_hash=config_hash,
        cache_dir=cache_dir,
        adapter_id=adapter_id,
        source_adapter=source_adapter,
        source_standard=source_standard,
        source_format=source_format,
        adapter_capabilities=adapter_capabilities,
        adapter_validation_report=adapter_validation_report,
        notes=notes,
    )
    path = base_dir / "metadata.json"
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    return path


def _artifact_metadata(
    *,
    base_dir: Path,
    root: Path,
    frames: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact_name, filename in BASE_ARTIFACTS.items():
        path = base_dir / filename
        frame = frames.get(artifact_name, pd.DataFrame())
        artifacts[artifact_name] = {
            "path": _relpath(path, root),
            "row_count": int(len(frame)),
            "sha256": _file_sha256(path) if path.exists() else None,
        }
    return artifacts


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)

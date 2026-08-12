"""Metadata manifest builder for base digital-twin network snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation.platform.governance import build_model_version
from gridalyn.twin.network.model import BASE_TABLE_FILENAMES
from gridalyn.twin.network.repository import NetworkModelRepository

BASE_METADATA_SCHEMA_VERSION = "1.0"
DEFAULT_SOURCE_ADAPTER = "SyntheticPandapowerAdapter"
DEFAULT_SOURCE_STANDARD = "pandapower"
DEFAULT_ADAPTER_ID = "synthetic_pandapower"
DEFAULT_SOURCE_FORMAT = "pandapower-cache"

# The canonical artifact list has one definition, in the model module; this
# name is the manifest-side view of it.
BASE_ARTIFACTS: dict[str, str] = dict(BASE_TABLE_FILENAMES)


def build_base_metadata(
    *,
    base_dir: Path,
    root: Path,
    config_path: Path,
    config_hash: str,
    cache_dir: Path | None = None,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    source_adapter: str = DEFAULT_SOURCE_ADAPTER,
    source_standard: str = DEFAULT_SOURCE_STANDARD,
    source_format: str = DEFAULT_SOURCE_FORMAT,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    adapter_validation_report: Path | None = None,
    notes: list[str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a repository-centric manifest for a base digital-twin snapshot.

    Args:
        base_dir: Directory holding the canonical base Parquet artifacts.
        root: Workspace root that declared paths are recorded relative to.
        config_path: Grid configuration the snapshot declares as its input.
        config_hash: Digest of that configuration's contents.
        cache_dir: Source cache the snapshot was built from, or ``None`` when
            it is not recoverable. Recorded as ``null`` rather than invented.
        adapter_id: Stable identifier of the producing source adapter.
        source_adapter: Class name of the producing source adapter.
        source_standard: Source data standard, e.g. ``"pandapower"``.
        source_format: Source serialization format.
        adapter_capabilities: Capabilities the producing adapter declares.
        adapter_validation_report: Path of the adapter validation report.
        notes: Free-text provenance notes recorded verbatim.
        created_at: ISO-8601 UTC timestamp to stamp instead of "now". Pin it to
            make regeneration byte-deterministic; leaving it ``None`` stamps the
            current time, which changes on every regeneration by design.

    Returns:
        The manifest payload, ready to serialize to ``metadata.json``.
    """
    # This function *produces* the provenance manifest, so it must load the
    # model before that manifest exists: "ignore" is the only honest policy here.
    repo = NetworkModelRepository.from_parquet(base_dir, provenance="ignore")
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
    stamped_at = created_at or datetime.now(timezone.utc).isoformat()
    model_version = build_model_version(
        created_at=stamped_at,
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
            "cache_dir": _relpath_or_none(cache_dir, root),
            "base_dir": _relpath(base_dir, root),
        },
    )

    metadata = {
        "report_id": "digital_twin_base_metadata",
        "schema_version": BASE_METADATA_SCHEMA_VERSION,
        "created_at": stamped_at,
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
        "cache_dir": _relpath_or_none(cache_dir, root),
        "base_dir": _relpath(base_dir, root),
        "counts": model.counts,
        "artifacts": artifact_metadata,
        "validation": validation_payload,
        "notes": notes or [],
    }
    if adapter_validation_report is not None:
        metadata["adapter_validation_report"] = _relpath(
            adapter_validation_report, root
        )
    return metadata


def write_base_metadata(
    *,
    base_dir: Path,
    root: Path,
    config_path: Path,
    config_hash: str,
    cache_dir: Path | None = None,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    source_adapter: str = DEFAULT_SOURCE_ADAPTER,
    source_standard: str = DEFAULT_SOURCE_STANDARD,
    source_format: str = DEFAULT_SOURCE_FORMAT,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    adapter_validation_report: Path | None = None,
    notes: list[str] | None = None,
    created_at: str | None = None,
) -> Path:
    """Write `metadata.json` for a base digital-twin snapshot.

    Args:
        base_dir: Directory holding the canonical base Parquet artifacts.
        root: Workspace root that declared paths are recorded relative to.
        config_path: Grid configuration the snapshot declares as its input.
        config_hash: Digest of that configuration's contents.
        cache_dir: Source cache, or ``None`` when it is not recoverable.
        adapter_id: Stable identifier of the producing source adapter.
        source_adapter: Class name of the producing source adapter.
        source_standard: Source data standard, e.g. ``"pandapower"``.
        source_format: Source serialization format.
        adapter_capabilities: Capabilities the producing adapter declares.
        adapter_validation_report: Path of the adapter validation report.
        notes: Free-text provenance notes recorded verbatim.
        created_at: ISO-8601 UTC timestamp to stamp instead of "now".

    Returns:
        The path of the written ``metadata.json``.
    """
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
        created_at=created_at,
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


def _relpath_or_none(path: Path | None, root: Path) -> str | None:
    return None if path is None else _relpath(path, root)

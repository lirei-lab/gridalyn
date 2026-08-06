"""Validation reports for network source adapter exports.

:func:`build_network_adapter_validation_report` keeps its historical flat
shape for in-memory consumers; the serialized report routes through the
platform report contract (:func:`gridalyn.foundation.write_report`, audit
§5.4, 2026-08-06), with the flat report's ``source_adapter``,
``source_standard``, ``adapter`` and ``lineage`` folded into ``summary``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.twin.network import NetworkModelRepository

NETWORK_ADAPTER_VALIDATION_SCHEMA_VERSION = "1.0"


def build_network_adapter_validation_report(
    *,
    base_dir: Path,
    root: Path,
    adapter_id: str | None = None,
    source_adapter: str,
    source_standard: str,
    source_format: str | None = None,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    artifact_paths: dict[str, Path],
    metadata_path: Path,
) -> dict[str, Any]:
    """Build a standard validation report for an exported network snapshot."""
    repository = NetworkModelRepository.from_parquet(base_dir)
    model = repository.load_model()
    validation = repository.validate_integrity()
    return {
        "report_id": "network_adapter_validation",
        "schema_version": NETWORK_ADAPTER_VALIDATION_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_adapter": source_adapter,
        "source_standard": source_standard,
        "adapter": {
            "adapter_id": adapter_id or _adapter_id_from_name(source_adapter),
            "adapter_name": source_adapter,
            "source_standard": source_standard,
            "source_format": source_format
            or _default_source_format_for(source_adapter, source_standard),
            "capabilities": list(
                adapter_capabilities or _default_capabilities_for(source_adapter)
            ),
        },
        "summary": {
            "counts": model.counts,
            "artifact_count": len(artifact_paths),
        },
        "validation": {
            "valid": bool(validation.valid),
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "summary": validation.summary,
        },
        "lineage": {
            "base_dir": _relpath(base_dir, root),
            "metadata_path": _relpath(metadata_path, root),
        },
        "artifacts": {
            name: {
                "path": _relpath(path, root),
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else None,
            }
            for name, path in sorted(artifact_paths.items())
        },
    }


def write_network_adapter_validation_report(
    *,
    path: Path,
    base_dir: Path,
    root: Path,
    adapter_id: str | None = None,
    source_adapter: str,
    source_standard: str,
    source_format: str | None = None,
    adapter_capabilities: tuple[str, ...] | list[str] | None = None,
    artifact_paths: dict[str, Path],
    metadata_path: Path,
) -> Path:
    """Write a governed validation report for an exported network snapshot."""
    report = build_network_adapter_validation_report(
        base_dir=base_dir,
        root=root,
        adapter_id=adapter_id,
        source_adapter=source_adapter,
        source_standard=source_standard,
        source_format=source_format,
        adapter_capabilities=adapter_capabilities,
        artifact_paths=artifact_paths,
        metadata_path=metadata_path,
    )
    # The exported base tables are both what the integrity validation read
    # (inputs) and what the adapter export wrote (artifacts).
    table_references = [
        file_reference(table_path, root)
        for _, table_path in sorted(artifact_paths.items())
    ]
    write_report(
        path,
        metadata=ReportMetadata(
            report_id="network_adapter_validation",
            source_domain="twin",
        ),
        inputs=table_references,
        artifacts=table_references,
        summary={
            **report["summary"],
            "source_adapter": report["source_adapter"],
            "source_standard": report["source_standard"],
            "adapter": report["adapter"],
            "lineage": report["lineage"],
        },
        validation=report["validation"],
    )
    return path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _adapter_id_from_name(adapter_name: str) -> str:
    name = adapter_name
    if name.endswith("Adapter"):
        name = name[: -len("Adapter")]
    chars: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0 and not name[index - 1].isupper():
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars).strip("_")


def _default_capabilities_for(source_adapter: str) -> tuple[str, ...]:
    if source_adapter == "SyntheticPandapowerAdapter":
        return (
            "load_snapshot",
            "export_base_parquet",
            "write_base_metadata",
            "write_validation_report",
        )
    return ("export_base_parquet", "write_validation_report")


def _default_source_format_for(source_adapter: str, source_standard: str) -> str:
    if source_adapter == "SyntheticPandapowerAdapter":
        return "pandapower-cache"
    return source_standard

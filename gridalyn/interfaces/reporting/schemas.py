"""Shared helpers for canonical report JSON artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.reports import (
    ReportMetadata,
    build_report,
    file_reference,
    validate_report,
    write_json_report,
)

SCHEMA_VERSION = "1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def relpath(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_input(path: Path, *, root: Path) -> dict[str, Any]:
    path = path.resolve()
    return {
        "path": relpath(path, root),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def canonical_report(
    *,
    report_id: str,
    title: str,
    root: Path,
    inputs: list[Path],
    metrics: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
    stage: str | None = None,
    source_domain: str = "gridalyn",
    project_name: str = "gridalyn",
) -> dict[str, Any]:
    return build_report(
        metadata=ReportMetadata(
            report_id=report_id,
            source_domain=source_domain,
            project={
                "name": project_name,
                "title": title,
                "stage": stage,
            },
        ),
        inputs=[file_reference(path, root=root) for path in inputs if path.exists()],
        artifacts=artifact_references(artifacts or {}, root=root),
        summary=metrics,
        validation={"valid": True, "errors": [], "warnings": []},
    )


def artifact_references(
    artifacts: dict[str, Any], *, root: Path
) -> list[dict[str, Any]]:
    """Normalize named artifacts to the public platform report contract."""
    items: list[dict[str, Any]] = []
    for name, value in artifacts.items():
        if value is None:
            continue
        item: dict[str, Any] = {"name": name}
        if isinstance(value, str):
            item["path"] = value
            candidate = (root / value).resolve()
            if candidate.exists():
                if candidate.is_file():
                    item.update(file_reference(candidate, root=root))
                elif candidate.is_dir():
                    item["exists"] = True
                    item["type"] = "directory"
            else:
                item["exists"] = False
        else:
            item["value"] = value
        items.append(item)
    return items


def write_report(path: Path, report: dict[str, Any], *, root: Path) -> str:
    """Validate and write a canonical report, returning its root-relative path.

    Args:
        path: Destination file for the canonical report JSON.
        report: Report payload; must satisfy the platform report contract.
        root: Workspace root used to relativize the returned path.

    Returns:
        The written report's path relative to ``root``.

    Raises:
        ValueError: If ``report`` fails :func:`validate_report`; the message
            names the destination file, the contract errors, and the fix.
    """
    errors = validate_report(report)
    if errors:
        raise ValueError(
            f"{path}: canonical report violates the platform report contract "
            f"({'; '.join(errors)}). Build the payload with "
            "gridalyn.interfaces.reporting.schemas.canonical_report — which "
            "routes through build_report — instead of hand-assembling the dict."
        )
    write_json_report(path, report)
    return relpath(path, root)

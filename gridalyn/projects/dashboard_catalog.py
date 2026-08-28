"""Build a generic dashboard catalog for the digital-twin grid viewer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from gridalyn.projects.project_catalog import build_project_catalog
from gridalyn.twin.network import (
    BASE_TABLE_FILENAMES,
    NetworkModelRepository,
    resolve_network_geography,
)

FILE_KINDS = {
    "nodes": "powerflow_nodes",
    "lines": "powerflow_lines",
    "power": "powerflow_power",
    "transformers": "powerflow_transformers",
}

_TWIN_PREFIX = "digital_twin/"


def _instance_root() -> str:
    """Workspace-relative root of the selected digital-twin instance.

    The twin CLI threads the selected instance via ``GRIDALYN_INSTANCE``, so
    the catalog generated for *any* named instance re-anchors its declared
    paths onto that instance rather than always onto ``instances/default``.
    """
    instance = os.environ.get("GRIDALYN_INSTANCE", "default")
    return f"instances/{instance}"


def _anchor(declared: str) -> str:
    """Re-anchor an instance-relative declared path onto the workspace root.

    Args:
        declared: Path recorded in a powerflow summary, in either the current
            workspace-relative form or the pre-unification instance-relative
            form.

    Returns:
        The workspace-relative equivalent. Absolute paths and paths already
        anchored under ``instances/`` are returned unchanged.
    """
    text = str(declared).replace("\\", "/")
    if text.startswith(_TWIN_PREFIX):
        return f"{_instance_root()}/{text}"
    return text


def _web_path(path: Path | str, root: Path) -> str:
    raw = Path(path)
    try:
        rel = raw.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        rel = raw
    return "/" + str(rel).replace("\\", "/").lstrip("/")


def _scenario_by_id(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {
        str(item["scenario_id"]): item
        for item in (items or [])
        if item.get("scenario_id")
    }


def _paths(scenario_id: str, summary: dict[str, Any], root: Path) -> dict[str, str]:
    declared = summary.get("paths") or {}
    paths = {}
    for kind, suffix in FILE_KINDS.items():
        fallback = (
            f"{_instance_root()}/{_TWIN_PREFIX}timeseries/"
            f"{scenario_id}_{suffix}.parquet"
        )
        paths[kind] = _web_path(_anchor(declared.get(kind) or fallback), root)
    return paths


def _metrics(summary: dict[str, Any]) -> dict[str, float | int | None]:
    return {
        "grid_peak_mw": summary.get("ext_grid_peak_mw"),
        "load_peak_mw": summary.get("load_peak_mw"),
        "v_min_pu": summary.get("v_min_pu"),
        "v_mean_pu": summary.get("v_mean_pu"),
        "line_max_loading_percent": summary.get("line_max_loading_percent"),
        "trafo_max_loading_percent": summary.get("trafo_max_loading_percent"),
        "n_line_overloads": summary.get("n_line_overloads"),
        "n_trafo_overloads": summary.get("n_trafo_overloads"),
    }


def _topology_counts(
    summary: dict[str, Any],
    network_counts: dict[str, int] | None = None,
) -> dict[str, int | None]:
    counts = network_counts or {}
    return {
        "n_buses": summary.get("n_buses", counts.get("buses")),
        "n_lines": summary.get("n_lines", counts.get("lines")),
        "n_loads": summary.get("n_loads", counts.get("loads")),
        "n_transformers": summary.get("n_transformers", counts.get("transformers")),
        "n_timestamps": summary.get("n_timestamps"),
    }


def build_dashboard_catalog(
    *,
    scenario_index: dict[str, Any],
    powerflow_summary: dict[str, Any],
    optional_extensions: dict[str, Path] | None,
    root: Path,
    network_repository: NetworkModelRepository | None = None,
    projects: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Build a study-agnostic scenario catalog for the dashboard.

    Args:
        scenario_index: Parsed scenario index.
        powerflow_summary: Parsed powerflow summary.
        optional_extensions: Onward catalogs to link, by key.
        root: Workspace root that served paths are expressed relative to.
        network_repository: Base snapshot to describe, or ``None``.
        projects: Loaded ``StudyProject`` objects whose declared result
            artifacts should be catalogued. ``None`` records an empty list.
            Studies are described, not embedded: the dashboard reads a
            project's artifacts as a *source*, which is why this belongs here
            -- the catalog is written by the ``projects`` layer, which may
            legitimately see both a twin and a study.

    Returns:
        The catalog payload.
    """
    scenario_items = _scenario_by_id(scenario_index.get("scenarios"))
    summary_items = _scenario_by_id(powerflow_summary.get("scenarios"))
    scenario_ids = sorted(set(scenario_items) | set(summary_items))
    network_model: dict[str, Any] = {}
    network_counts: dict[str, int] | None = None
    if network_repository is not None:
        model = network_repository.load_model()
        integrity = network_repository.validate_integrity()
        metadata = _load_network_metadata(network_repository.base_dir)
        network_counts = model.counts
        identity = model.identity
        network_model = {
            "counts": network_counts,
            # Sourced from the identity layer (Phase 12); None when the model
            # carries no manifest, matching what the raw-metadata read rendered.
            "model_version_id": identity.id if identity is not None else None,
            "model_version": metadata.get("model_version", {}),
            "validation": {
                "valid": integrity.valid,
                "errors": list(integrity.errors),
                "warnings": list(integrity.warnings),
            },
            "geography": _geography(network_repository, metadata, root),
        }
    extensions = {
        key: _web_path(path, root)
        for key, path in (optional_extensions or {}).items()
        if Path(path).exists()
    }

    scenarios = []
    for scenario_id in scenario_ids:
        scenario = scenario_items.get(scenario_id, {})
        summary = summary_items.get(scenario_id, {})
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "label": scenario.get("label") or summary.get("label") or scenario_id,
                "description": scenario.get("description")
                or summary.get("description")
                or "",
                "paths": _paths(scenario_id, summary, root),
                "metrics": _metrics(summary),
                "topology_counts": _topology_counts(summary, network_counts),
                "extensions": extensions,
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "digital_twin_dashboard_catalog",
        # 1.1 adds network_model.geography: the CRS, the extent, the base
        # artifact paths, and which geometries are derived from bus endpoints.
        # 1.2 adds projects: each study's declared result artifacts, classified
        # so a viewer renders them from the report contract instead of from
        # per-study code. Both additive -- every 1.0 key keeps its name, shape
        # and meaning, so a reader written against 1.0 is unaffected.
        "schema_version": "1.2",
        "title": "Gridalyn Digital Twin",
        "network_model": network_model,
        "projects": build_project_catalog(projects or (), root=root),
        "scenarios": scenarios,
    }


def _geography(
    repository: NetworkModelRepository,
    metadata: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    """Publish where the snapshot sits and which artifacts carry its geometry.

    The catalog previously named only the per-scenario timeseries artifacts, so
    a consumer could reach a scenario's voltages but not the base tables that
    say where any of it is. That made a geo-centred view impossible to drive
    from the catalog: the only route to the network's geography was to hardcode
    the base paths, which is exactly what a catalog exists to prevent.

    Args:
        repository: Loaded base-snapshot repository.
        metadata: Parsed base ``metadata.json``, consulted for a declared CRS.
        root: Workspace root that published paths are served relative to.

    Returns:
        The resolved geography payload, extended with a ``paths`` block naming
        every canonical base artifact that exists on disk.
    """
    model = repository.load_model()
    geography = resolve_network_geography(
        frames={
            "grid_buses": model.buses,
            "grid_lines": model.lines,
            "grid_transformers": model.transformers,
            "buildings": model.buildings,
            "building_grid_connectivity": model.connectivity,
        },
        metadata=metadata,
    )
    payload = geography.to_dict()
    payload["paths"] = {
        artifact: _web_path(repository.base_dir / filename, root)
        for artifact, filename in BASE_TABLE_FILENAMES.items()
        if (repository.base_dir / filename).exists()
    }
    return payload


def _load_network_metadata(base_dir: Path) -> dict[str, Any]:
    path = base_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_dashboard_catalog(path: Path, catalog: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True))
    return path

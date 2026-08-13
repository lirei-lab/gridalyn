"""Build a generic dashboard catalog for the digital-twin grid viewer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.twin.network import NetworkModelRepository

FILE_KINDS = {
    "nodes": "powerflow_nodes",
    "lines": "powerflow_lines",
    "power": "powerflow_power",
    "transformers": "powerflow_transformers",
}

#: Workspace-relative root of the default digital-twin instance. Summaries
#: written before the 2026-05-19 instance-path unification declared their
#: parquet locations relative to the *instance* (``digital_twin/...``) rather
#: than to the workspace, so paths in that older form need re-anchoring here.
_INSTANCE_ROOT = "instances/default"
_TWIN_PREFIX = "digital_twin/"


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
        return f"{_INSTANCE_ROOT}/{text}"
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
            f"{_INSTANCE_ROOT}/{_TWIN_PREFIX}timeseries/"
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
) -> dict[str, Any]:
    """Build a study-agnostic scenario catalog for the dashboard."""
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
        "schema_version": "1.0",
        "title": "Gridalyn Digital Twin",
        "network_model": network_model,
        "scenarios": scenarios,
    }


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

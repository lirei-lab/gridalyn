"""Build a generic dashboard catalog for the digital-twin grid viewer."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from gridalyn.projects.project_catalog import build_project_catalog
from gridalyn.projects.scenario_catalog import BY_FILE as PARTITION_BY_FILE
from gridalyn.twin.network import (
    BASE_TABLE_FILENAMES,
    NetworkModelRepository,
    resolve_network_geography,
)
from gridalyn.twin.observation.publication import (
    PROVENANCE_SIMULATED,
    resolve_observation_publication,
)
from gridalyn.twin.semantic.publication import (
    GRAPH_CLASS_COLUMN,
    GRAPH_SOURCE_COLUMN,
    read_graph_manifest,
    resolve_semantic_publication,
    semantic_artifact_filenames,
)

FILE_KINDS = {
    "nodes": "powerflow_nodes",
    "lines": "powerflow_lines",
    "power": "powerflow_power",
    "transformers": "powerflow_transformers",
}
"""The twin's per-scenario artifact kinds, and the file suffix each is written
under. The twin partitions BY FILE -- one artifact per (scenario, kind) -- so
the scenario id is in the path.

This mapping stays here, in the producer, and is now PUBLISHED with every
scenario rather than being re-declared by each consumer. It was written out
three times: here, in ``dashboard/src/scenarios.js`` and in
``dashboard/src/useDuckDB.js``, with nothing keeping the three in sync, and the
client additionally synthesized the ``timeseries/{id}_{suffix}.parquet`` layout
for itself. A consumer that assumes this set cannot read a study's scenarios,
which are partitioned the other way."""

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
    semantic_dir: Path | None = None,
    scenario_assets: Path | None = None,
    observations_dir: Path | None = None,
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
        semantic_dir: Directory holding the materialized semantic graph, or
            ``None``. ``None`` publishes no ``semantic`` block at all, which
            is the honest rendering for a twin that has none -- an empty block
            would claim the ontology was looked for and found empty.
        scenario_assets: Path to the scenario asset registry, or ``None``.
            Contributes the one class population that varies *within* an
            artifact, which is what a map can encode as a dimension.
        observations_dir: Where this instance's MEASURED observations are read
            from. Unlike ``semantic_dir``, the resulting block is published
            whether or not anything is there: "is anything here measured?" is a
            question every consumer must be able to ask of every instance, and
            omitting the key would make "no measured data" and "this catalog is
            too old to say" the same observation. ``None`` still publishes the
            block, naming no directory.

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
                # How each kind must be READ, published so a consumer never
                # infers it. The twin is file-partitioned: each path holds this
                # scenario alone. A study may be column-partitioned, where one
                # path holds every scenario and a column selects.
                "partitioning": {
                    kind: {
                        "kind": kind,
                        "partitioning": PARTITION_BY_FILE,
                        "id_column": None,
                    }
                    for kind in FILE_KINDS
                },
                # Where a scenario's numbers came from. Always "simulated":
                # these artifacts are written by a solved power flow, and a
                # value from a solver and a value from a meter must not reach
                # a view looking identical.
                "provenance": PROVENANCE_SIMULATED,
                "metrics": _metrics(summary),
                "topology_counts": _topology_counts(summary, network_counts),
                "extensions": extensions,
            }
        )

    catalog: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "digital_twin_dashboard_catalog",
        # 1.1 adds network_model.geography: the CRS, the extent, the base
        # artifact paths, and which geometries are derived from bus endpoints.
        # 1.2 adds projects: each study's declared result artifacts, classified
        # so a viewer renders them from the report contract instead of from
        # per-study code. Both additive -- every 1.0 key keeps its name, shape
        # and meaning, so a reader written against 1.0 is unaffected.
        # 1.3 adds semantic: the active profile, the graph's counts and
        # validation verdict, the semantic artifact paths, and the ontology
        # CLASSES with a count each -- the classes being what a client can
        # build a layer or a filter from, which a node count cannot. Additive
        # like the two before it.
        # 1.4 adds observation, and `provenance` on every scenario: whether
        # this instance carries MEASURED state, where it would be read from,
        # and what each rendered artifact's values actually are. Also additive.
        "schema_version": "1.4",
        "title": "Gridalyn Digital Twin",
        "network_model": network_model,
        "projects": build_project_catalog(projects or (), root=root),
        "scenarios": scenarios,
    }
    semantic = _semantic(
        semantic_dir=semantic_dir,
        scenario_assets=scenario_assets,
        network_repository=network_repository,
        root=root,
    )
    if semantic is not None:
        catalog["semantic"] = semantic
    catalog["observation"] = _observation(observations_dir, root)
    return catalog


def _observation(observations_dir: Path | None, root: Path) -> dict[str, Any]:
    """State whether this instance carries measured state, and where it lives.

    Always returns a payload. An instance with no measured observations is the
    normal case -- every instance this repository ships -- and it says so with
    a reason and with the directory it looked in, rather than by being silent.

    Args:
        observations_dir: Where measured observations are read from, or
            ``None`` when the caller names no location.
        root: Workspace root that published paths are served relative to.

    Returns:
        The observation payload, extended with the served directory when one
        was named.
    """
    publication = resolve_observation_publication(observations_dir or Path("."))
    payload = publication.to_dict()
    if observations_dir is None:
        # No directory named, so none is published: a path the caller never
        # gave would be this function's invention, not the twin's statement.
        payload["measured"]["directory"] = None
        return payload
    payload["measured"]["directory"] = _web_path(observations_dir, root)
    payload["measured"]["sources"] = [
        _web_path(path, root) for path in publication.measured_sources
    ]
    payload["measured"]["entity_join"] = (
        _web_path(publication.entity_join, root)
        if publication.entity_join is not None
        else None
    )
    return payload


def _read_frame(path: Path, columns: list[str] | None = None) -> Any:
    """Read a parquet artifact, or return ``None`` when it is unreadable.

    A twin whose semantic tables are absent, truncated or written by a
    different emitter must not take the whole catalog down with it: the
    scenarios and the geography are unrelated to the ontology. The failure is
    reported on stderr rather than swallowed, matching how the generator
    reports a study it had to skip.

    Args:
        path: Artifact to read.
        columns: Columns to project, or ``None`` for all. Projecting is what
            keeps the multi-megabyte node table from being materialized in
            full for a class tally.

    Returns:
        The loaded frame, or ``None``.
    """
    if not path.exists():
        return None
    import pandas as pd

    try:
        return pd.read_parquet(path, columns=columns)
    except (OSError, ValueError) as error:  # unreadable or wrong columns
        print(f"warning: skipping {path}: {error}", file=sys.stderr, flush=True)
        return None


def _semantic(
    *,
    semantic_dir: Path | None,
    scenario_assets: Path | None,
    network_repository: NetworkModelRepository | None,
    root: Path,
) -> dict[str, Any] | None:
    """Publish the twin's ontology, or ``None`` when it declares none.

    The dashboard reached the ontology through a hardcoded path to
    ``semantic/graph_manifest.json`` and rendered four scalars from it --
    profile, valid, node count, edge count. That is an ontology reduced to a
    node count: nothing a client can colour, filter or group by, and a path
    the catalog was supposed to have eliminated.

    Args:
        semantic_dir: Directory holding the materialized graph, or ``None``.
        scenario_assets: Scenario asset registry path, or ``None``.
        network_repository: Base snapshot whose tables carry the third class
            population, or ``None``.
        root: Workspace root that published paths are served relative to.

    Returns:
        The semantic payload, or ``None`` when neither a semantic directory
        nor a scenario asset registry exists -- a twin with no ontology says
        so by carrying no block, rather than by carrying an empty one.
    """
    graph_dir = semantic_dir if semantic_dir and semantic_dir.exists() else None
    registry = scenario_assets if scenario_assets and scenario_assets.exists() else None
    if graph_dir is None and registry is None:
        return None

    manifest: dict[str, Any] = {}
    nodes = None
    if graph_dir is not None:
        manifest = read_graph_manifest(graph_dir)
        nodes = _read_frame(
            graph_dir / "nodes.parquet",
            columns=[GRAPH_CLASS_COLUMN, GRAPH_SOURCE_COLUMN],
        )
    assets = _read_frame(registry) if registry is not None else None
    base_frames: dict[str, Any] = {}
    if network_repository is not None:
        model = network_repository.load_model()
        base_frames = {
            "grid_buses": model.buses,
            "grid_lines": model.lines,
            "grid_transformers": model.transformers,
            "buildings": model.buildings,
            "building_grid_connectivity": model.connectivity,
        }

    publication = resolve_semantic_publication(
        manifest=manifest,
        base_frames=base_frames,
        graph_nodes=nodes,
        scenario_assets=assets,
    )
    payload = publication.to_dict()
    # Every artifact a class was read from is reachable: the semantic
    # documents and the asset registry are named here, and the base-population
    # artifacts are named in `network_model.geography.paths` under the SAME
    # canonical keys, so a consumer resolves `classes[].artifact` against the
    # union of the two without a special case.
    paths: dict[str, str] = {}
    if graph_dir is not None:
        for name, filename in semantic_artifact_filenames(publication.profile).items():
            candidate = graph_dir / filename
            if candidate.exists():
                paths[name] = _web_path(candidate, root)
    if registry is not None:
        paths["asset_registry"] = _web_path(registry, root)
    payload["paths"] = paths
    return payload


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

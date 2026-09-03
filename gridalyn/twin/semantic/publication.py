"""What a consumer needs in order to *read* the twin's ontology.

The twin has carried a full semantic layer since Phase 9 -- a profile, a
materialized node/edge graph, a validation verdict -- and every base table
carries a declared class column. None of it reached a consumer. The dashboard
read four scalars (profile, valid, node count, edge count) off
``semantic/graph_manifest.json`` by hardcoded path, which is an ontology
reduced to a node count: nothing a client could colour, filter or group by.

This module resolves the ontology into the shape a consumer can act on, the
way :mod:`gridalyn.twin.network.geography` did for the snapshot's geography.

**The classes come from three populations, and they do not coincide.**
Measured against ``instances/default`` on 2026-09-02:

===================  =======  ==========================================
Population           Classes  What it is
===================  =======  ==========================================
``base_snapshot``          4  The declared class column of each base
                              table -- one class per artifact, constant
                              within it (``ConnectivityNode``,
                              ``ACLineSegment``, ``PowerTransformer``,
                              ``Building``). Bare names, no prefix.
``semantic_graph``        21  ``nodes.parquet``'s ``semantic_type`` --
                              the profile's CURIE vocabulary
                              (``brick:Building``, ``cim:EnergyConsumer``
                              ...). A building is *four* nodes here.
``scenario_assets``        2  The scenario asset registry's class per
                              (scenario, entity): ``Building`` vs
                              ``EVChargingAsset``. The only population
                              that varies *within* an artifact.
===================  =======  ==========================================

Publishing one of them and calling it "the ontology classes" would leave the
consumer to discover the other two by reading files. Every class therefore
carries the population it came from, the artifact and column it was read off,
and whether that artifact's rows carry coordinates -- so a client can ask for
"the classes I can draw" without knowing any of this by heart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from gridalyn.twin.network.schema import (
    BASE_TABLE_SCHEMAS,
    ROLE_IDENTITY,
    ROLE_LATITUDE,
    ROLE_LONGITUDE,
    ROLE_ONTOLOGY_CLASS,
    table_schema,
)

#: Class read off a base table's declared ontology-class column.
POPULATION_BASE = "base_snapshot"

#: Class read off the materialized semantic graph's ``semantic_type``.
POPULATION_GRAPH = "semantic_graph"

#: Class read off the scenario asset registry, scoped to one scenario.
POPULATION_SCENARIO = "scenario_assets"

#: Column the semantic graph's node table names its class in.
GRAPH_CLASS_COLUMN = "semantic_type"

#: Column the semantic graph's node table names its originating table in.
GRAPH_SOURCE_COLUMN = "source_table"

#: Column the scenario asset registry names its class in. One spelling: both
#: producers -- ``ev_scenarios.py`` and the asset-registry stage that widens
#: it -- write ``ontology_class``.
SCENARIO_CLASS_COLUMN = "ontology_class"

#: Column the scenario asset registry scopes each row to.
SCENARIO_ID_COLUMN = "scenario_id"

#: Coordinate spellings for artifacts outside the declared base contract, in
#: resolution order. One pair, because the asset-registry producer writes the
#: same ``lat``/``lon`` the base adapters do -- carrying more would be
#: tolerance rather than evidence, the :mod:`gridalyn.twin.network.schema`
#: posture.
_UNDECLARED_COORDINATE_SPELLINGS = (("lat", "lon"),)

#: Identity spellings for artifacts outside the declared base contract. The
#: scenario asset registry keys every row by ``building_id``; the semantic node
#: table keys by ``node_id``.
_UNDECLARED_IDENTITY_SPELLINGS = ("building_id", "node_id", "entity_id")

#: Canonical file name of the graph's own manifest inside the semantic dir.
GRAPH_MANIFEST_FILENAME = "graph_manifest.json"

#: Canonical file name of the graph's validation report.
VALIDATION_REPORT_FILENAME = "validation_report.json"

#: Semantic artifacts whose file name is fixed, keyed by the name the catalog
#: publishes them under. The profile document is *not* here: its file name
#: carries the profile id (``profile_north_america.json``), so it is derived.
SEMANTIC_ARTIFACT_FILENAMES: dict[str, str] = {
    "nodes": "nodes.parquet",
    "edges": "edges.parquet",
    "graph_manifest": GRAPH_MANIFEST_FILENAME,
    "validation_report": VALIDATION_REPORT_FILENAME,
}

#: Why a class list can be empty without the twin being broken. Held as a
#: constant so the reason travels with the value, matching
#: :data:`gridalyn.twin.network.model.SCENARIO_TIME_ABSENT_REASON`.
CLASSES_ABSENT_REASON = (
    "no artifact of this twin declared an ontology class; a base built by an "
    "adapter that writes no class column, and a twin with no materialized "
    "semantic graph, are both legitimate models -- rebuild the semantic layer "
    "with `gridalyn twin semantic` to publish graph classes"
)


@dataclass(frozen=True)
class OntologyClass:
    """One ontology class the twin declares, with where it was read from.

    Attributes:
        name: The class as the twin spells it. CURIE-prefixed in the
            ``semantic_graph`` population, bare in the other two -- the
            spelling is reported, never normalized, because normalizing would
            merge ``brick:Building`` and ``Building``, which count different
            populations.
        count: Rows carrying the class in the artifact it was read from.
        population: Which of the three populations this came from --
            :data:`POPULATION_BASE`, :data:`POPULATION_GRAPH` or
            :data:`POPULATION_SCENARIO`.
        artifact: Canonical artifact the rows live in.
        column: Column the class was read off.
        located: Whether that artifact's rows carry coordinates directly, so a
            consumer can tell a drawable class from one it would have to join
            to reach.
        coordinates: The columns the coordinates are spelled in, or ``None``
            when there are none. Named rather than left implicit: a client told
            only that a class is drawable would have to assume ``lat``/``lon``.
        identity: Column naming each row's entity, or ``None``. What a view
            says when it labels a drawn feature.
        scenario_column: Column the rows are scoped by, or ``None`` when the
            population is not scenario-scoped. Declared for the same reason as
            ``coordinates``: a consumer that has to filter by scenario would
            otherwise assume the spelling.
        scenario_id: Scenario the count is scoped to, or ``None`` when the
            population is not scenario-scoped. A class in the scenario
            population appears once per scenario: its count is a property of
            the pair, not of the class.
        derived_from: Canonical artifacts the rows originate in, when the
            artifact holding them is itself derived. Populated only for the
            ``semantic_graph`` population, where a node records the table it
            was emitted from -- which is how a consumer links
            ``brick:Building`` back to the ``buildings`` table that can be
            drawn. Empty elsewhere, because there the artifact *is* the
            source.
    """

    name: str
    count: int
    population: str
    artifact: str
    column: str
    located: bool
    scenario_id: str | None = None
    derived_from: tuple[str, ...] = ()
    coordinates: Mapping[str, str] | None = None
    identity: str | None = None
    scenario_column: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native rendering for a catalog or report."""
        return {
            "class": self.name,
            "count": self.count,
            "population": self.population,
            "artifact": self.artifact,
            "column": self.column,
            "located": self.located,
            "coordinates": dict(self.coordinates) if self.coordinates else None,
            "identity": self.identity,
            "scenario_column": self.scenario_column,
            "scenario_id": self.scenario_id,
            "derived_from": list(self.derived_from),
        }


@dataclass(frozen=True)
class SemanticPublication:
    """The twin's ontology, in the shape a consumer can act on.

    Attributes:
        profile: Active semantic profile id, or ``None`` when the twin has no
            materialized graph.
        node_count: Nodes in the materialized graph, or ``None``.
        edge_count: Edges in the materialized graph, or ``None``.
        valid: The graph's validation verdict, or ``None`` when no graph or no
            report. ``None`` is "not checked", which is a different statement
            from ``False``.
        errors: Validation errors reported, or ``None`` when unchecked.
        warnings: Validation warnings reported, or ``None`` when unchecked.
        classes: Every declared class, across all three populations.
    """

    profile: str | None
    node_count: int | None
    edge_count: int | None
    valid: bool | None
    errors: int | None
    warnings: int | None
    classes: tuple[OntologyClass, ...]

    @property
    def populations(self) -> tuple[str, ...]:
        """Return the populations that contributed a class, in declared order."""
        seen: list[str] = []
        for entry in self.classes:
            if entry.population not in seen:
                seen.append(entry.population)
        return tuple(seen)

    def classes_in(self, population: str) -> tuple[OntologyClass, ...]:
        """Return only the classes read from one population."""
        return tuple(entry for entry in self.classes if entry.population == population)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native payload for a catalog or report."""
        return {
            "profile": self.profile,
            "graph": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "validation": {
                    "valid": self.valid,
                    "errors": self.errors,
                    "warnings": self.warnings,
                },
            },
            "populations": list(self.populations),
            "classes": [entry.to_dict() for entry in self.classes],
            # Stated rather than left to inference: an empty list is a
            # legitimate twin, not a failed read.
            "classes_absent_reason": (None if self.classes else CLASSES_ABSENT_REASON),
        }


def _coordinates(frame: pd.DataFrame, artifact: str) -> dict[str, str] | None:
    """Resolve the columns ``frame``'s coordinates are spelled in, or ``None``.

    Naming the columns rather than only answering "is it located" is what stops
    the consumer guessing: a client told a class is drawable but not which
    columns hold its position has to assume ``lat``/``lon``, which is the same
    guess ``network_model.geography.located_artifacts`` exists to remove.

    Args:
        frame: Loaded table.
        artifact: Canonical base artifact name when the frame is one, else a
            free name -- an artifact outside the declared base contract is
            resolved against :data:`_UNDECLARED_COORDINATE_SPELLINGS`.

    Returns:
        ``{"latitude": ..., "longitude": ...}``, or ``None`` when the frame
        carries no usable pair.
    """
    if artifact in BASE_TABLE_SCHEMAS:
        schema = table_schema(artifact)
        # A table that declares no coordinate role is unlocated by contract --
        # `grid_lines` and `grid_transformers` carry bus endpoints, not
        # positions -- so asking the schema to resolve one would raise rather
        # than answer the question.
        if not {ROLE_LATITUDE, ROLE_LONGITUDE} <= set(schema.roles):
            return None
        latitude = schema.resolve(frame, ROLE_LATITUDE)
        longitude = schema.resolve(frame, ROLE_LONGITUDE)
    else:
        columns = set(frame.columns)
        latitude, longitude = next(
            (pair for pair in _UNDECLARED_COORDINATE_SPELLINGS if set(pair) <= columns),
            (None, None),
        )
    if latitude is None or longitude is None:
        return None
    return {"latitude": latitude, "longitude": longitude}


def _identity(frame: pd.DataFrame, artifact: str) -> str | None:
    """Resolve the column naming each row's entity, or ``None``.

    Args:
        frame: Loaded table.
        artifact: Canonical base artifact name when the frame is one, else a
            free name.

    Returns:
        The identity column name, or ``None`` when the frame carries none.
    """
    if artifact in BASE_TABLE_SCHEMAS:
        return table_schema(artifact).resolve(frame, ROLE_IDENTITY)
    columns = set(frame.columns)
    return next(
        (name for name in _UNDECLARED_IDENTITY_SPELLINGS if name in columns),
        None,
    )


def _counts(values: pd.Series) -> list[tuple[str, int]]:
    """Return ``(class, count)`` pairs sorted by class, nulls dropped."""
    tallied = values.dropna().astype(str).value_counts()
    return sorted((str(name), int(count)) for name, count in tallied.items())


def resolve_base_ontology_classes(
    frames: Mapping[str, pd.DataFrame],
) -> tuple[OntologyClass, ...]:
    """Resolve the classes each base table declares on its class column.

    Args:
        frames: Loaded base tables keyed by canonical artifact name. Artifacts
            that declare no class column, and artifacts absent from the
            mapping, are skipped rather than treated as errors.

    Returns:
        One entry per (artifact, class) pair, artifacts in declared order.
    """
    resolved: list[OntologyClass] = []
    for artifact, schema in BASE_TABLE_SCHEMAS.items():
        if ROLE_ONTOLOGY_CLASS not in schema.roles:
            continue
        frame = frames.get(artifact)
        if frame is None or frame.empty:
            continue
        column = schema.resolve(frame, ROLE_ONTOLOGY_CLASS)
        if column is None:
            continue
        coordinates = _coordinates(frame, artifact)
        identity = _identity(frame, artifact)
        for name, count in _counts(frame[column]):
            resolved.append(
                OntologyClass(
                    name=name,
                    count=count,
                    population=POPULATION_BASE,
                    artifact=artifact,
                    column=column,
                    located=coordinates is not None,
                    coordinates=coordinates,
                    identity=identity,
                )
            )
    return tuple(resolved)


def resolve_graph_ontology_classes(
    nodes: pd.DataFrame,
    *,
    artifact: str = "semantic_nodes",
) -> tuple[OntologyClass, ...]:
    """Resolve the classes the materialized semantic graph carries.

    Args:
        nodes: Loaded ``nodes.parquet``. A frame without the class column
            yields nothing rather than raising -- a graph written by a future
            emitter that spells it differently is a *missing* publication, not
            a broken twin.
        artifact: Name to report the classes under.

    Returns:
        One entry per class, sorted by class name.
    """
    if nodes.empty or GRAPH_CLASS_COLUMN not in nodes.columns:
        return ()
    coordinates = _coordinates(nodes, artifact)
    identity = _identity(nodes, artifact)
    sources = _graph_sources(nodes)
    return tuple(
        OntologyClass(
            name=name,
            count=count,
            population=POPULATION_GRAPH,
            artifact=artifact,
            column=GRAPH_CLASS_COLUMN,
            located=coordinates is not None,
            coordinates=coordinates,
            identity=identity,
            derived_from=sources.get(name, ()),
        )
        for name, count in _counts(nodes[GRAPH_CLASS_COLUMN])
    )


def _graph_sources(nodes: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    """Return the source tables each graph class was emitted from.

    Args:
        nodes: Loaded node table.

    Returns:
        Class name to sorted source-table names. Empty when the node table
        records no source, which a future emitter is free to do.
    """
    if GRAPH_SOURCE_COLUMN not in nodes.columns:
        return {}
    pairs = nodes[[GRAPH_CLASS_COLUMN, GRAPH_SOURCE_COLUMN]].dropna()
    grouped = pairs.astype(str).groupby(GRAPH_CLASS_COLUMN)[GRAPH_SOURCE_COLUMN]
    return {
        str(name): tuple(sorted(set(values)))
        for name, values in grouped.agg(list).items()
    }


def resolve_scenario_ontology_classes(
    assets: pd.DataFrame,
    *,
    artifact: str = "asset_registry",
) -> tuple[OntologyClass, ...]:
    """Resolve the classes a scenario asset registry declares, per scenario.

    This is the only population whose class varies *within* an artifact, which
    is what makes it the one a map can encode as a dimension rather than as a
    per-table constant.

    Args:
        assets: Loaded asset registry. Must carry the class column; the
            scenario column is optional, and without it every class is
            reported unscoped.
        artifact: Name to report the classes under.

    Returns:
        One entry per (scenario, class) pair, sorted by scenario then class.
    """
    if assets.empty or SCENARIO_CLASS_COLUMN not in assets.columns:
        return ()
    coordinates = _coordinates(assets, artifact)
    identity = _identity(assets, artifact)

    scoped = SCENARIO_ID_COLUMN in assets.columns

    def _entry(name: str, count: int, scenario_id: str | None) -> OntologyClass:
        return OntologyClass(
            name=name,
            count=count,
            population=POPULATION_SCENARIO,
            artifact=artifact,
            column=SCENARIO_CLASS_COLUMN,
            located=coordinates is not None,
            coordinates=coordinates,
            identity=identity,
            scenario_column=SCENARIO_ID_COLUMN if scoped else None,
            scenario_id=scenario_id,
        )

    if not scoped:
        return tuple(
            _entry(name, count, None)
            for name, count in _counts(assets[SCENARIO_CLASS_COLUMN])
        )
    resolved: list[OntologyClass] = []
    for scenario_id, group in assets.groupby(SCENARIO_ID_COLUMN, sort=True):
        resolved.extend(
            _entry(name, count, str(scenario_id))
            for name, count in _counts(group[SCENARIO_CLASS_COLUMN])
        )
    return tuple(resolved)


def semantic_artifact_filenames(profile: str | None) -> dict[str, str]:
    """Return the semantic dir's file names, keyed by published artifact name.

    Args:
        profile: Active profile id, or ``None``. The profile document's name
            carries the id, so a twin with no profile publishes no profile
            path rather than a guessed one.

    Returns:
        Published-name to file-name mapping.
    """
    names = dict(SEMANTIC_ARTIFACT_FILENAMES)
    if profile:
        names["profile"] = f"profile_{profile}.json"
    return names


def read_graph_manifest(semantic_dir: Path | str) -> dict[str, Any]:
    """Read a semantic dir's graph manifest, or return an empty mapping.

    Args:
        semantic_dir: Directory holding the materialized graph.

    Returns:
        The parsed manifest. An absent or unparseable manifest yields ``{}``,
        matching how the catalog reads a base snapshot's ``metadata.json``:
        a twin with no semantic layer is a legitimate model.
    """
    path = Path(semantic_dir) / GRAPH_MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_int(value: Any) -> int | None:
    """Coerce a manifest count to ``int``, or ``None`` when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def resolve_semantic_publication(
    *,
    manifest: Mapping[str, Any] | None = None,
    base_frames: Mapping[str, pd.DataFrame] | None = None,
    graph_nodes: pd.DataFrame | None = None,
    scenario_assets: pd.DataFrame | None = None,
) -> SemanticPublication:
    """Resolve the twin's ontology from the artifacts that carry it.

    Args:
        manifest: Parsed ``graph_manifest.json``, or ``None``. Supplies the
            profile id, the graph counts and the validation verdict -- all of
            which the manifest already states, so the multi-megabyte node and
            edge tables are never read for them.
        base_frames: Loaded base tables keyed by canonical artifact name.
        graph_nodes: Loaded ``nodes.parquet``, or ``None`` when the caller
            declines the read. Its absence costs the graph *class* counts, not
            the graph counts, which come from the manifest.
        scenario_assets: Loaded scenario asset registry, or ``None``.

    Returns:
        The resolved :class:`SemanticPublication`. A twin with none of these
        still returns a value -- every field ``None`` and no classes -- rather
        than raising: a twin without a semantic layer is a legitimate model,
        not an error.
    """
    document = dict(manifest or {})
    validation = document.get("validation")
    if not isinstance(validation, Mapping):
        validation = {}
    valid = validation.get("valid")

    classes: list[OntologyClass] = []
    classes.extend(resolve_base_ontology_classes(base_frames or {}))
    if graph_nodes is not None:
        classes.extend(resolve_graph_ontology_classes(graph_nodes))
    if scenario_assets is not None:
        classes.extend(resolve_scenario_ontology_classes(scenario_assets))

    return SemanticPublication(
        profile=document.get("semantic_profile") or None,
        node_count=_as_int(document.get("node_count")),
        edge_count=_as_int(document.get("edge_count")),
        valid=valid if isinstance(valid, bool) else None,
        errors=_as_int(validation.get("error_count")),
        warnings=_as_int(validation.get("warning_count")),
        classes=tuple(classes),
    )


__all__ = [
    "CLASSES_ABSENT_REASON",
    "GRAPH_CLASS_COLUMN",
    "GRAPH_MANIFEST_FILENAME",
    "GRAPH_SOURCE_COLUMN",
    "POPULATION_BASE",
    "POPULATION_GRAPH",
    "POPULATION_SCENARIO",
    "SCENARIO_CLASS_COLUMN",
    "SCENARIO_ID_COLUMN",
    "SEMANTIC_ARTIFACT_FILENAMES",
    "VALIDATION_REPORT_FILENAME",
    "OntologyClass",
    "SemanticPublication",
    "read_graph_manifest",
    "resolve_base_ontology_classes",
    "resolve_graph_ontology_classes",
    "resolve_scenario_ontology_classes",
    "resolve_semantic_publication",
    "semantic_artifact_filenames",
]

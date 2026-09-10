"""Validation for the federated semantic digital-twin graph.

A graph is checked against the profile it was built with. Structural checks
come first -- columns, identity, edge endpoints, declared types and
relationships -- then the profile's **axioms**: each relationship's one
predicate IRI, its domain and range, its per-source cardinality; then the
profile's scenario count rules.

**Re-based 2026-09-10.** Before, the only relationship rules
were written here by hand (``HAS_LOAD`` and ``CONNECTED_TO`` exactly once, and
three CLS counts), and no predicate, domain or range was checked: an ``OFFERS``
edge from a transformer to a building passed. Every axiom now comes from the
profile, so a capability's rules travel with its declaration.

Axiom violations aggregate by (relationship, offending type or IRI) with a
count, so a systematic emitter bug is one message, not ten thousand lines.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_REQUIRED_NODE_COLUMNS = frozenset(
    {
        "node_id",
        "labels",
        "semantic_type",
        "semantic_uri",
        "source_standard",
        "source_table",
        "source_id",
        "name",
        "scenario_id",
        "properties",
    }
)
_REQUIRED_EDGE_COLUMNS = frozenset(
    {
        "edge_id",
        "source_id",
        "target_id",
        "relationship_type",
        "semantic_uri",
        "source_standard",
        "source_table",
        "scenario_id",
        "properties",
    }
)

#: Property-name endings that must carry a unit instead (``_kw``, ``_kv``...).
_UNITLESS_SUFFIXES = ("power", "voltage", "current")

NO_AXIOMS_WARNING = (
    "profile declares no relationship axioms; predicate IRIs, domain, range "
    "and cardinality were not checked"
)


def _loads_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(value)


def validate_semantic_graph(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    profile: Mapping[str, Any],
    expected_scenario_counts: Mapping[str, Mapping[str, int]] | None = None,
) -> dict[str, Any]:
    """Validate a semantic graph against the profile it was built with.

    Args:
        nodes: The graph's node table.
        edges: The graph's edge table.
        profile: A profile from
            :func:`~gridalyn.twin.semantic.profile.profile_with_capabilities`.
        expected_scenario_counts: ``{scenario_id: {count_key: value}}``. Every
            key must have a rule in ``profile["scenario_counts"]``; a key with
            no rule is an error, never a silent skip.

    Returns:
        A report with ``valid``, node and edge counts, ``errors`` and
        ``warnings``.
    """
    errors = _missing_column_errors(nodes, edges)
    warnings: list[str] = []
    if errors:
        return _report(nodes, edges, errors, warnings)

    errors.extend(_identity_errors(nodes, edges))
    errors.extend(_vocabulary_errors(nodes, edges, profile))
    axioms = profile.get("relationships")
    if axioms:
        types = nodes.drop_duplicates("node_id").set_index("node_id")["semantic_type"]
        errors.extend(_predicate_errors(edges, axioms))
        errors.extend(_domain_range_errors(edges, types, axioms))
        errors.extend(_cardinality_errors(nodes, edges, axioms))
    else:
        warnings.append(NO_AXIOMS_WARNING)
    errors.extend(
        _scenario_count_errors(
            nodes, profile.get("scenario_counts", {}), expected_scenario_counts or {}
        )
    )
    errors.extend(_unit_errors(nodes))
    return _report(nodes, edges, errors, warnings)


def _missing_column_errors(nodes: pd.DataFrame, edges: pd.DataFrame) -> list[str]:
    errors = []
    if missing := sorted(_REQUIRED_NODE_COLUMNS - set(nodes.columns)):
        errors.append(f"nodes missing columns: {', '.join(missing)}")
    if missing := sorted(_REQUIRED_EDGE_COLUMNS - set(edges.columns)):
        errors.append(f"edges missing columns: {', '.join(missing)}")
    return errors


def _identity_errors(nodes: pd.DataFrame, edges: pd.DataFrame) -> list[str]:
    errors = []
    if nodes["node_id"].duplicated().any():
        errors.append("duplicate node_id values found")
    if edges["edge_id"].duplicated().any():
        errors.append("duplicate edge_id values found")
    node_ids = nodes["node_id"]
    dangling = edges.loc[
        ~edges["source_id"].isin(node_ids) | ~edges["target_id"].isin(node_ids)
    ]
    errors.extend(
        f"edge {edge_id} has missing endpoint {source} -> {target}"
        for edge_id, source, target in zip(
            dangling["edge_id"],
            dangling["source_id"],
            dangling["target_id"],
            strict=True,
        )
    )
    return errors


def _vocabulary_errors(
    nodes: pd.DataFrame, edges: pd.DataFrame, profile: Mapping[str, Any]
) -> list[str]:
    errors = []
    namespaces = profile.get("namespaces", {})
    allowed_types = set(profile.get("allowed_semantic_types", []))
    allowed_relationships = set(profile.get("relationship_types", []))
    for semantic_type in sorted(nodes["semantic_type"].dropna().unique()):
        if ":" not in semantic_type:
            errors.append(f"semantic type lacks namespace: {semantic_type}")
            continue
        if semantic_type.split(":", 1)[0] not in namespaces:
            errors.append(f"semantic type uses unknown namespace: {semantic_type}")
        if allowed_types and semantic_type not in allowed_types:
            errors.append(f"semantic type not listed in profile: {semantic_type}")
    for relationship in sorted(edges["relationship_type"].dropna().unique()):
        if allowed_relationships and relationship not in allowed_relationships:
            errors.append(f"relationship type not listed in profile: {relationship}")
    return errors


def _predicate_errors(
    edges: pd.DataFrame, axioms: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    iri_by_relationship = {name: spec["iri"] for name, spec in axioms.items()}
    declared = edges.loc[edges["relationship_type"].isin(list(iri_by_relationship))]
    expected = declared["relationship_type"].map(iri_by_relationship)
    wrong = declared.loc[declared["semantic_uri"] != expected]
    counts = wrong.groupby(["relationship_type", "semantic_uri"]).size()
    return [
        f"relationship {relationship}: {count} edge(s) carry IRI {iri}; the "
        f"profile declares {iri_by_relationship[relationship]}"
        for (relationship, iri), count in counts.items()
    ]


def _outside(
    relationship: str, side: str, observed: pd.Series, allowed: list[str]
) -> list[str]:
    present = observed.dropna()
    offending = present.loc[~present.isin(allowed)].value_counts()
    verb = "start at" if side == "domain" else "end at"
    return [
        f"relationship {relationship}: {count} edge(s) {verb} {semantic_type}, "
        f"outside its {side} ({', '.join(allowed)})"
        for semantic_type, count in sorted(offending.items())
    ]


def _domain_range_errors(
    edges: pd.DataFrame, types: pd.Series, axioms: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    source_types = edges["source_id"].map(types)
    target_types = edges["target_id"].map(types)
    errors: list[str] = []
    for name in sorted(axioms):
        selected = edges["relationship_type"] == name
        spec = axioms[name]
        errors.extend(
            _outside(name, "domain", source_types[selected], list(spec["domain"]))
        )
        errors.extend(
            _outside(name, "range", target_types[selected], list(spec["range"]))
        )
    return errors


def _cardinality_errors(
    nodes: pd.DataFrame, edges: pd.DataFrame, axioms: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    errors: list[str] = []
    for name in sorted(axioms):
        bounds = axioms[name].get("source_cardinality")
        if not bounds:
            continue
        low, high = int(bounds[0]), int(bounds[1])
        per_source = edges.loc[
            edges["relationship_type"] == name, "source_id"
        ].value_counts()
        subjects = nodes.loc[nodes["semantic_type"].isin(list(axioms[name]["domain"]))]
        observed = subjects["node_id"].map(per_source).fillna(0).astype(int)
        broken = (observed < low) | (observed > high)
        expectation = f"exactly {low}" if low == high else f"between {low} and {high}"
        errors.extend(
            f"{semantic_type} {node_id} must have {expectation} {name} edge(s), "
            f"found {count}"
            for node_id, semantic_type, count in zip(
                subjects.loc[broken, "node_id"],
                subjects.loc[broken, "semantic_type"],
                observed[broken],
                strict=True,
            )
        )
    return errors


def _rule_count(nodes: pd.DataFrame, scenario_id: str, rule: Mapping[str, Any]) -> int:
    selected = nodes.loc[
        (nodes["scenario_id"].fillna("") == scenario_id)
        & (nodes["semantic_type"] == rule["semantic_type"])
    ]
    flag = rule.get("property_true")
    if not flag:
        return int(len(selected))
    return int(sum(bool(_loads_json(raw).get(flag)) for raw in selected["properties"]))


def _scenario_count_errors(
    nodes: pd.DataFrame,
    rules: Mapping[str, Mapping[str, Any]],
    expected_counts: Mapping[str, Mapping[str, int]],
) -> list[str]:
    errors: list[str] = []
    declared = ", ".join(sorted(rules)) or "none"
    for scenario_id in sorted(expected_counts):
        for key, expected in sorted(expected_counts[scenario_id].items()):
            rule = rules.get(key)
            if rule is None:
                errors.append(
                    f"scenario {scenario_id}: expected count {key!r} has no rule in "
                    f"the profile (declared: {declared})"
                )
                continue
            actual = _rule_count(nodes, scenario_id, rule)
            if actual != expected:
                errors.append(
                    f"scenario {scenario_id} {key} expected {expected} got {actual}"
                )
    return errors


def _unit_errors(nodes: pd.DataFrame) -> list[str]:
    return [
        f"property {key} on {node_id} lacks explicit unit"
        for node_id, raw in zip(nodes["node_id"], nodes["properties"], strict=True)
        for key in _loads_json(raw)
        if key.endswith(_UNITLESS_SUFFIXES)
    ]


def write_validation_report(report: dict[str, Any], path: Path) -> None:
    """Write a validation report as sorted, indented JSON.

    Args:
        report: A report from :func:`validate_semantic_graph`.
        path: Destination file; parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)


def _report(
    nodes: pd.DataFrame, edges: pd.DataFrame, errors: list[str], warnings: list[str]
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "valid": len(errors) == 0,
        "node_count": int(len(nodes)),
        "edge_count": int(len(edges)),
        "error_count": int(len(errors)),
        "warning_count": int(len(warnings)),
        "errors": errors,
        "warnings": warnings,
    }

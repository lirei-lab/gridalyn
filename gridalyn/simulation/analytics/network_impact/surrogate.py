"""GNN-ready network impact surrogate artifacts for flexibility selection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.twin.semantic.profile import NAMESPACES, SEMANTIC_TYPE, semantic_uri

NODE_COLUMNS = [
    "node_id",
    "node_type",
    "semantic_type",
    "semantic_uri",
    "scenario_id",
    "pandapower_id",
    "features_json",
]

EDGE_COLUMNS = [
    "edge_id",
    "source_id",
    "target_id",
    "edge_type",
    "semantic_type",
    "semantic_uri",
    "scenario_id",
    "features_json",
]


def _json(data: dict[str, Any]) -> str:
    clean = {key: (None if pd.isna(value) else value) for key, value in data.items()}
    return json.dumps(clean, sort_keys=True)


def _uri_for(qname: str) -> str:
    """Resolve a qname to its namespace URI when the prefix is registered."""
    prefix = qname.split(":", 1)[0] if ":" in qname else ""
    if prefix in NAMESPACES:
        return semantic_uri(qname)
    return qname


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _add_node(nodes: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    nodes.setdefault(row["node_id"], row)


def _numeric_features(features_json: str) -> dict[str, float]:
    features = json.loads(features_json or "{}")
    numeric: dict[str, float] = {}
    for key, value in features.items():
        if isinstance(value, bool):
            numeric[f"feature_{key}"] = float(value)
        elif isinstance(value, (int, float)) and not pd.isna(value):
            numeric[f"feature_{key}"] = float(value)
    return numeric


def build_graph_snapshot(
    providers: pd.DataFrame,
    sensitivity: pd.DataFrame,
    *,
    scenario_id: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build graph node/edge records with schemas compatible with a future GNN."""
    _require_columns(
        providers,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "building_id",
            "load_id",
            "ev_id",
            "pandapower_load",
            "load_bus_id",
            "feeder_bus_id",
            "constraint_zone_id",
            "constraint_zone_type",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        ],
        "providers",
    )
    _require_columns(
        sensitivity,
        [
            "provider_id",
            "scenario_id",
            "constraint_id",
            "constraint_type",
            "sensitivity_kw_per_kw",
            "deliverability_factor",
            "available_relief_kw",
        ],
        "sensitivity",
    )

    providers = providers.copy()
    sensitivity = sensitivity.copy()
    if scenario_id is not None:
        providers = providers.loc[providers["scenario_id"] == scenario_id].copy()
        sensitivity = sensitivity.loc[sensitivity["scenario_id"] == scenario_id].copy()

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for scenario in sorted(providers["scenario_id"].dropna().unique()):
        scenario_node = f"scenario:{scenario}"
        _add_node(
            nodes,
            {
                "node_id": scenario_node,
                "node_type": "scenario",
                "semantic_type": SEMANTIC_TYPE["scenario"],
                "semantic_uri": _uri_for(SEMANTIC_TYPE["scenario"]),
                "scenario_id": scenario,
                "pandapower_id": None,
                "features_json": _json({"scenario_id": scenario}),
            },
        )

    for provider in providers.to_dict("records"):
        scenario = provider["scenario_id"]
        scenario_node = f"scenario:{scenario}"
        provider_id = provider["provider_id"]
        building_id = provider["building_id"]
        load_id = provider["load_id"]
        ev_id = provider.get("ev_id")
        load_bus_id = provider["load_bus_id"]
        feeder_bus_id = provider["feeder_bus_id"]

        _add_node(
            nodes,
            {
                "node_id": provider_id,
                "node_type": "provider",
                "semantic_type": SEMANTIC_TYPE["flexibility_provider"],
                "semantic_uri": _uri_for(SEMANTIC_TYPE["flexibility_provider"]),
                "scenario_id": scenario,
                "pandapower_id": provider.get("pandapower_load"),
                "features_json": _json(
                    {
                        "provider_type": provider["provider_type"],
                        "available_capacity_kw": float(
                            provider["available_capacity_kw"]
                        ),
                        "base_cost_per_kw_h": float(provider["base_cost_per_kw_h"]),
                        "selection_priority": int(provider["selection_priority"]),
                    }
                ),
            },
        )
        _add_node(
            nodes,
            {
                "node_id": building_id,
                "node_type": "building",
                "semantic_type": SEMANTIC_TYPE["building"],
                "semantic_uri": _uri_for(SEMANTIC_TYPE["building"]),
                "scenario_id": scenario,
                "pandapower_id": provider.get("pandapower_load"),
                "features_json": _json({"load_id": load_id}),
            },
        )
        _add_node(
            nodes,
            {
                "node_id": load_id,
                "node_type": "load",
                "semantic_type": SEMANTIC_TYPE["energy_consumer"],
                "semantic_uri": _uri_for(SEMANTIC_TYPE["energy_consumer"]),
                "scenario_id": scenario,
                "pandapower_id": provider.get("pandapower_load"),
                "features_json": _json(
                    {"pandapower_load": provider.get("pandapower_load")}
                ),
            },
        )
        for bus_id in [load_bus_id, feeder_bus_id]:
            _add_node(
                nodes,
                {
                    "node_id": bus_id,
                    "node_type": "bus",
                    "semantic_type": SEMANTIC_TYPE["connectivity_node"],
                    "semantic_uri": _uri_for(SEMANTIC_TYPE["connectivity_node"]),
                    "scenario_id": scenario,
                    "pandapower_id": str(bus_id).replace("bus:", ""),
                    "features_json": _json({"bus_role": "load_or_feeder"}),
                },
            )
        if ev_id:
            _add_node(
                nodes,
                {
                    "node_id": ev_id,
                    "node_type": "evse",
                    "semantic_type": SEMANTIC_TYPE["evse"],
                    "semantic_uri": _uri_for(SEMANTIC_TYPE["evse"]),
                    "scenario_id": scenario,
                    "pandapower_id": provider.get("pandapower_load"),
                    "features_json": _json(
                        {"provider_type": provider["provider_type"]}
                    ),
                },
            )

        raw_edges = [
            (
                f"{scenario_node}|scenario_includes|{provider_id}",
                scenario_node,
                provider_id,
                "scenario_includes",
                "dt:INCLUDES_ASSET",
                {"scenario_id": scenario},
            ),
            (
                f"{provider_id}|offers_flexibility|{building_id}",
                provider_id,
                building_id,
                "offers_flexibility",
                "efont:providesFlexibility",
                {"provider_type": provider["provider_type"]},
            ),
            (
                f"{building_id}|has_load|{load_id}",
                building_id,
                load_id,
                "has_load",
                "dt:HAS_LOAD",
                {"pandapower_load": provider.get("pandapower_load")},
            ),
            (
                f"{load_id}|connected_to|{load_bus_id}",
                load_id,
                load_bus_id,
                "connected_to",
                "cim:ConnectivityNode",
                {"path_role": "load_bus"},
            ),
            (
                f"{load_bus_id}|feeds_from|{feeder_bus_id}",
                feeder_bus_id,
                load_bus_id,
                "feeds",
                "cim:Feeder",
                {"path_role": "feeder_bus"},
            ),
        ]
        if ev_id:
            raw_edges.append(
                (
                    f"{building_id}|has_evse|{ev_id}",
                    building_id,
                    ev_id,
                    "has_evse",
                    "dt:HAS_EVSE",
                    {"provider_type": provider["provider_type"]},
                )
            )

        for edge_id, source, target, edge_type, semantic_type, features in raw_edges:
            edges.setdefault(
                edge_id,
                {
                    "edge_id": edge_id,
                    "source_id": source,
                    "target_id": target,
                    "edge_type": edge_type,
                    "semantic_type": semantic_type,
                    "semantic_uri": _uri_for(semantic_type),
                    "scenario_id": scenario,
                    "features_json": _json(features),
                },
            )

    for row in sensitivity.to_dict("records"):
        constraint_id = row["constraint_id"]
        scenario = row["scenario_id"]
        _add_node(
            nodes,
            {
                "node_id": constraint_id,
                "node_type": "constraint",
                "semantic_type": row.get(
                    "constraint_type", SEMANTIC_TYPE["power_transformer"]
                ),
                "semantic_uri": _uri_for(
                    row.get("constraint_type", SEMANTIC_TYPE["power_transformer"])
                ),
                "scenario_id": scenario,
                "pandapower_id": str(constraint_id).replace("transformer:", ""),
                "features_json": _json({"constraint_type": row.get("constraint_type")}),
            },
        )
        edge_id = f"{row['provider_id']}|constrains|{constraint_id}"
        edges.setdefault(
            edge_id,
            {
                "edge_id": edge_id,
                "source_id": row["provider_id"],
                "target_id": constraint_id,
                "edge_type": "constrains",
                "semantic_type": SEMANTIC_TYPE["network_impact"],
                "semantic_uri": _uri_for(SEMANTIC_TYPE["network_impact"]),
                "scenario_id": scenario,
                "features_json": _json(
                    {
                        "sensitivity_kw_per_kw": float(row["sensitivity_kw_per_kw"]),
                        "deliverability_factor": float(row["deliverability_factor"]),
                        "available_relief_kw": float(row["available_relief_kw"]),
                    }
                ),
            },
        )

    nodes_df = (
        pd.DataFrame(nodes.values(), columns=NODE_COLUMNS)
        .sort_values("node_id")
        .reset_index(drop=True)
    )
    edges_df = (
        pd.DataFrame(edges.values(), columns=EDGE_COLUMNS)
        .sort_values("edge_id")
        .reset_index(drop=True)
    )
    return nodes_df, edges_df


def build_node_features(nodes: pd.DataFrame) -> pd.DataFrame:
    """Flatten node JSON features into a stable table usable as tensor input."""
    _require_columns(
        nodes, ["node_id", "node_type", "semantic_type", "features_json"], "nodes"
    )
    rows: list[dict[str, Any]] = []
    node_type_codes = {
        value: index for index, value in enumerate(sorted(nodes["node_type"].unique()))
    }
    for index, row in nodes.sort_values("node_id").reset_index(drop=True).iterrows():
        features = _numeric_features(row["features_json"])
        features.update(
            {
                "node_index": int(index),
                "node_id": row["node_id"],
                "node_type": row["node_type"],
                "semantic_type": row["semantic_type"],
                "feature_node_type_code": float(node_type_codes[row["node_type"]]),
            }
        )
        rows.append(features)
    return pd.DataFrame(rows).fillna(0.0)


def build_edge_features(edges: pd.DataFrame) -> pd.DataFrame:
    """Flatten edge JSON features and expose source/target indices."""
    _require_columns(
        edges,
        ["edge_id", "source_id", "target_id", "edge_type", "features_json"],
        "edges",
    )
    endpoint_ids = sorted(set(edges["source_id"]).union(set(edges["target_id"])))
    node_index = {node_id: index for index, node_id in enumerate(endpoint_ids)}
    edge_type_codes = {
        value: index for index, value in enumerate(sorted(edges["edge_type"].unique()))
    }
    rows: list[dict[str, Any]] = []
    for index, row in edges.sort_values("edge_id").reset_index(drop=True).iterrows():
        features = _numeric_features(row["features_json"])
        features.update(
            {
                "edge_index": int(index),
                "edge_id": row["edge_id"],
                "source_id": row["source_id"],
                "target_id": row["target_id"],
                "source_index": int(node_index[row["source_id"]]),
                "target_index": int(node_index[row["target_id"]]),
                "edge_type": row["edge_type"],
                "feature_edge_type_code": float(edge_type_codes[row["edge_type"]]),
            }
        )
        rows.append(features)
    return pd.DataFrame(rows).fillna(0.0)


def build_training_dataset(
    providers: pd.DataFrame,
    sensitivity: pd.DataFrame,
    *,
    scenario_id: str,
) -> pd.DataFrame:
    """Build a deterministic training table for the first surrogate baseline."""
    _require_columns(
        providers,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "constraint_zone_id",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        ],
        "providers",
    )
    _require_columns(
        sensitivity,
        [
            "provider_id",
            "scenario_id",
            "constraint_id",
            "constraint_type",
            "sensitivity_kw_per_kw",
            "available_relief_kw",
        ],
        "sensitivity",
    )
    providers = providers.loc[providers["scenario_id"] == scenario_id].copy()
    sensitivity = sensitivity.loc[sensitivity["scenario_id"] == scenario_id].copy()
    training = providers.merge(
        sensitivity,
        on=["provider_id", "scenario_id"],
        how="inner",
        validate="one_to_many",
    )
    if training.empty:
        return training

    provider_codes = {
        value: index
        for index, value in enumerate(sorted(training["provider_type"].unique()))
    }
    training["feature_provider_type_code"] = (
        training["provider_type"].map(provider_codes).astype(float)
    )
    training["feature_same_constraint_zone"] = (
        training["constraint_zone_id"] == training["constraint_id"]
    ).astype(float)
    training["feature_available_capacity_kw"] = training[
        "available_capacity_kw"
    ].astype(float)
    training["feature_base_cost_per_kw_h"] = training["base_cost_per_kw_h"].astype(
        float
    )
    training["feature_selection_priority"] = training["selection_priority"].astype(
        float
    )
    training["feature_topology_sensitivity"] = training["sensitivity_kw_per_kw"].astype(
        float
    )
    training["target_deliverability_factor"] = training["sensitivity_kw_per_kw"].clip(
        0.0, 1.0
    )
    training["target_relief_kw"] = (
        training["available_capacity_kw"].astype(float)
        * training["target_deliverability_factor"]
    )
    training["target_delta_loading_pct_per_kw"] = -training[
        "target_deliverability_factor"
    ]
    training["target_delta_v_min_pu_per_kw"] = (
        training["target_deliverability_factor"] * 0.00001
    )
    training["target_side_effect_score"] = (
        1.0 - training["target_deliverability_factor"]
    )
    return training.sort_values(["constraint_id", "provider_id"]).reset_index(drop=True)


def build_provider_impact_predictions(training: pd.DataFrame) -> pd.DataFrame:
    """Score provider/constraint pairs with the deterministic v1 tabular surrogate."""
    if training.empty:
        return training.copy()
    predictions = training.copy()
    predictions["predicted_deliverability_factor"] = predictions[
        "target_deliverability_factor"
    ]
    predictions["predicted_relief_kw"] = (
        predictions["feature_available_capacity_kw"]
        * predictions["predicted_deliverability_factor"]
    )
    predictions["predicted_delta_loading_pct_per_kw"] = predictions[
        "target_delta_loading_pct_per_kw"
    ]
    predictions["predicted_delta_v_min_pu_per_kw"] = predictions[
        "target_delta_v_min_pu_per_kw"
    ]
    predictions["predicted_side_effect_score"] = predictions["target_side_effect_score"]
    denominator = predictions["feature_base_cost_per_kw_h"].clip(
        lower=0.001
    ) * predictions["feature_selection_priority"].clip(lower=1.0)
    predictions["selection_score"] = predictions["predicted_relief_kw"] / denominator
    predictions["effective_cost_per_predicted_kw_h"] = predictions[
        "feature_base_cost_per_kw_h"
    ] / predictions["predicted_deliverability_factor"].clip(lower=0.001)
    predictions["selection_rank"] = (
        predictions.groupby(["scenario_id", "constraint_id"])["selection_score"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    columns = [
        "provider_id",
        "scenario_id",
        "provider_type",
        "constraint_id",
        "constraint_type",
        "available_capacity_kw",
        "base_cost_per_kw_h",
        "selection_priority",
        "predicted_deliverability_factor",
        "predicted_relief_kw",
        "predicted_delta_loading_pct_per_kw",
        "predicted_delta_v_min_pu_per_kw",
        "predicted_side_effect_score",
        "effective_cost_per_predicted_kw_h",
        "selection_score",
        "selection_rank",
    ]
    return (
        predictions[columns]
        .sort_values(["constraint_id", "selection_rank", "provider_id"])
        .reset_index(drop=True)
    )


def build_surrogate_report(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    training: pd.DataFrame,
    predictions: pd.DataFrame,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    """Summarize surrogate artifacts and make the validation boundary explicit."""
    positive = predictions.loc[
        predictions.get("predicted_relief_kw", pd.Series(dtype=float)) > 0.0
    ]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "network_impact_surrogate",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "model": {
            "model_family": "tabular_deterministic_v1",
            "feature_source": "semantic_graph_provider_registry_topology_sensitivity",
            "future_backend": "heterogeneous_gnn",
            "status": "baseline_surrogate_not_final_physics",
        },
        "validation": {
            "authority": "pandapower_ac_powerflow",
            "policy": (
                "use_surrogate_for_fast_screening_validate_selected_dispatch_with_pandapower"
            ),
        },
        "summary": {
            "n_nodes": int(len(nodes)),
            "n_edges": int(len(edges)),
            "n_training_rows": int(len(training)),
            "n_prediction_rows": int(len(predictions)),
            "positive_prediction_count": int(len(positive)),
            "positive_predicted_relief_kw": (
                float(positive["predicted_relief_kw"].sum()) if len(positive) else 0.0
            ),
            "constraint_count": (
                int(training["constraint_id"].nunique())
                if "constraint_id" in training
                else 0
            ),
            "provider_count": (
                int(training["provider_id"].nunique())
                if "provider_id" in training
                else 0
            ),
        },
    }


def write_surrogate_artifacts(
    out_dir: Path,
    *,
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    node_features: pd.DataFrame,
    edge_features: pd.DataFrame,
    training: pd.DataFrame,
    predictions: pd.DataFrame,
    report: dict[str, Any],
) -> dict[str, Path]:
    """Write all surrogate artifacts and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "nodes": out_dir / "network_graph_nodes.parquet",
        "edges": out_dir / "network_graph_edges.parquet",
        "node_features": out_dir / "network_node_features.parquet",
        "edge_features": out_dir / "network_edge_features.parquet",
        "training": out_dir / "network_impact_training.parquet",
        "predictions": out_dir / "network_impact_predictions.parquet",
        "report": out_dir / "network_impact_surrogate_report.json",
    }
    nodes.to_parquet(paths["nodes"], index=False)
    edges.to_parquet(paths["edges"], index=False)
    node_features.to_parquet(paths["node_features"], index=False)
    edge_features.to_parquet(paths["edge_features"], index=False)
    training.to_parquet(paths["training"], index=False)
    predictions.to_parquet(paths["predictions"], index=False)
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True))
    return paths

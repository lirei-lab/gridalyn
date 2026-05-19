# Network Impact Surrogate

The network impact surrogate is the fast screening layer between locational
flexibility selection and full pandapower validation. It does not replace the
AC power-flow solver. It estimates which providers are likely to relieve a
network constraint, ranks candidates quickly, and then hands the selected
dispatch back to pandapower for physical validation.

## Why It Exists

The current topology sensitivity is intentionally simple: a provider has a
deliverability factor of `1.0` when it is downstream of the constrained
transformer and `0.0` otherwise. That makes location visible, but it cannot
capture line loading, voltage effects, feeder impedance, base loading, or
multi-constraint side effects.

The surrogate adds an intermediate layer:

```text
semantic graph + provider registry + topology sensitivity
        ↓
GNN-ready graph snapshot and tabular features
        ↓
fast provider impact prediction
        ↓
locational provider ranking
        ↓
pandapower AC validation
```

The first model is a deterministic tabular baseline. It is deliberately
explainable and reproducible. The exported graph, node-feature, edge-feature,
training, and prediction tables are shaped so that a later heterogeneous GNN can
consume the same artifacts.

## Generated Artifacts

Generate the layer with:

```bash
uv run gridalyn market surrogate \
  --scenario-id S4 \
  --provider-registry digital_twin/flexibility/provider_registry.parquet \
  --sensitivity digital_twin/flexibility/network_sensitivity.parquet \
  --out-dir digital_twin/flexibility
```

The command writes:

```text
digital_twin/flexibility/network_graph_nodes.parquet
digital_twin/flexibility/network_graph_edges.parquet
digital_twin/flexibility/network_node_features.parquet
digital_twin/flexibility/network_edge_features.parquet
digital_twin/flexibility/network_impact_training.parquet
digital_twin/flexibility/network_impact_predictions.parquet
digital_twin/flexibility/network_impact_surrogate_report.json
```

Current S4 generation produces:

| Metric | Value |
| --- | ---: |
| Nodes | 9508 |
| Edges | 378215 |
| Training rows | 366768 |
| Prediction rows | 366768 |
| Providers | 2264 |
| Constraints | 162 |
| Positive provider-constraint predictions | 2264 |

## GNN-Ready Schema

`network_graph_nodes.parquet` stores stable graph nodes:

```text
node_id
node_type
semantic_type
semantic_uri
scenario_id
pandapower_id
features_json
```

Node types include:

```text
scenario
provider
building
load
bus
evse
constraint
```

`network_graph_edges.parquet` stores typed relationships:

```text
edge_id
source_id
target_id
edge_type
semantic_type
semantic_uri
scenario_id
features_json
```

Edge types include:

```text
scenario_includes
offers_flexibility
has_load
connected_to
feeds
has_evse
constrains
```

`network_node_features.parquet` and `network_edge_features.parquet` flatten
numeric fields from `features_json` and add stable integer indices. These are
the bridge to future tensors such as:

```text
node_feature_matrix
edge_feature_matrix
edge_index
node_type_vector
edge_type_vector
global_context_vector
target_vector
```

## Baseline Model

The v1 surrogate is named `tabular_deterministic_v1`. It produces one row per
provider-constraint pair in `network_impact_predictions.parquet`.

Important columns:

```text
provider_id
scenario_id
provider_type
constraint_id
constraint_type
available_capacity_kw
base_cost_per_kw_h
selection_priority
predicted_deliverability_factor
predicted_relief_kw
predicted_delta_loading_pct_per_kw
predicted_delta_v_min_pu_per_kw
predicted_side_effect_score
effective_cost_per_predicted_kw_h
selection_score
selection_rank
```

The baseline currently uses topology sensitivity as its deterministic target.
This preserves today’s behavior while introducing the feature and prediction
interfaces that a trained model will replace later.

## Physics Labels

The next training layer uses pandapower finite differences as labels. Generate
sample labels with:

```bash
uv run gridalyn market perturbation-samples \
  --scenario-id S4 \
  --top-constraints 6 \
  --max-providers-per-constraint 12 \
  --max-timesteps 18 \
  --perturbation-kw 2 \
  --perturbation-kw 5 \
  --perturbation-kw 10
```

The command writes:

```text
digital_twin/flexibility/network_impact_physics_labels.parquet
digital_twin/flexibility/network_impact_physics_labels_report.json
```

Each row is one provider/timestep/constraint perturbation replayed through
pandapower. Important columns include:

```text
sample_id
provider_id
provider_type
constraint_id
timestep
requested_perturbation_kw
actual_perturbation_kw
delta_constraint_trafo_loading_pct
delta_global_trafo_max_loading_pct
delta_global_line_max_loading_pct
delta_v_min_pu
delta_ext_grid_mw
relief_pct_per_kw
label_source
```

Current S4 sample run:

| Metric | Value |
| --- | ---: |
| Constraints | 6 |
| Providers | 72 |
| Timesteps | 18 |
| Samples | 3888 |
| Positive samples | 3429 |
| Mean relief | 0.53 pct-pt/kW |
| Mean voltage effect | 0.000199 pu |

These labels are the bridge from topology-only screening to a physics-trained
tabular surrogate, and later to a heterogeneous GNN. The sampler runs baseline
timesteps and perturbations in batches so it avoids one full pandapower startup
per sample.

## Physics-Trained Surrogate

Train the first physics-backed selector table with:

```bash
uv run gridalyn market train-physics-surrogate \
  --scenario-id S4 \
  --training-path digital_twin/flexibility/network_impact_training.parquet \
  --labels-path digital_twin/flexibility/network_impact_physics_labels.parquet \
  --out-dir digital_twin/flexibility
```

The command writes:

```text
digital_twin/flexibility/network_impact_physics_predictions.parquet
digital_twin/flexibility/network_impact_physics_surrogate_report.json
```

The v1 model is `tabular_physics_lookup_v1`. It uses direct
provider/constraint finite-difference labels when available, falls back to
provider-type/constraint averages, and otherwise returns zero deliverability
when there is no physical label coverage.

Current S4 training summary:

| Metric | Value |
| --- | ---: |
| Label rows | 3888 |
| Positive label rows | 3429 |
| Supervised provider-constraint pairs | 69 |
| Prediction rows | 366768 |
| Positive predictions | 114 |
| Supervised predictions | 13584 |
| Mean predicted relief | 0.53 pct-pt/kW |

Validate the physics-backed predictions with:

```bash
uv run gridalyn market verify-network-impact \
  --scenario-id S4 \
  --predictions-path digital_twin/flexibility/network_impact_physics_predictions.parquet \
  --out-path digital_twin/flexibility/network_impact_physics_verification_report.json
```

Current S4 comparison:

| Case | Delivered MWh | Shortfall MWh | Transformer max reduction | Transformer overload delta |
| --- | ---: | ---: | ---: | ---: |
| Aggregate CLS | 6.58 | 0.00 | 12.22 pct-pt | -2 |
| Topology locational | 1.08 | 5.50 | 1.66 pct-pt | -3 |
| Physics surrogate locational | 1.08 | 5.50 | 1.66 pct-pt | -3 |

With the expanded label set, the physics surrogate now matches the topology
selector on the top three validation constraints. It is still not a replacement
for pandapower; it is a faster selector whose training coverage now includes the
critical local providers used in the verification report.

## Selection Use

The locational selector should rank providers by predicted network value, not
only by cost:

```text
selection_score = predicted_relief_kw
                / (base_cost_per_kw_h * selection_priority)
```

For production dispatch, this score should be combined with:

- active constraint severity;
- voltage risk penalty;
- side-effect penalty;
- soft/hard CLS policy;
- rebound margin.

The surrogate output is a candidate ranking. It is not a final dispatch proof.

## Validation Boundary

Pandapower remains the physical authority. The recommended report flow is:

```text
unmanaged baseline
current aggregate CLS
constraint-aware clearing
verified locational clearing replay
topology-only locational selection
surrogate-ranked locational selection
```

Each candidate dispatch must be replayed through the AC power-flow engine and
compared on:

- transformer overloads;
- line overloads;
- minimum voltage;
- buses below voltage thresholds;
- local shortfall;
- cost;
- Soft/Hard CLS mix;
- rebound impact.

`constraint_aware_clearing` is the first case where the market input is local
rather than aggregate. It converts transformer loading above the selected limit
into kW requirements per transformer and timestep, clears those requirements
against providers connected to the same constraint zone, and then replays the
result through pandapower. The v1 objective uses the physical overload above
100%, so it is intentionally conservative. It proves the wiring from topology
to market to verification; later versions should add security margins, voltage
risk, line constraints, and rebound-aware requirements.

Generate the validation report with:

```bash
uv run gridalyn market verify-network-impact \
  --scenario-id S4 \
  --top-constraints 3
```

After report generation, refresh the scenario-aware dashboard catalog:

```bash
uv run gridalyn market network-impact-catalog
```

The catalog writes `digital_twin/flexibility/network_impact_catalog.json`. It
marks scenarios with available report artifacts separately from scenarios whose
Network Impact validation has not been generated yet, so the dashboard does not
reuse S4 metrics for S0-S3.

Current S4 results for the top three transformer constraints
(`transformer:64`, `transformer:99`, `transformer:110`) show:

| Case | Delivered MWh | Shortfall MWh | Transformer max reduction | Transformer overload delta |
| --- | ---: | ---: | ---: | ---: |
| Aggregate CLS | 6.58 | 0.00 | 12.22 pct-pt | -2 |
| Constraint-aware clearing | 0.022 | 0.00 | 0.25 pct-pt | 0 |
| Verified locational clearing | 0.021 | 0.001 | 0.25 pct-pt | 0 |
| Topology locational | 1.08 | 5.50 | 1.66 pct-pt | -3 |
| Surrogate locational v1 | 1.08 | 5.50 | 1.66 pct-pt | -3 |

The topology and surrogate cases match because the first surrogate is still
trained on deterministic topology sensitivity. The constraint-aware case shows
another useful boundary: clearing only the overload above 100% is feasible and
cheap, but too small to materially improve broader grid margins. The verified
locational clearing replay is the provider-level AC power-flow check and is the
preferred reference when evaluating the MVP dispatch. The important result is
not that the surrogate is better yet; it is that the report now exposes the
operational tradeoff. Aggregate CLS delivers more energy, while local-only
dispatch is much more constrained by available providers near overloaded
transformers.

## Roadmap

1. Add pandapower perturbation sampling for active constraints and critical
   timesteps.
2. Replace deterministic labels with finite-difference labels for transformer,
   line, and voltage response.
3. Train a tabular model on the graph-aware feature table.
4. Add temporal context features from load, EV, thermal limit, and weather.
5. Add a heterogeneous GNN backend that consumes the same node, edge, and
   feature artifacts.
6. Validate every selected policy with pandapower before emitting operational
   reports.

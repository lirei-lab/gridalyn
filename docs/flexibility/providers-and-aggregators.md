# Providers And Aggregators

Providers and aggregators are the operational bridge between physical assets and
decision mechanisms. A battery, building, EVSE, flexible load, inverter, or
portfolio should not enter a market or controller as an anonymous kW quantity.
It needs identity, location, capability, owner/aggregator, availability, and
verification metadata.

The current implementation is strongest for flexibility providers, but the same
shape applies to prosumers, DER voltage-support providers, storage portfolios,
and future transactive participants.

## Artifacts

Generate the provider artifacts with:

```bash
uv run gridalyn market providers \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --out-dir instances/default/digital_twin/flexibility
```

The command writes:

```text
instances/default/digital_twin/flexibility/provider_registry.parquet
instances/default/digital_twin/flexibility/network_sensitivity.parquet
instances/default/digital_twin/flexibility/provider_registry_summary.json
```

After the provider layer exists, generate the GNN-ready impact surrogate:

```bash
uv run gridalyn market surrogate \
  --scenario-id S4 \
  --out-dir instances/default/digital_twin/flexibility
```

That command adds graph, feature, training, prediction, and report artifacts
used by the fast network-impact screening layer.

## Provider Registry

`provider_registry.parquet` contains one row per controllable provider. A
provider row should answer:

- what physical or logical asset is controllable;
- who manages it;
- where it is connected;
- what it can provide;
- under which scenario or model state it is available;
- what cost, priority, reliability, or role metadata should influence
  selection.

In the current Flexibility CLS demo this includes:

- Soft CLS building providers from `soft_cls_participant`;
- Hard CLS EV providers from `has_ev` and `hard_cls_enabled`;
- building, load, EV, bus, feeder, and transformer IDs;
- available capacity in kW;
- base cost proxy;
- selection priority;
- source lineage.

Current generated counts for the larger Flexibility CLS workflow:

| Scenario | Providers | Soft building providers | Hard EV providers |
| --- | ---: | ---: | ---: |
| S0 | 970 | 970 | 0 |
| S1 | 1294 | 970 | 324 |
| S2 | 1617 | 970 | 647 |
| S3 | 1940 | 970 | 970 |
| S4 | 2264 | 970 | 1294 |

## Aggregator and Provider Hierarchy

The current model intentionally separates physical assets from market roles:

```text
Building or EV
  -> FlexibilityProvider
    -> FlexibilityOffer
      -> ConstraintZone
        -> Transformer
```

A participating Soft CLS building becomes one provider:

```text
building:123
provider:S4:building:123:soft_cls
offer:S4:building:123:soft_cls
```

A Hard CLS-enabled EV becomes one provider:

```text
ev:S4:456
provider:S4:ev:S4:456:hard_cls
offer:S4:ev:S4:456:hard_cls
```

Aggregators are represented one level above providers:

```text
aggregator:S4:soft_cls
  -> portfolio:S4:soft_cls
    -> provider:S4:building:123:soft_cls

aggregator:S4:hard_cls
  -> portfolio:S4:hard_cls
    -> provider:S4:ev:S4:456:hard_cls
```

These aggregators are currently synthetic market roles, not yet separate
commercial companies. That is deliberate: it lets the digital twin expose the
correct graph shape now, while leaving room to later split providers across
multiple real or synthetic aggregators with different territories, bids,
reliability scores, and settlement histories.

The semantic graph persists this hierarchy with:

- `MANAGES_PORTFOLIO`: aggregator to portfolio;
- `INCLUDES_PROVIDER`: portfolio to provider;
- `OFFERS`: provider to offer;
- `TARGETS_CONSTRAINT`: offer to constraint zone;
- `CONSTRAINT_ZONE_FOR`: constraint zone to transformer;
- `IMPLEMENTS_CONTRACT`: provider to Soft/Hard CLS contract.

## Network Sensitivity

`network_sensitivity.parquet` is a first-pass topology sensitivity table:

```text
provider_id
scenario_id
constraint_id
constraint_type
sensitivity_kw_per_kw
deliverability_factor
method
available_relief_kw
```

The current method is `downstream_transformer_topology`:

- a provider connected downstream of a transformer gets sensitivity `1.0` to
  that transformer;
- it gets sensitivity `0.0` to other transformers.

This is intentionally simple. It makes location visible to selection without
requiring full AC power-flow sensitivities yet. A later method should add
pandapower finite-difference sensitivity for lines, transformers, voltage, and
multi-constraint interactions.

## Selection Rule

The first selector ranks local providers by:

```text
effective_cost_per_kw_h = base_cost_per_kw_h / sensitivity_kw_per_kw
```

For a transformer constraint, this means:

1. select only providers with positive deliverability to that transformer;
2. prefer Soft CLS buildings before Hard CLS EVs through lower base cost and
   priority;
3. stop when expected relief covers the required kW.

This does not yet replace the aggregate clearing engine. It provides the
missing provider-management layer so the next clearing iteration can optimize
against network constraints rather than treating all kW as equivalent.

## Locational Clearing MVP

The first actual locational clearing artifact is generated with:

```bash
uv run gridalyn market locational-clearing \
  --scenario-id S4 \
  --top-constraints 3
```

It derives active transformer requirements from
`S4_powerflow_transformers.parquet`, ranks candidates with
`network_impact_predictions.parquet`, and writes:

```text
instances/default/digital_twin/flexibility/locational_clearing_events.parquet
instances/default/digital_twin/flexibility/locational_clearing_selections.parquet
instances/default/digital_twin/flexibility/locational_clearing_summary.json
instances/default/digital_twin/flexibility/locational_flexibility_clearing_report.json
```

Current S4 run over `transformer:64`, `transformer:99`, and
`transformer:110` clears `38` active constraint events with `64` provider
selections. The local requirement is `0.022 MWh`, fully covered by `7` unique
Soft CLS providers. This is the first actionable clearing layer: it produces
which offers were selected for which network constraint, while pandapower
verification remains the authority for physical impact.

Validate the selected providers with:

```bash
uv run gridalyn market verify-clearing \
  --scenario-id S4
```

This replays `locational_clearing_selections.parquet` on the S4 pandapower
network and writes:

```text
instances/default/digital_twin/flexibility/locational_clearing_dispatch.parquet
instances/default/digital_twin/flexibility/locational_clearing_verification_report.json
```

The current S4 verification shows `0.0208 MWh` delivered, `0.0012 MWh`
shortfall, no Hard CLS activation, and no aggregate rebound injected. The
physical comparison against unmanaged load shows `0.25` percentage points of
maximum transformer-loading relief, `0.00076 p.u.` minimum-voltage improvement,
and no overload-count delta. This is intentionally modest: the MVP clears only
the excess above selected transformer overload thresholds, not a global
substation objective.

## Network Impact Surrogate

The next layer is the network impact surrogate documented in
[Network Impact Surrogate](network-impact-surrogate.md). It is GNN-ready but
starts with an explainable tabular baseline:

- `network_graph_nodes.parquet` and `network_graph_edges.parquet` encode the
  provider/building/load/bus/constraint graph;
- `network_node_features.parquet` and `network_edge_features.parquet` expose
  stable integer indices and numeric features for future tensors;
- `network_impact_training.parquet` stores provider-constraint feature rows;
- `network_impact_predictions.parquet` stores predicted deliverability,
  expected relief, side-effect score, and selection rank;
- `network_impact_surrogate_report.json` records model scope and the pandapower
  validation boundary.

For S4, the current generated surrogate contains `9508` nodes, `378215` edges,
`366768` training rows, and `366768` prediction rows. It should be used for fast
screening and ranking. Final dispatch must still be replayed through pandapower.

## Shadow Report

The shadow report compares the current aggregate study dispatch against the
locational provider selector without changing market-clearing behavior:

```bash
uv run gridalyn market shadow-report \
  --scenario-id S4 \
  --top-constraints 3 \
  --out-path projects/flexibility_cls/outputs/reports/provider_selection_shadow_report.json
```

The report uses the top transformer constraints from
`instances/default/digital_twin/reports/mv_lv_transformer_overload_report.json`, maps them to
`transformer:*` IDs, and runs provider selection for each timestep where the
aggregate dispatch requests Soft or Hard CLS.

Current S4 shadow summary:

- constraints: `transformer:64`, `transformer:99`, `transformer:110`;
- constraint-events: `207`;
- original aggregate dispatch requirement: `6.58 MWh`;
- constraint-event requirement across the three local constraints: `19.73 MWh`;
- local selected relief with topology sensitivity: `1.60 MWh`;
- local shortfall: `18.14 MWh`;
- shortfall events: `200`.

The high local shortfall is expected and useful: it shows that the current
aggregate dispatch cannot simply be assigned to a few overloaded transformers
without locational procurement. This is the evidence needed before replacing
aggregate clearing with constraint-aware clearing.

## Network Impact Verification

The follow-up verification report replays candidate policies through pandapower:

```bash
uv run gridalyn market verify-network-impact \
  --scenario-id S4 \
  --top-constraints 3
```

It writes:

```text
instances/default/digital_twin/flexibility/network_impact_verification_report.json
```

The report compares unmanaged load, current aggregate CLS, topology-only
locational dispatch, and surrogate-ranked locational dispatch. It keeps the
surrogate honest: fast rankings are useful only if the resulting dispatch
improves voltage and loading metrics when replayed with AC power flow.

## Semantic Role

The semantic graph consumes `provider_registry.parquet` when generated with:

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --flexibility-dir instances/default/digital_twin/flexibility \
  --timeseries-dir instances/default/digital_twin/timeseries \
  --out-dir instances/default/digital_twin/semantic
```

It creates explicit market-management nodes:

- `cls:FlexibilityAggregator` for Soft CLS and Hard CLS aggregation roles;
- `cls:FlexibilityPortfolio` for each scenario/provider-type portfolio;
- `cls:FlexibilityProvider` for each controllable building or EV provider;
- `cls:FlexibilityOffer` for each provider's locational offer;
- `cls:ConstraintZone` for each scenario-specific constrained transformer zone.

The generated graph links them with `MANAGES_PORTFOLIO`, `AGGREGATES`,
`INCLUDES_PROVIDER`, `OFFERS`, `IMPLEMENTS_CONTRACT`,
`LOCATED_IN_CONSTRAINT_ZONE`, `TARGETS_CONSTRAINT`, and
`CONSTRAINT_ZONE_FOR`. In the current artifacts this adds `8085` providers,
`8085` offers, `810` constraint zones, and `9` aggregator/portfolio pairs.

The provider layer combines:

- CIM topology through `constraint_zone_id`;
- Brick/ASHRAE 223 building assets through `building_id`;
- EFOnt building flexibility semantics through Soft CLS providers;
- IEEE 2030.5 readiness through Hard CLS EV providers;
- `cls:` contracts and future locational market constraints.

This keeps the provider registry operationally useful while preserving ontology
alignment for FalkorDB migration.

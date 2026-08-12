# Utility Platform Roadmap

Gridalyn should keep supporting reproducible simulations and public demo
projects, but the core should evolve into a platform a utility could recognize:
model-centric, CIM-aligned, queryable, versioned, auditable, and extensible
through adapters and applications.

This roadmap uses Zepben/Evolve as a reference point for product philosophy, not
as a feature clone. The important pattern is a strong network model core with
SDKs, model services, network exploration, hosting capacity analysis, and import
or export adapters around the model.

Reference points:

- Zepben Evolve docs: <https://zepben.github.io/evolve/docs/>
- Energy Workbench Server network model: <https://zepben.github.io/evolve/docs/energy-workbench-server/2.19.0/network-model>
- Evolve Python SDK: <https://zepben.github.io/evolve/docs/python-sdk/0.37.0/>

## Target Position

Gridalyn will operate with synthetic data first, but its core abstractions must
look like real utility software:

- a canonical network model, not only generated study files;
- stable IDs and source-system lineage;
- versioned model snapshots;
- adapters for synthetic, GIS, simulation, semantic graph, and analytics tools;
- APIs for partial network access by feeder, transformer, substation, and
  connectivity zone;
- analytics modules that consume the same model contract;
- dashboards and study workspaces as applications above the platform, not the
  platform itself.

## Design Principles

1. **Model before outputs.** Parquet and reports remain important, but they are
   products of the model, not the model itself.
2. **CIM-first grid topology.** Distribution network entities should map cleanly
   to CIM concepts such as equipment, terminals, connectivity nodes, feeders,
   substations, energy consumers, transformers, switches, and DER assets.
3. **Synthetic data as an adapter.** Synthetic GeoJSON/network generation is one
   source adapter. Real GIS/DMS/AMI/SCADA integrations should fit the same model
   store.
4. **Project isolation.** Executable demos and studies live under `projects/`;
   reusable logic lives in `gridalyn`.
5. **Operational states are explicit.** The platform should distinguish base,
   normal, current, planned, and study-case states.
6. **Partial model access.** A utility workflow rarely needs the whole model at
   once. Feeder, transformer, zone, and downstream queries must become first
   class.
7. **Validation as product behavior.** Every import, export, scenario, and graph
   should produce validation reports with counts, warnings, and lineage.

## Current State

The current system already has several strong platform ingredients:

| Area | Current capability |
| --- | --- |
| Digital twin artifacts | `instances/default/digital_twin/base`, `models`, `scenarios`, `timeseries`, `flexibility`, `semantic`, `reports`, `dashboard`. |
| Network generation | Synthetic grid and building network generation from GeoJSON-like inputs. |
| Simulation | Pandapower execution and scenario powerflow outputs. |
| Building models | PyCity-style building, zone, device, end-use, and scenario-device overlays. |
| Flexibility | Provider registry, topology sensitivity, locational clearing, network impact surrogate, verification reports. |
| Semantic graph | North America profile with CIM, Brick/ASHRAE 223, OpenADR, IEEE 2030.5, EFOnt, and CLS extensions. |
| Project workflows | `projects/*/project.yaml` and `workflow.yaml`. |
| Dashboard | General digital twin catalog plus scenario and network impact panels. |

The main remaining weakness is boundary clarity. The public surface should keep
the architecture centered on `gridalyn`, governed `projects/`, and
`instances/default/digital_twin/`, while optional editorial material stays
outside executable platform workflows.

## Target Capability Architecture

Gridalyn is moving to a capability architecture rather than a script or
case-study architecture. The layers are:

```text
Applications And Interfaces
  CLI, dashboard, reports, future APIs

Problems And Experiments
  demo projects, hosting capacity, planning cases, benchmarks

Flexibility Market And Operations
  providers, aggregators, offers, clearing, dispatch, settlement, operational KPIs

Simulation And Validation
  pandapower, thermal checks, network-impact physics, surrogate validation

Asset And Flexibility Modeling
  buildings, EVSE, DER, loads, forecasts, flexibility envelopes

Digital Twin Core
  network model, topology, scenarios, timeseries, semantic graph, adapters

Foundation And Governance
  IDs, units, lineage, manifests, model versions, validation, artifact policy
```

The detailed layer contract is in
[Capability Architecture](capability-architecture.md) and the
[Platform Layer Model](platform-layer-model.md).

## Architecture Reference Points

The platform direction should come from a consensus of similar systems rather
than from copying one framework:

- **Zepben / Evolve:** durable network model, SDK-first access, and
  utility-grade model services.
- **GridAPPS-D:** distribution applications operating against a shared grid
  model and service layer.
- **NREL Sienna:** separation between system data, operations/planning studies,
  simulation, and analysis.
- **HELICS:** explicit interfaces for future coupled simulation and time
  coordination.
- **pandapower / OpenDSS:** solver engines beneath the platform contract.
- **Modular energy modeling frameworks:** reusable problems, environments,
  scenarios, models, and experiments, without losing Gridalyn's digital-twin and
  operations focus.

The resulting principle is simple: **Gridalyn is model-centered,
operation-aware, and application-friendly.**

## Target Package Direction

```text
gridalyn/
  foundation/       governance, release checks, reports, datasets, workspace paths
  twin/             network model repository, adapters, semantic graph, graph DB
  assets/           building, DER, EVSE, load, forecast, synthetic model synthesis
  simulation/       pandapower, LightSim2Grid, network impact, validation analytics
  operations/       providers, markets, dispatch, settlement, utility KPIs
  projects/         project/workflow manifests, execution, regressions
  interfaces/       CLI, reporting, dashboard/catalog, visualization surfaces

projects/
  minimal_grid_project/
  ieee_33_bus_demo/
  synthetic_geojson_feeder/
  prosumer_battery_market/
  der_voltage_optimization/
  rl_voltage_control_lightsim/
  ev_hosting_flex/
    project.yaml
    workflow.yaml
    scripts/
    outputs/
  admm_thermal_consensus/

instances/default/digital_twin/
  base/
  models/
  scenarios/
  timeseries/
  flexibility/
  semantic/
  reports/
  dashboard/
```

The future directories are intentional design targets. They should be introduced
only when at least one project or application consumes the new contract.

## Detailed Implementation Plan

### Phase 0: Preserve The Public V0.1 Cut

**Goal:** keep the current release candidate stable while the architecture
evolves.

**Work:**

- keep public demo projects reproducible and independent;
- keep `instances/default/digital_twin/*` artifact contracts stable;
- keep the canonical SDK imports stable while reusable logic evolves;
- keep public docs centered on the platform contract;
- run the release checks after every architecture step.

**Exit criteria:**

- `uv run --with pytest python -m pytest -q`
- `uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml`
- `uv run gridalyn platform check-artifacts --summary-only`
- `uv run gridalyn project regression projects/ev_hosting_flex`

### Phase 1: Foundation And Governance Contracts

**Goal:** make every result traceable to a model version, run, scenario, inputs,
and validation report.

**Implement:**

- `ModelVersion` contract with `model_version`, `source_system`,
  `source_adapter`, `created_at`, `artifact_hashes`, and `validation_status`;
- `StudyRun` contract with `project_id`, `workflow_id`, `run_id`, `started_at`,
  `completed_at`, stage outputs, report outputs, and regression status;
- shared manifest helpers in `gridalyn.foundation`;
- validation report schemas for adapters, projects, simulations, market runs,
  and dashboard catalogs.

**Update current artifacts:**

- `instances/default/digital_twin/base/metadata.json`;
- `projects/*/outputs/manifests/project_run_manifest.json`;
- `instances/default/digital_twin/reports/canonical/*`;
- dashboard catalog metadata.

**Tests:**

- manifests include model version and run ID;
- report inputs have hashes;
- project run manifest references required reports;
- artifact policy remains clean.

**Status:**

- `gridalyn.foundation` exposes `ModelVersion` and `StudyRun` governance
  contracts.
- `instances/default/digital_twin/base/metadata.json` includes `model_version_id` and a structured
  `model_version` object.
- Project dry runs and executions include a structured `study_run` object in
  `project_run_manifest.json`.
- Platform report helpers can carry `model_version_id` and `study_run_id` under
  `governance`.
- Dashboard catalogs propagate the network model version from base metadata
  when a network repository is available.

### Phase 2: Digital Twin Core As Product Backbone

**Goal:** make the digital twin the reusable model service boundary, even while
it remains local Parquet/JSON.

**Implement:**

- `NetworkModelRepository` snapshot metadata API;
- query methods by feeder, transformer, bus, downstream zone, and asset type;
- explicit operational states: `base`, `normal`, `current`, `planned`,
  `study_case`;
- `NetworkModel` export/import contract shared by all adapters;
- adapter validation summaries exposed in a common format.

**Update current artifacts:**

- `instances/default/digital_twin/base`;
- `instances/default/digital_twin/scenarios`;
- `instances/default/digital_twin/semantic`;
- `instances/default/digital_twin/dashboard/catalog.json`.

**Tests:**

- no orphan loads;
- all edge endpoints exist;
- scenarios reference known assets;
- adapter registry resolves all declared adapters;
- dashboard catalog can load from digital twin metadata without project-specific
  assumptions.

### Phase 2B: Operations Facades

**Goal:** expose utility-facing services that combine digital twin state,
network-impact analytics, and market mechanics behind stable contracts.

**Implement:**

- `FlexibilityOperationContext` with deterministic operation IDs, scenario,
  clearing method, model version, study run, market role, and ontology profile;
- input validation for provider registry, constraint requirements, and
  method-specific impact tables;
- `run_flexibility_clearing_operation` as the first operational facade;
- report enrichment with operation context, governance IDs, validation, and
  input summary.

**Status:**

- `gridalyn.operations` provides the first validated operation
  facade.
- `gridalyn.operations` exports the flexibility operation facade for
  applications and future service APIs; `foundation` remains focused on
  governance, reports, workspace, and artifact contracts.
- Existing `gridalyn.operations.clearing` remains the clearing engine;
  the operation layer wraps it with governance and validation.
- The same layer now exposes `AggregatorPortfolio`, `FlexibilityOffer`,
  `DispatchInstruction`, and `SettlementRecord` tabular contracts.
- It also exposes `NetworkConstraint` normalization and
  `build_operational_kpi_report` generation for mechanism-intelligence metrics.

### Phase 3: Asset And Flexibility Modeling Contracts

**Goal:** separate asset behavior from market logic and simulation execution.

**Implement:**

- documented model assumptions and validation signals for controllable assets;
- `BuildingFlexibilityModel`;
- `EVChargingModel`;
- `ThermalLimitModel`;
- `FlexibilityEnvelope`;
- mapping from `asset_registry.parquet` to controllable asset models.

**Current EV mapping:**

- building Soft CLS becomes a building flexibility model with action bounds;
- EV Hard CLS becomes an EV charging model with interruption or limiting
  actions;
- transformer dynamic limit becomes a thermal constraint model.

**Tests:**

- every controllable asset has state and action definitions;
- Soft CLS actions cannot exceed declared envelopes;
- Hard CLS actions cannot exceed EV availability;
- units are explicit for power, energy, time, and price.

### Phase 4: Simulation And Validation Environment

**Goal:** let market and experiments call physical validation through a stable
environment interface.

**Implement:**

- `GridEnvironment` interface with `reset`, `step`, `evaluate`, and `close`;
- `PandapowerGridEnvironment`;
- `NetworkImpactSurrogateEnvironment`;
- comparison report between surrogate predictions and pandapower validation;
- scenario replay API for project workflows.

**Use in flexibility demos:**

- day-ahead and realtime dispatch produce actions;
- environment evaluates voltage, line loading, transformer loading, overloads,
  and unmet relief;
- reports store both fast-screening and physical-validation metrics.

**Tests:**

- same scenario can run through surrogate and pandapower environments;
- environment output schema is stable;
- known S4 regression metrics remain within baseline;
- physical validation failures are reported, not swallowed.

### Phase 5: Flexibility Market And Operations

**Goal:** make provider selection graph-aware and operationally measurable.

**Implement:**

- `FlexibilityProvider` and `Aggregator` domain contracts;
- portfolio membership edges between aggregators, buildings, EVSEs, and
  contracts;
- `Offer`, `Bid`, `ClearingResult`, `DispatchInstruction`, `Settlement`;
- locational constraint model with impacted transformer/feeder/bus;
- operational KPI report for mechanism intelligence.

**Required KPIs:**

- delivered MWh;
- shortage MWh;
- congestion relief in percentage points;
- voltage improvement;
- transformer overload reduction;
- rebound MWh;
- settlement cost;
- cost per MWh delivered;
- cost per overload percentage-point relieved;
- number of selected providers;
- geographic/topological concentration of selected portfolios;
- surrogate-vs-physics error.

**Tests:**

- aggregators cannot clear assets outside their declared portfolio;
- selected assets map to known buses/transformers;
- clearing can be filtered by locational constraint;
- settlement references dispatched assets and delivered energy;
- KPI report changes by scenario and constraint.

### Phase 6: Problems And Experiments

**Goal:** package studies as reproducible problem definitions rather than
one-off pipelines.

**Implement:**

- `Problem` contract: dataset, environment, objective, model, and scenarios;
- `Experiment` contract: scenario references, model, metrics, proof artifacts,
  parameters, and run manifest;
- `Objective` classes for overload reduction, cost minimization, voltage margin,
  hosting capacity, and reliability;
- sweep definitions for scenarios, models, datasets, and objectives;
- benchmark reports comparing clearing strategies and validation methods.

**First problem:**

```text
EVCapacityLimitationProblem
  dataset: digital twin + project outputs
  environment: GridEnvironment
  objective: reduce overload and shortage at minimum cost
  model: locational CLS flexibility clearing
  scenarios: S0_0pct, S1_10pct, S2_20pct, S3_30pct, S4_40pct
  metrics: overload reduction, shortage, settlement cost, delivery risk
  artifacts: reports, KPIs, figures, dashboard metrics
```

Explicit state/action/input/output spaces remain a later abstraction. The
public v0.1 contract should stay lighter: problem, model, scenarios,
experiments, metrics, and artifacts.

**Tests:**

- flexibility workflows can be represented as `Problem` objects;
- regression command can read the experiment output;
- a minimal tutorial problem runs without full EV data;
- benchmark report compares at least two strategies.

### Phase 7: Applications And Utility PoC

**Goal:** expose the platform as something a utility user can understand without
reading study scripts.

**Implement:**

- dashboard Network Explorer with feeder/transformer search;
- Operations panel for constraints, providers, aggregators, dispatch, and KPIs;
- CLI commands aligned to capability layers:
  - `gridalyn twin ...`;
  - `gridalyn model ...`;
  - `gridalyn simulate ...`;
  - `gridalyn market ...`;
  - `gridalyn experiment ...`;
  - `gridalyn platform ...`;
- report catalog API for applications;
- optional service wrapper around repository and reports.

**Tests:**

- dashboard catalog loads with only digital twin artifacts;
- operations panels load only when market manifests exist;
- CLI help groups commands by capability;
- utility PoC can show model, constraint, dispatch, validation, and KPI lineage.

## Priority Roadmap

| Priority | Capability | Concrete next deliverable | Why now |
| --- | --- | --- | --- |
| P0 | Foundation And Governance | ModelVersion and StudyRun contracts in manifests | Every later layer needs traceability. |
| P1 | Digital Twin Core | Operational state and snapshot metadata API | Utility PoC needs model state, not only files. |
| P2 | Flexibility Market And Operations | DispatchDeliveryRecord and dashboard-ready operations catalog on top of constraint/KPI contracts | Market logic is the main differentiator. |
| P3 | Simulation And Validation | GridEnvironment interface with pandapower and surrogate backends | Clearing must be validated without coupling to one script. |
| P4 | Asset And Flexibility Modeling | Space contracts and flexibility envelopes | Assets need explicit actions and limits. |
| P5 | Problems And Experiments | EVCapacityLimitationProblem and Experiment manifest | Converts the study into a reusable benchmark. |
| P6 | Applications And Interfaces | Network/Operations dashboard panels and capability CLI groups | Makes the platform usable by non-authors. |
| P7 | Utility Data Expansion | GIS/AMI/SCADA adapter skeletons and model service prototype | Starts the transition from synthetic study to utility PoC. |

## Current Status By Capability

| Capability | Current status | Main gap |
| --- | --- | --- |
| Foundation And Governance | Project manifests, artifact checks, report schemas, regression baseline. | First-class model/run contracts across every report. |
| Digital Twin Core | Repository, base Parquet, semantic graph, adapter registry, synthetic and CIM-like adapters. | Explicit operational states and richer partial model access. |
| Asset And Flexibility Modeling | Building models, EV scenario overlays, thermal forecast, asset registry. | Clear model assumptions and flexibility envelopes. |
| Simulation And Validation | Pandapower validation, network impact surrogate, consistency reports. | Common environment interface. |
| Flexibility Market And Operations | Provider registry, locational clearing, operations facade, aggregator portfolios, offers, dispatch, settlement, network constraints, and operational KPIs. | Measured delivery records and dashboard-ready operations catalog. |
| Problems And Experiments | Governed project workflows and regression. | Reusable `Problem` and `Experiment` abstractions. |
| Applications And Interfaces | CLI, dashboard catalog, docs. | Utility-facing Network/Operations views. |

## Runtime Boundary Policy

Active implementation lives in:

- `gridalyn` for reusable platform logic;
- `projects/ev_hosting_flex` for executable study workflows;
- optional publication or presentation material outside executable platform
  workflows.

New code must not write study outputs outside the governed project artifact
roots.

## Do Not Break

The migration must preserve:

- `uv run gridalyn twin build --dry-run --skip-heavy`;
- `uv run gridalyn twin building-models`;
- `uv run gridalyn twin scenario-models`;
- `uv run gridalyn market providers`;
- `uv run gridalyn semantic build`;
- `uv run gridalyn semantic validate`;
- `uv run --with pytest python -m pytest -q`;
- `uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml`;
- public demo project workflows and their canonical reports.

## Near-Term Execution Order

1. Keep hygiene tests that protect imports into `gridalyn`.
2. Keep digital-twin build logic in `gridalyn/twin` and project workflow
   orchestration in `gridalyn/projects/workflows`.
3. Continue hardening provider, clearing, and network impact modules in
   `gridalyn.operations` and `gridalyn.simulation.analytics`.
4. Move canonical report schemas into `gridalyn.interfaces.reporting`.
5. Keep study pipeline scripts under `projects/ev_hosting_flex`.
6. Keep publication-only notes and illustrative plots outside executable
   workflows.
7. Keep generated project outputs under `projects/ev_hosting_flex/outputs`.
8. Continue hardening the `gridalyn.twin` repository with Parquet backend.
9. Refactor digital twin scripts to consume `NetworkModelRepository`.
10. Promote dashboard to Network Explorer semantics.

## Success Definition

The platform is viable when a developer can:

1. generate or import a network model;
2. validate it;
3. query it by topology;
4. create a study project;
5. generate scenarios;
6. run simulations;
7. run analytics;
8. publish reports and dashboard artifacts;
9. trace every result to model version, scenario, inputs, and validation status;
10. do all of the above through the canonical Gridalyn modules and project
    contracts.

# What Is Gridalyn?

Gridalyn is an open-source Python SDK for studies of electric distribution
grids and the distributed energy resources on them: flexible building loads,
EV chargers and storage. It is built for researchers who need reproducible,
citable results.

A **study** is the research unit, and its **project** is the study's on-disk
contract: a `project.yaml` (kind `StudyProject`) that declares inputs,
scenarios and metrics, and a `workflow.yaml` (kind `Workflow`) that names the
stages computing them. The study is data, not code. Re-running the two files
reproduces the numbers, and `gridalyn project regression` checks them against
the baseline the study commits.

## What it does

Each capability lives in one layer of the SDK; the seven layers are walked in
order in [Components](../components/overview.md).

- **Synthetic data generation**: residential load profiles (space heating plus
  background load), weather, EV and thermal models, deterministic for a
  declared seed. See [Assets](../components/assets.md).
- **A canonical network model**: topology, ingest adapters (GeoJSON, CIM as
  Parquet), a declared column schema, a stamped model identity, and a semantic
  graph describing it. See [Twin](../components/twin.md) and the
  `synthetic_geojson_feeder` study.
- **Power flow**: pandapower or LightSim2Grid, selected through a backend
  registry, surrogates that state their own error bound, and control
  environments for learning agents. See
  [Simulation](../components/simulation.md) and the `ieee_33_bus_demo` and
  `rl_voltage_control_lightsim` studies.
- **Flexibility operations**: locational clearing, dispatch, settlement and
  KPIs, and voltage-constrained DER dispatch. See
  [Operations](../components/operations.md) and the `prosumer_battery_market`
  and `der_voltage_optimization` studies.
- **Agent interaction**: roles, messages and two protocols (`flex_trading`
  and the OpenADR 3.1.0 `dr_program`) exchanged over simulated communication
  channels with latency, loss and outages. See
  [Operations](../components/operations.md) and the `dr_agent_interaction`
  and `flex_trading_congestion` studies.
- **Measured-state ingest**: the one-way path from measured data into the
  network model. See [Twin](../components/twin.md) and the
  `measured_shadow_feeder` study.
- **Governed outputs**: every artifact-producing stage writes a platform
  report, and a headline number can carry an `uncertainty` block stating its
  method, sample size and interval. See
  [Report And Run-Manifest Schema](../reference/report-schema.md).
- **Execution and checks**: a runner that executes the stage DAG and records a
  run manifest with seeds, library versions and input hashes, plus sense
  checks and baseline regression. See [Projects](../components/projects.md)
  and the `minimal_grid_project` study.

Every study named here is listed, with its tier, on
[The Studies](studies.md).

## Who it is for

Researchers who need a study that survives re-running: a load generator
validated against real data, the seed written down, and the pinned numbers
checked on every change. Contributors extending the SDK start from the same
[Components](../components/overview.md) walk, then
[Contributing](../contributing/overview.md).

## Scope of v0.1

Gridalyn v0.1 is a network-model platform seed for research:

- synthetic data first;
- model-centric rather than script-centric;
- a North America semantic profile;
- project-governed workflows with canonical Parquet and JSON artifacts;
- import and export adapter contracts ready for richer utility data sources;
- a dashboard that reads generated catalogs and reports.

### What it does not claim

**It is not a digital twin.** `gridalyn.twin` is a canonical, identified,
schema-declared digital model with a one-way, automated measured-state ingest
path. A deployment becomes a digital shadow when its operator feeds that path
real measured data; the SDK on its own is not one, because every producer it
exercises in CI is simulated or a fixture. Bidirectional flow, digital to
physical, is a non-goal, so treat "digital twin" in package and directory
names as a target. [Twin](../components/twin.md#what-problem-this-layer-solves)
gives the full statement; the at-scale proof of the measured path is an
operator-receipted protocol (see
[Operator Verification](../contributing/verification.md)).

**Out of scope:**

| Area | Why |
| --- | --- |
| Certified utility operations | Not certified for operational switching, planning approval, protection studies or regulatory reporting. |
| Full CIM service | The CIM path is a Parquet adapter contract, not a complete CIM RDF or service implementation. |
| Live utility integrations | GIS, AMI, SCADA, OMS, DERMS and market integrations are adapter targets, not shipped integrations. |
| Managed model server | The model repository is a local library; a hosted service can be built on top. |
| Full dashboard product | The dashboard is an artifact viewer and network-model explorer, not an operator console. |
| Publication workspace | Papers, presentations and compiled documents are outside the platform. |

Validate any operational decision support with utility-grade data, engineering
review and the applicable grid codes.

Next: [Installation](installation.md)

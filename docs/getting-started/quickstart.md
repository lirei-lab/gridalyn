# Quickstart

This page is the shortest path from a fresh checkout to a verified platform
workspace, reproducible demo workflows, dashboard-ready artifacts, and a
working documentation build.

## 1. Install Python Dependencies

From the repository root:

```bash
uv sync --extra dev
```

For library-only use, `uv sync` is enough. The `dev` extra installs the docs
and test tools used later in this guide.

If the environment is already created, verify that the CLI is available:

```bash
uv run gridalyn --help
```

Check the repository artifact policy:

```bash
uv run gridalyn validate
```

Expected result: `"valid": true`. This checks repository artifact policy and
project contracts. If the command reports tracked generated
artifacts, read [Artifact Policy](../development/artifact-policy.md) before
adding files to Git.

## 2. Run the Minimal Grid Project

The smallest complete project is:

```text
projects/minimal_grid_project/
  project.yaml
  workflow.yaml
  scripts/
  outputs/
```

Run it:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

Expected outcome: a five-bus feeder, one AC power-flow run, CSV tables, one
JSON report, one voltage-profile figure, and a run manifest. More detail is in
[Minimal Grid Project](../projects/minimal-grid-project.md).

## 3. Run the Small IEEE Demo

The smallest benchmark-feeder project is:

```text
projects/ieee_33_bus_demo/
  project.yaml
  workflow.yaml
  scripts/
  outputs/
```

Run it:

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
```

Check generated artifacts:

```bash
uv run gridalyn project status projects/ieee_33_bus_demo --check-artifacts
```

Expected outcome: the project is valid, the pandapower power flow converges,
the JSON reports exist, and the voltage profile and scenario comparison figures
are generated. The demo includes baseline, load growth, PV, EV peak, and mixed
PV+EV scenarios.

More detail is in [IEEE 33-Bus Demo](../projects/ieee-33-demo.md).

## 4. Run The Synthetic GeoJSON Feeder

Run the compact geospatial network-generation demo:

```bash
uv run gridalyn project run projects/synthetic_geojson_feeder
uv run gridalyn project status projects/synthetic_geojson_feeder --check-artifacts
```

Expected outcome: generated building-footprint GeoJSON, a synthetic LV/MV/HV
feeder, pandapower tables, a network validation report, a platform report, a
topology figure, and a run manifest. More detail is in
[Synthetic GeoJSON Feeder](../projects/synthetic-geojson-feeder.md).

## 5. Run The Prosumer Market Demo

Run the compact operations demo:

```bash
uv run gridalyn project run projects/prosumer_battery_market
uv run gridalyn project status projects/prosumer_battery_market --check-artifacts
```

Expected outcome: a 14-bus synthetic feeder, five PV+battery prosumers, a
12-interval real-time market, dispatch records, post-market power-flow results,
two JSON reports, and two figures. More detail is in
[Prosumer Battery Market Demo](../projects/prosumer-battery-market.md).

## 6. Run The DER Optimization Demo

Run the compact optimization demo:

```bash
uv run gridalyn project run projects/der_voltage_optimization
uv run gridalyn project status projects/der_voltage_optimization --check-artifacts
```

Expected outcome: a 16-bus synthetic feeder, finite-difference voltage
sensitivities, a `cvxpy` DER dispatch, pandapower AC verification, two JSON
reports, and two figures. More detail is in
[DER Voltage Optimization Demo](../projects/der-voltage-optimization.md).

## 7. Run The RL Voltage-Control Demo

Run the compact learning-control demo:

```bash
uv run gridalyn project run projects/rl_voltage_control_lightsim
uv run gridalyn project status projects/rl_voltage_control_lightsim --check-artifacts
```

Expected outcome: a 10-bus synthetic feeder, a LightSim2Grid simulator,
90-episode Q-learning, a learned policy table, a Q-table, a 24-step evaluation
trajectory, reports, and figures. More detail is in
[RL Voltage Control With LightSim2Grid](../projects/rl-voltage-control-lightsim.md).

## 8. Inspect the Larger Flexibility Workflow

The larger executable workflow is:

```text
projects/flexibility_cls/
  project.yaml
  workflow.yaml
  scripts/
  outputs/
```

Validate its project contract:

```bash
uv run gridalyn project validate projects/flexibility_cls
```

Print the execution plan:

```bash
uv run gridalyn project plan projects/flexibility_cls
```

For a stricter check that also verifies declared output artifacts, run:

```bash
uv run gridalyn validate --check-project-artifacts
```

## 9. Run the Flexibility CLS Workflow

Run all stages when you need to regenerate outputs:

```bash
uv run gridalyn project run projects/flexibility_cls
```

Check the workflow state and required reports:

```bash
uv run gridalyn project status projects/flexibility_cls --check-artifacts
```

Expected high-level outcome:

- project contract valid;
- 24 workflow stages available;
- required reports found;
- required reports valid;
- required figures found.

The full workflow regenerates stochastic profiles, network validation,
figures, operational artifacts, and canonical reports. On a typical developer
machine it is a minutes-scale command, not an instant smoke test.

More detail is in [Run Demo Projects](run-ev-project.md).

If generated outputs already exist and you only need a fast numerical check,
run:

```bash
uv run gridalyn project regression projects/flexibility_cls
```

## 10. Regenerate Core Report Layers

Project reports:

```bash
uv run python projects/flexibility_cls/scripts/reports/build_study_reports.py
```

Digital twin reports:

```bash
uv run python -m gridalyn.interfaces.reporting.digital_twin
```

Output consistency check:

```bash
uv run python projects/flexibility_cls/scripts/pipeline/verify_output_consistency.py
```

## 11. Build Semantic Graph Artifacts

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir digital_twin/base \
  --scenario-dir digital_twin/scenarios \
  --flexibility-dir digital_twin/flexibility \
  --timeseries-dir digital_twin/timeseries \
  --out-dir digital_twin/semantic
```

Validate the graph:

```bash
uv run gridalyn semantic validate \
  --semantic-dir digital_twin/semantic
```

## 12. Run the Dashboard

Install and build the frontend:

```bash
npm install --prefix dashboard
npm --prefix dashboard run build
```

Deploy with Compose:

```bash
docker compose -f dashboard/docker-compose.yml up -d --build dashboard
```

Open:

```text
http://localhost:8081/
```

Dashboard details are in [Dashboard](../platform/dashboard.md).

## 13. Build the Documentation

```bash
uv run --extra docs mkdocs serve -f docs/mkdocs.yml
```

Strict static build:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

The generated HTML goes to `site/` and should not be committed.

## Next Step

Use [Documentation Map](documentation-map.md) to choose the next page based on
whether you are reproducing, developing, or preparing a release.

# Quickstart

This page is the shortest path from a fresh checkout to a verified Gridalyn
platform workspace. It focuses on the platform contract first: CLI, artifact
policy, one small governed project, optional operations workflow, dashboard
readiness, and documentation.

Demo projects are executable checks for that contract. They are not the
platform identity; the reusable platform lives in the `gridalyn` SDK, canonical
artifact layout, CLI, reports, and validation rules.

## 1. Install The Workspace

From the repository root:

```bash
uv sync --extra dev
```

For library-only use, `uv sync` is enough. The `dev` extra installs the docs
and test tools used later in this guide.

Verify that the CLI is available:

```bash
uv run gridalyn --help
```

Check repository policy and project contracts:

```bash
uv run gridalyn validate
```

Expected result: `"valid": true`. If the command reports tracked generated
artifacts, read [Artifact Policy](../development/artifact-policy.md) before
adding files to Git.

## 2. Run A Minimal Governed Project

The smallest complete project contract is:

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
uv run gridalyn project verify projects/minimal_grid_project
```

This proves the basic platform loop:

```text
project contract -> workflow stages -> generated artifacts -> reports -> sense checks
```

Expected outcome: a five-bus feeder, one AC power-flow run, CSV tables, one
JSON report, one voltage-profile figure, a run manifest, and a passing
project-level verification.

More detail is in [Minimal Grid Project](../projects/minimal-grid-project.md).

## 3. Inspect The Platform Surfaces

After the minimal project passes, inspect the reusable surfaces instead of
jumping straight into a large demo:

| Surface | What to check |
| --- | --- |
| [Platform Overview](../platform/overview.md) | Platform layers, source-of-truth rule, stable and transitional surfaces. |
| [Platform Layer Model](../platform/platform-layer-model.md) | Responsibility boundaries between foundation, twin, assets, simulation, operations, projects, and interfaces. |
| [Python SDK Overview](../sdk/overview.md) | The seven public SDK areas under `gridalyn`. |
| [Project Model](../projects/project-model.md) | The reusable `project.yaml` and `workflow.yaml` contract. |
| [Testing And Validation](../development/testing-and-validation.md) | Which checks to run for docs, projects, SDK changes, and release readiness. |

Use [Documentation Map](documentation-map.md) when you are unsure where to go
next.

## 4. Choose One Additional Verification Path

Pick one path based on what you need to prove:

| Goal | Command | Read next |
| --- | --- | --- |
| Benchmark feeder smoke test | `uv run gridalyn project verify projects/ieee_33_bus_demo` | [IEEE 33-Bus Demo](../projects/ieee-33-demo.md) |
| Geospatial model generation | `uv run gridalyn project verify projects/synthetic_geojson_feeder` | [Synthetic GeoJSON Feeder](../projects/synthetic-geojson-feeder.md) |
| Compact market operation | `uv run gridalyn project verify projects/prosumer_battery_market` | [Prosumer Battery Market Demo](../projects/prosumer-battery-market.md) |
| Optimization and physical verification | `uv run gridalyn project verify projects/der_voltage_optimization` | [DER Voltage Optimization Demo](../projects/der-voltage-optimization.md) |
| Learning-control environment | `uv run gridalyn project verify projects/rl_voltage_control_lightsim` | [RL Voltage Control With LightSim2Grid](../projects/rl-voltage-control-lightsim.md) |
| Larger operations workflow | `uv run gridalyn project verify projects/flexibility_cls` | [Run Demo Projects](run-ev-project.md) |

The larger Flexibility CLS workflow is useful as an end-to-end stress test for
operations, clearing, dispatch, settlement, reports, and figures. Run it when
you need the full operations stack, not as the first proof that Gridalyn works.

## 5. Validate Code And Documentation

Run the Python test suite:

```bash
uv run --with pytest python -m pytest -q
```

Build the documentation strictly:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

The generated HTML goes to `site/` and should not be committed.

## 6. Optional Application Surfaces

Build the semantic graph when you need ontology-aligned artifacts:

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir digital_twin/base \
  --scenario-dir digital_twin/scenarios \
  --flexibility-dir digital_twin/flexibility \
  --timeseries-dir digital_twin/timeseries \
  --out-dir digital_twin/semantic

uv run gridalyn semantic validate \
  --semantic-dir digital_twin/semantic
```

Build the dashboard only after the data contracts are valid:

```bash
npm install --prefix dashboard
npm --prefix dashboard run build
docker compose -f dashboard/docker-compose.yml up -d --build dashboard
```

Open:

```text
http://localhost:8081/
```

Dashboard details are in [Dashboard](../platform/dashboard.md).

## Next Step

Use [First Hour With Gridalyn](first-hour.md) for a guided platform reading
path, or [Run Demo Projects](run-ev-project.md) when your goal is specifically
to compare executable examples.

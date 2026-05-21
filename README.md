# Gridalyn

**A utility digital-twin platform for distribution networks, governed
scenario workflows, flexibility-market analysis, semantic graph exports, and
traceable reports.**

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)

Gridalyn is built for two audiences at once:

- researchers who need reproducible synthetic-grid studies; and
- utility-platform developers who need a clean core that can later ingest real
  GIS, CIM, AMI, SCADA, DER, and flexibility-market data.

The current release keeps synthetic data first, but the architecture is
model-centric: adapters produce canonical network snapshots, project workflows
produce governed artifacts, and dashboards or reports consume those artifacts
instead of ad hoc scripts.

The canonical Python command-line entrypoint and SDK namespace are `gridalyn`.

## Public Surface In V0.1

The initial viable release focuses on a compact, publishable core:

- `gridalyn/`: canonical reusable Python SDK package for applications,
  notebooks, project workflows, and utility-facing services;
- `projects/`: executable demos and study workflows using one governed project
  contract;
- `instances/default/digital_twin/`: the default materialized twin instance
  with canonical Parquet and JSON contracts for base topology, scenarios,
  timeseries, flexibility, semantic graph, reports, and dashboard catalog
  metadata;
- `dashboard/`: browser application that consumes generated catalog and report
  artifacts;
- `examples/tutorials/data/minimal/`: a tiny tracked demo dataset for smoke
  tests and tutorials.

No single demo is the identity of the platform. New studies should reuse
`gridalyn` modules and follow the same project contract rather than copying
workflow scripts.

## Architecture At A Glance

```text
gridalyn/      canonical SDK package and import namespace
  foundation/   governance, reports, artifact policy, datasets, workspace paths
  twin/         network repository, adapters, graph/database, semantic exports
  assets/       building, DER, EVSE, load, forecast, and asset model synthesis
  simulation/   synthetic-network builders, pandapower, LightSim2Grid, network impact
  operations/   flexibility providers, markets, dispatch, settlement, KPIs
  projects/     governed project manifests, workflow execution, sense checks
  interfaces/   stable CLI, reporting, dashboard/catalog, visualization surfaces

projects/
  minimal_grid_project/
  ieee_33_bus_demo/
  synthetic_geojson_feeder/
  prosumer_battery_market/
  der_voltage_optimization/
  rl_voltage_control_lightsim/
  flexibility_cls/
    project.yaml
    workflow.yaml
    scripts/
    outputs/

instances/
  default/
    digital_twin/
      base/
      scenarios/
      timeseries/
      flexibility/
      semantic/
      reports/
      dashboard/
```

## Install

Prerequisites:

- Python 3.12 or newer;
- [`uv`](https://github.com/astral-sh/uv);
- Node.js 20+ if you want to build the dashboard;
- Docker Compose if you want local container deployment.

From the repository root:

```bash
uv sync --extra dev
uv run gridalyn --help
```

For a lighter library-only install, use `uv sync`. Optional capability groups
keep heavier integrations out of the smallest install:

```bash
uv sync --extra geo        # GeoJSON, OSM, geospatial preprocessing
uv sync --extra sim        # pandapower and LightSim2Grid simulation helpers
uv sync --extra ops        # optimization and operational analytics
uv sync --extra semantic   # RDF/graph database tooling
uv sync --extra dashboard  # dashboard and visualization helpers
uv sync --extra all        # full platform runtime
```

The `dev` extra installs the full runtime plus documentation and test tools
used by repository checks.

Synthetic load and weather generation helpers are included for reproducible
public studies. They are documented under `docs/sdk/data-generation.md`; treat
them as synthetic baselines unless a project explicitly documents calibration.

## Quickstart

Run the workspace validation:

```bash
uv run gridalyn doctor
uv run gridalyn validate
```

Inspect and run the smallest demo project:

```bash
uv run gridalyn project list
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
uv run gridalyn project plan projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project verify-all
```

Run a larger flexibility operations demo when you need the full stack:

```bash
uv run gridalyn project run projects/flexibility_cls
uv run gridalyn project verify projects/flexibility_cls
```

Build documentation:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

## Core CLIs

```bash
uv run gridalyn --help
uv run gridalyn twin --help
uv run gridalyn project --help
uv run gridalyn market --help
uv run gridalyn semantic --help
uv run gridalyn dashboard --help
uv run gridalyn platform --help
```

Domain-specific entrypoints are also installed for script-friendly usage:

```bash
uv run gridalyn-dt --help
uv run gridalyn-flex --help
uv run gridalyn-semantic --help
uv run gridalyn-dashboard --help
uv run gridalyn-platform --help
```

## Documentation

Serve the docs locally:

```bash
uv run --extra docs mkdocs serve -f docs/mkdocs.yml
```

Then open:

```text
http://127.0.0.1:8000/
```

The recommended reading path is:

1. `docs/getting-started/documentation-map.md`
2. `docs/getting-started/what-is-gridalyn.md`
3. `docs/getting-started/installation.md`
4. `docs/getting-started/quickstart.md`
5. `docs/platform/overview.md`
6. `docs/platform/capability-architecture.md`
7. `docs/projects/project-model.md`
8. `docs/sdk/overview.md`
9. `docs/platform/release-readiness.md`

## Release Checks

Before publishing a release candidate, run:

```bash
uv run --with pytest python -m pytest -q
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
uv run gridalyn validate --check-project-artifacts
uv run gridalyn project verify-all
uv run gridalyn project regression projects/flexibility_cls
node --test dashboard/src/*.test.js
(cd dashboard && npm run build)
```

These checks cover unit tests, documentation, tracked-artifact hygiene, and the
project verification/regression baseline plus dashboard health.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Disclaimer

Gridalyn can generate and analyze realistic synthetic power-grid scenarios, but
it is not yet certified operational utility software. Treat v0.1 as a research
and platform-development release. Validate any operational decision support
with utility-grade data, engineering review, and the applicable grid codes.

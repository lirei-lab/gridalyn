# What Is Gridalyn?

Gridalyn is a platform for distribution-grid digital twins, simulation-backed
studies, and flexibility operations. It is designed to support reproducible
research today while keeping the core close to the shape of a utility platform:
model-centric, traceable, adapter-driven, and ready for operational
applications.

## What It Does

Gridalyn provides:

| Capability | Description |
| --- | --- |
| Digital twin core | Canonical grid, building, scenario, time-series, semantic, and report artifacts. |
| Project workflows | Reproducible project contracts with `project.yaml`, `workflow.yaml`, scripts, outputs, manifests, and regression checks. |
| Synthetic model generation | GeoJSON and configuration-driven synthetic network and building model generation. |
| Simulation and validation | Powerflow and network-impact validation using generated or imported model snapshots. |
| Flexibility operations | Provider registry, aggregators, locational clearing, dispatch, settlement, and operational KPIs. |
| Semantic graph | North America-first ontology mapping for grid, buildings, EV/DER assets, telemetry, scenarios, and flexibility contracts. |
| Dashboard integration | Catalog and report artifacts that allow a general grid dashboard to load scenarios programmatically. |

## What It Is Not

Gridalyn is not a single study or study-specific workflow. The public project
folder contains several demos with different levels of complexity, but the
platform boundary is broader than any one demo:

- reusable logic belongs in the Gridalyn SDK;
- executable studies belong in `projects/<name>/`;
- canonical twin artifacts belong in `instances/default/digital_twin/`;
- project-specific generated artifacts belong in project `outputs/`;
- dashboards and reports consume explicit artifacts, not study-specific hidden
  assumptions.

## Public Interfaces

The platform name is Gridalyn. The public interfaces are:

- `gridalyn` as the command-line entrypoint;
- `gridalyn` as the Python SDK namespace;
- `lirei-uqtr/gridalyn` as the public repository name.

## Recommended Reading Order

1. [Installation](installation.md)
2. [Quickstart](quickstart.md)
3. [Run Demo Projects](run-ev-project.md)
4. [Capability Architecture](../platform/capability-architecture.md)
5. [Projects and Workflows](../platform/projects-and-workflows.md)
6. [Digital Twin Data](../platform/digital-twin.md)
7. [CLI Reference](../reference/cli.md)

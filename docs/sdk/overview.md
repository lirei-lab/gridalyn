# Python SDK Overview

The canonical Python SDK namespace is `gridalyn`. It is the reusable core used
by project workflows, command-line tools, reports, semantic graph builders,
market operations, and future applications. New applications should import from
`gridalyn` directly.

## Main Modules

Gridalyn is physically organized into seven platform modules:
`foundation`, `twin`, `assets`, `simulation`, `operations`, `projects`, and
`interfaces`.

| Module | Role |
| --- | --- |
| `gridalyn.foundation` | Governance, validation, artifact policy, manifests, report metadata, lightweight dataset discovery. |
| `gridalyn.twin` | Network repository, topology, source adapters, import/export helpers, semantic graph, graph adapters. |
| `gridalyn.assets` | Building, EVSE, DER, thermal, load, forecast, and synthetic asset model generation. |
| `gridalyn.simulation` | Synthetic-network construction, powerflow, simulation engines, network impact, thermal and voltage validation, surrogate-ready analytics. |
| `gridalyn.operations` | Providers, aggregators, clearing, dispatch, settlement, constraints, and KPIs. |
| `gridalyn.projects` | Project manifest and workflow execution contracts. |
| `gridalyn.interfaces` | Command-line entrypoints, reports, dashboard/catalog helpers, visualization, graph-facing adapters. |

## Canonical Usage

```python
from gridalyn import twin, operations

repository = twin.NetworkModelRepository("instances/default/digital_twin/base")
clearing = operations.build_locational_clearing(...)
```

## Import Rule

Prefer documented public imports from the seven platform modules and the pages
in this SDK section. If two project workflows need the same behavior, move that
behavior into the Gridalyn SDK and keep project scripts as orchestration.

For the stable import list and output conventions, read
[SDK Public Contract](public-contract.md).

For synthetic load, weather, and aggregate MV-network generation, read
[Data Generation](data-generation.md). That layer is reproducible and useful
for demos, but its lower-level `gridalyn.assets.datagen` helpers should be
treated as synthetic baselines unless a project documents calibration.

For workspace paths, prefer `GridalynWorkspace` and `ArtifactLayout` from
`gridalyn.foundation` instead of constructing `instances/default/digital_twin/*` paths manually.

## Command Rule

The current user-facing command is:

```bash
uv run gridalyn --help
```

Documentation, projects, and automation should use `gridalyn`.

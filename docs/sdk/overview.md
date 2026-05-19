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
| `gridalyn.simulation` | Powerflow, simulation engines, network impact, thermal and voltage validation, surrogate-ready analytics. |
| `gridalyn.operations` | Providers, aggregators, clearing, dispatch, settlement, constraints, and KPIs. |
| `gridalyn.projects` | Project manifest and workflow execution contracts. |
| `gridalyn.interfaces` | Command-line entrypoints, reports, dashboard/catalog helpers, visualization, graph-facing adapters. |

## Compatibility Alias Map

Older project scripts may still import the historical narrow modules. They are
kept as compatibility aliases, but new code should prefer the seven-module
surface above.

| Platform area | Historical compatibility aliases | Meaning |
| --- | --- | --- |
| Foundation | `gridalyn.platform`, `gridalyn.reporting` | Trust, validation, manifests, run metadata, report metadata. |
| Twin | `gridalyn.network`, `gridalyn.adapters`, `gridalyn.io`, `gridalyn.semantic` | Canonical distribution model, source adapters, topology, and ontology-aligned graph. |
| Assets | `gridalyn.modeling`, `gridalyn.datagen` | Building, load, EV, DER, forecast, and flexibility model generation. |
| Simulation | `gridalyn.simulators`, `gridalyn.analytics` | Powerflow, network impact, thermal and voltage validation, surrogate-ready analytics. |
| Operations | `gridalyn.operations`, `gridalyn.market` | Providers, aggregators, clearing, dispatch, settlement, constraints, and KPIs. |
| Projects | `gridalyn.projects`, `gridalyn.workflows` | Reproducible project manifests, workflow stages, regressions, and demos. |
| Interfaces | `gridalyn.interfaces.cli`, dashboard/report/catalog helpers | Human and system entrypoints over stable artifacts and APIs. |

The grouping gives contributors a clear home for new functionality while
preserving old scripts during the migration.

```python
from gridalyn import twin, operations

repository = twin.NetworkModelRepository("digital_twin/base")
clearing = operations.build_locational_clearing(...)
```

## Import Rule

Prefer documented public imports from the seven platform modules and the pages
in this SDK section. If two project workflows need the same behavior, move that
behavior into the Gridalyn SDK and keep project scripts as orchestration.

For the stable import list and output conventions, read
[SDK Public Contract](public-contract.md).

Compatibility aliases are registered by `gridalyn` so old import paths continue
to work during the transition. New code should prefer the seven-module
vocabulary unless a narrower compatibility path is clearer.

For workspace paths, prefer `GridalynWorkspace` and `ArtifactLayout` from
`gridalyn.foundation` instead of constructing `digital_twin/*` paths manually.

## Command Rule

The current user-facing command is:

```bash
uv run gridalyn --help
```

Documentation, projects, and automation should use `gridalyn`.

# Documentation Map

Use this page when you are unsure where to go next. Gridalyn documentation is
organized around platform surfaces and user roles rather than repository
folders.

## Fast Paths

| Goal | Start here | Then read |
| --- | --- | --- |
| Understand the product | [Platform Overview](../platform/overview.md) | [Architecture Map](../platform/capability-architecture.md) |
| Run it locally | [Installation](installation.md) | [Quickstart](quickstart.md) |
| Reproduce demo projects | [Run Demo Projects](run-demo-projects.md) | [Reproducibility Checklist](reproducibility.md) |
| Learn the model concepts | [Core Concepts](../concepts/overview.md) | [Network Model](../concepts/network-model.md) |
| Build with Python | [Python SDK Overview](../sdk/overview.md) | [Public Python API](../development/public-api.md) |
| Design an operation | [Utility Operations](../platform/operations.md) | [Locational Clearing](../flexibility/clearing.md) |
| Create a study | [Project Model](../projects/project-model.md) | [Project Problem Contract](../projects/problem-contract.md) |
| Publish or release | [Testing And Validation](../development/testing-and-validation.md) | [Release Readiness](../platform/release-readiness.md) |

## Section Meaning

| Section | What belongs there |
| --- | --- |
| Start | Step-by-step commands for installing, running, viewing, and reproducing. |
| Platform | Product identity, architecture, digital twin core, application surfaces, roadmap. |
| Platform | Durable vocabulary for network models, scenarios, states, artifacts, and semantic relationships. |
| SDK | Python package surfaces and reusable development interfaces. |
| Operations | Flexibility and utility operations: providers, clearing, dispatch, validation, KPIs. |
| Projects | Executable project examples plus the project/workflow contract. |
| Reference | Commands, schemas, semantic graph, artifact rules, and validation. |
| Development | Repository structure, contribution workflow, tests, release checks, and AI-agent guidance. |

## Source Of Truth

Gridalyn has three durable source-of-truth layers:

| Layer | Owns | Do not use it for |
| --- | --- | --- |
| `configs/` | reusable grid and geography configuration | generated outputs |
| `projects/<name>/` | reproducible workflow contracts, scripts, outputs, reports, figures | reusable library logic or dashboard application code |
| `instances/default/digital_twin/` | default materialized twin instance consumed by dashboards, semantics, reports, and applications | ad hoc notebooks, drafts, or project-only experiments |

`examples/` is tutorial material. It is not the runtime backend for governed
projects.

## Native Module Map

Use this table when a doc, script, or issue is ambiguous about ownership:

| Need | Native module |
| --- | --- |
| Reports, manifests, workspace layout, artifact policy | `gridalyn.foundation` |
| Network snapshots, adapters, topology, semantic graph | `gridalyn.twin` |
| Building, device, DER, thermal, load, and asset models | `gridalyn.assets` |
| Synthetic-network construction and physical validation | `gridalyn.simulation` |
| Providers, clearing, dispatch, settlement, KPIs | `gridalyn.operations` |
| Project contracts, workflow execution, sense checks | `gridalyn.projects` |
| CLI, dashboard/catalog, reporting, visualization | `gridalyn.interfaces` |

Use the native modules above as public entry points. If a note or script points
to a retired path, migrate it to the owning native module instead of adding
another facade.

## Verification Ladder

```bash
uv run gridalyn platform check-artifacts --summary-only
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project verify projects/minimal_grid_project
uv run gridalyn project regression projects/minimal_grid_project
uv run --with pytest python -m pytest -q
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

If one command fails, fix that layer before moving to the next command.

The ladder uses `minimal_grid_project` because it runs in seconds. `verify` and
`regression` read a project's emitted reports, and `outputs/` is not committed —
so they fail on a fresh clone until that project has been run. Substituting a
research study here means budgeting tens of minutes for the `run` step.

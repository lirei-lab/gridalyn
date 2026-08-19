# Gridalyn

Gridalyn is an open-source Python SDK for modeling, simulating and optimizing
multi-scale electric distribution systems and their distributed energy
resources — flexible building loads, EV chargers and energy storage.

It is built for researchers and academics who need **reproducible, citable
studies**: a declarative `StudyProject` and `Workflow` contract drives synthetic
data generation, a canonical network model, power flow, and flexibility-market
operations, emitting governed report artifacts with regression baselines. A
study is data, not code — two YAML files describe it, and re-running them
reproduces the numbers.

## Where to start

**[Start](start/what-is-gridalyn.md)** — install the workspace, run a compact
demo study, and read the artifacts it wrote. Five pages, ending at real output
on disk. In a hurry: go straight to the
[Quickstart](start/quickstart.md).

**[Components](components/overview.md)** — understand the platform itself, read
in one pass: seven layers, one page each, in the same order their own imports
run — `foundation → twin → assets → simulation → operations → projects →
interfaces`. Start here if you want to understand before you run.

**[Guides](guides/overview.md)** — task-shaped how-tos: build your own project,
author a workflow, generate reports and figures, open the dashboard.

**[Reference](reference/overview.md)** — the CLI, the Python API, the project
and workflow YAML contracts, the report schema and the artifact policy.

**[Contributing](contributing/overview.md)** — module boundaries, conventions,
testing and release, for extending the platform itself.

## First commands

```bash
uv sync --extra dev
uv run gridalyn --help
uv run gridalyn project validate projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
```

For the flagship research study — the full arc, calibrated inputs, pinned
headlines — budget time before running it: a full source regeneration is
roughly **six hours** across 23 stages, verified by an operator rather than in
CI via a pinned verification receipt. Warm runs against an existing cache take
minutes.

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project verify projects/ev_hosting_flex
```

## Where things live

| Path | What it holds |
| --- | --- |
| `gridalyn/` | The Python SDK — the canonical package and import namespace. |
| `projects/` | Executable demo and study projects using the same contract. |
| `instances/default/digital_twin/` | The default materialized twin instance. |
| `dashboard/` | Browser application consuming generated catalogs and reports. |
| `examples/` | Tutorial material, not project runtime logic. |

Generated caches, large data and derived artifacts stay out of git unless the
[Artifact Policy](reference/artifact-policy.md) explicitly allows them.

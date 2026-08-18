# What Is Gridalyn?

Gridalyn is a platform for distribution-grid network models, simulation-backed
studies, and flexibility operations. It is designed to support reproducible
research today while keeping the core close to the shape of a utility
platform: model-centric, traceable, adapter-driven, and ready for operational
applications.

It splits into seven layers — `foundation → twin → assets → simulation →
operations → projects → interfaces` — read end to end in
[Components](../components/overview.md). This page only orients you before
you install; the components walk is where "what it does" is actually
explained, one layer at a time.

## Who It Is For

Researchers who need reproducible, citable studies — a declarative
`StudyProject`/`Workflow` contract drives synthetic data generation, power
flow, and flexibility-market operations, and emits governed report artifacts
with regression baselines. Contributors extending the SDK reach the same
seven layers through [Components](../components/overview.md) and
[Contributing](../contributing/overview.md).

## What It Is Not

Gridalyn is not a single study or study-specific workflow. The public project
folder contains several demos with different levels of complexity, but the
platform boundary is broader than any one demo:

- reusable logic belongs in the Gridalyn SDK;
- executable studies belong in `projects/<name>/`;
- canonical twin artifacts belong under `instances/<name>/digital_twin/` — a
  project's twin is a named instance (`default` unless a project declares
  otherwise), not a single fixed location; see `gridalyn twin build
  --instance`;
- project-specific generated artifacts belong in project `outputs/`;
- dashboards and reports consume explicit artifacts, not study-specific hidden
  assumptions;
- public APIs use the native `gridalyn.*` modules and CLI commands.

`gridalyn.twin` also names one layer whose name is aspirational — see
[Twin](../components/twin.md) for the precise, measured claim; it is a
canonical, identified, schema-declared digital **model**, not a full digital
twin, and the page states exactly why.

## Public Interfaces

The platform name is Gridalyn. The public interfaces are:

- `gridalyn` as the command-line entrypoint;
- `gridalyn` as the Python SDK namespace;
- `lirei-lab/gridalyn` as the public repository name.

## Recommended Reading Order

1. [Installation](installation.md)
2. [Quickstart](quickstart.md)
3. [Reading The Outputs](reading-the-outputs.md)
4. [Components](../components/overview.md) — the platform itself, in one pass
5. [Run Demo Projects](run-demo-projects.md)
6. [CLI Reference](../reference/cli.md)

# Code Structure Audit

This page records the current code-structure boundary for Gridalyn. It is meant
to keep the repository aligned with the public architecture: reusable platform
capabilities live in `gridalyn/`, project folders declare reproducible studies,
and examples remain tutorial material.

## Current Shape

Gridalyn is now organized around seven canonical package areas:

| Area | Responsibility |
| --- | --- |
| `gridalyn.foundation` | IDs, units, lineage, manifests, validation primitives. |
| `gridalyn.assets` | Building, DER, EVSE, storage, and provider asset models. |
| `gridalyn.twin` | Digital twin artifacts, topology repositories, IO, semantic graph support. |
| `gridalyn.simulation` | Powerflow, optimization, surrogate, and environment execution helpers. |
| `gridalyn.operations` | Markets, control, dispatch, flexibility, verification, and KPIs. |
| `gridalyn.projects` | Project contracts, workflow execution, checks, and project reports. |
| `gridalyn.interfaces` | CLI, dashboard, reporting, adapters, and user-facing integration surfaces. |

This is the structure new code should target. New top-level package areas should
be avoided unless they represent a durable platform capability.

## What Is Healthy

- Public code is concentrated in `gridalyn/` instead of being hidden inside
  individual project scripts.
- Projects such as `projects/ev_hosting_flex`,
  `projects/ieee_33_bus_demo`, and other demos now use project manifests and
  workflow contracts.
- Publication-only figure generators are kept out of `projects/*/scripts` and
  belong under manuscript workspaces, not governed demo workflows.
- The historical `gridalyn/api.py` facade, dashboard-public exporters,
  database-manager shims, and project-owned compatibility routes have been
  removed instead of preserved as parallel APIs.
- `foundation` no longer acts as a catch-all facade for project or operations
  behavior. Project APIs live under `gridalyn.projects`; market and flexibility
  APIs live under `gridalyn.operations`.
- Examples are tutorial and interoperability material rather than the runtime
  backbone of projects.

## Structural Risks

Recent cleanup moved the generic Network Impact, locational clearing,
scorecard, dashboard extension, topology-cache, and workspace-validation
defaults away from individual study directories. Generic Gridalyn code now uses
`instances/default/digital_twin/cache`, `instances/default/digital_twin/flexibility`, and `instances/default/digital_twin/operations`
as platform artifact roots. Project-specific routes must be supplied by project
workflows, CLI arguments, or project manifests.

| Priority | Issue | Why It Matters | Direction |
| --- | --- | --- | --- |
| P0 | Keep the seven-package boundary stable. | Frequent package reshuffling makes the SDK hard to learn. | Add capabilities inside the canonical areas before creating new areas. |
| P1 | Keep `gridalyn/` independent from `projects/`. | The SDK must be usable without bundled demo projects. | Enforced by `test_gridalyn_package_does_not_depend_on_projects`. |
| P1 | Project-specific routes must be explicit. | Hidden defaults make demos look like platform requirements. | Pass paths through `project.yaml`, `workflow.yaml`, or CLI arguments. |
| P2 | Some low-level helpers still expose study-era names in comments or print messages. | They do not break functionality, but they make the source harder to read before open source publication. | Rename messages and comments when touching the owning module; avoid compatibility shims. |

## Native Import Retirement Inventory

The canonical SDK surface is `foundation`, `twin`, `assets`, `simulation`,
`operations`, `projects`, and `interfaces`. Public docs, examples, and new tests
should use those names directly. Archived callers should be recovered from Git
history or migrated to the native surface. Do not add compatibility modules for
removed paths.

## Rules For New Code

1. Put reusable behavior in `gridalyn/`, not in `projects/` or `examples/`.
2. Put project orchestration in `projects/<name>/workflow.yaml`.
3. Put tutorial scripts in `examples/` only when they are optional learning
   material.
4. Keep generated artifacts out of package directories.
5. Prefer explicit paths from project manifests over hard-coded repository paths.
6. Use normal imports. Avoid runtime `sys.path` edits inside package modules.
7. If a path exists only for historical imports, remove it or migrate callers
   to the native module.

## Cleanup Sequence

The next cleanup should be incremental:

1. Keep import-boundary checks current as new platform modules appear.
2. Rename study-era comments and messages when touching the owning module.
3. Keep examples small, documented, and independent from governed project
   execution.

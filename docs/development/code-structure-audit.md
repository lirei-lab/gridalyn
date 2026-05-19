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
- Projects such as `projects/flexibility_cls`,
  `projects/ieee_33_bus_demo`, and other demos now use project manifests and
  workflow contracts.
- Compatibility aliases keep older import paths working while the repository
  transitions to the canonical package layout.
- Examples are moving toward tutorial and interoperability roles rather than
  being the runtime backbone of projects.

## Structural Risks

Recent cleanup moved the generic Network Impact, locational clearing,
scorecard, dashboard extension, topology-cache, and workspace-validation
defaults away from `projects/flexibility_cls`. Generic Gridalyn code now uses
`instances/default/digital_twin/cache`, `instances/default/digital_twin/flexibility`, and `instances/default/digital_twin/operations`
as platform artifact roots. Project-specific routes must be supplied by project
workflows, CLI arguments, or project manifests.

| Priority | Issue | Why It Matters | Direction |
| --- | --- | --- | --- |
| P0 | Keep the seven-package boundary stable. | Frequent package reshuffling makes the SDK hard to learn. | Add capabilities inside the canonical areas before creating new areas. |
| P1 | Keep `gridalyn/` independent from `projects/`. | The SDK must be usable without bundled demo projects. | Enforced by `test_gridalyn_package_does_not_depend_on_projects`. |
| P1 | Project-specific routes must be explicit. | Hidden defaults make demos look like platform requirements. | Pass paths through `project.yaml`, `workflow.yaml`, or CLI arguments. |
| P1 | Some project workflows still call scripts in `examples/`. | Examples should teach; the SDK should execute reusable operations. | Move reusable GeoJSON and data-acquisition functions into `gridalyn.twin` or `gridalyn.interfaces.cli`. |
| P1 | Manuscript-specific figure scripts still exist near project logic. | Public projects should not depend on private manuscript outputs. | Keep publication-only material outside the public project workflow. |
| P2 | Legacy compatibility import aliases remain. | They are useful now, but can confuse new users. | Keep them documented as temporary import shims, not as public commands. |
| P2 | `gridalyn.api.Interface` reflects an older interactive synthetic-grid interface. | It does not match the current platform boundary. | Replace it with smaller SDK entry points or mark it as legacy. |

## Rules For New Code

1. Put reusable behavior in `gridalyn/`, not in `projects/` or `examples/`.
2. Put project orchestration in `projects/<name>/workflow.yaml`.
3. Put tutorial scripts in `examples/` only when they are optional learning
   material.
4. Keep generated artifacts out of package directories.
5. Prefer explicit paths from project manifests over hard-coded repository paths.
6. Use normal imports. Avoid runtime `sys.path` edits inside package modules.
7. If a module exists only for backward compatibility, document that fact.

## Cleanup Sequence

The next cleanup should be incremental:

1. Promote GeoJSON network-generation utilities from examples into SDK/CLI
   functions.
2. Move publication-only figure generation behind a private or optional
   manuscript workflow.
3. Add deprecation notes for legacy import aliases.
4. Add import-boundary tests that fail when package modules depend on examples
   or project-specific paths.

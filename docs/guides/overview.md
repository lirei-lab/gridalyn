# Guide Overview

Guides are task-oriented: each one shows how to produce or inspect a specific
artifact using the current CLI and project layout. They intentionally call
reusable platform commands — if a task needs copying a large project script,
that behavior probably belongs in `gridalyn/` instead, per
[Components](../components/overview.md)'s placement rule.

## The sequence

A study moves through the platform in one order, and the guides below are
listed in it rather than alphabetically. The same order appears in three
places, which is the strongest evidence it is real rather than imposed: it is
the direction imports flow between layers, it is the verb-prefix order of a
`workflow.yaml`'s stage ids, and it is the order these guides are written in.

| Phase | Layer | What runs it | Guide |
| --- | --- | --- | --- |
| **Declare** the study as a contract | [Projects](../components/projects.md) | `gridalyn project init`, then `validate` | [Build Your Own Project](build-your-own-project.md), [Project Template](project-template.md) |
| **Model** what the study acts on | [Twin](../components/twin.md), [Assets](../components/assets.md) | `gridalyn twin build`; stages prefixed `build_*` / `generate_*` | [Build A Twin](build-a-twin.md), [Synthetic Networks From GeoJSON](synthetic-network-from-geojson.md) |
| **Design the mechanism** — the thing the study exists to do | [Simulation](../components/simulation.md), [Operations](../components/operations.md) | `gridalyn project run`; stages prefixed `run_*`, then `analyze_*` | [Author A Workflow](author-a-workflow.md) |
| **Validate** before believing the result | [Projects](../components/projects.md) | `sense-check` (do the numbers make sense?), `regression` (did they move?), `verify` (both, plus artifact status) | [Reproducibility](reproducibility.md) |
| **Publish** the result outward | [Interfaces](../components/interfaces.md) | stages prefixed `export_*`; the report contract | [Reports And Figures](reports-and-figures.md), [Open The Dashboard](open-the-dashboard.md) |

Two things worth noticing in that table.

**Validation is a phase, not an afterthought.** In the six light governed
studies it is a stage inside the workflow itself (`validate_project_outputs`),
so `gridalyn project run` cannot report success on a study whose numbers were
never examined. The two heavy studies validate operator-side instead, because
their runs take hours.

**The three validation commands answer three different questions**, and the
distinction matters more than the similar names suggest: `validate` asks
whether the contract is well-formed, `sense-check` whether the numbers are
plausible, `regression` whether they moved against a pinned baseline. Nothing
answers all three at once except `verify`, which excludes regression.

## Outside the sequence

[Write An Extension](write-an-extension.md) is the one guide that is not a
phase: it shows how to register a component from outside `gridalyn` without
editing it, which applies at whichever phase the component belongs to.

Read [Components](../components/overview.md) first if a guide's vocabulary is
unfamiliar — every term it uses is defined there or in the
[Glossary](../reference/glossary.md).

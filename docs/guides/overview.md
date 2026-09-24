# Guide Overview

Each guide takes one task from start to finish with the current CLI and
project layout. A guide calls reusable platform commands; if a task seems to
need a large copied script, that behaviour belongs in `gridalyn/` instead, per
the placement rule in [Components](../components/overview.md).

## The guides

They are listed in the order a study uses them: declare the project, model
what it acts on, publish what it produces, then reproduce and inspect the
result.

| Guide | Use it to | Layers |
| --- | --- | --- |
| [Build Your Own Project](build-your-own-project.md) | Declare a new study as a project: scaffold it, write its workflow and stages, and run it. | [Projects](../components/projects.md) |
| [Build A Twin](build-a-twin.md) | Build the network model a named instance's studies act on. | [Twin](../components/twin.md) |
| [Synthetic Networks From GeoJSON](synthetic-network-from-geojson.md) | Derive a synthetic feeder from building footprints. | [Twin](../components/twin.md), [Assets](../components/assets.md) |
| [Feed Measured Data](feed-measured-data.md) | Run measured data through the twin's ingest path; the worked example is `measured_shadow_feeder`. | [Twin](../components/twin.md) |
| [Write Governed Reports And Figures](reports-and-figures.md) | Write a stage's platform report and figures. | [Foundation](../components/foundation.md), [Projects](../components/projects.md) |
| [Reproduce A Published Result](reproducibility.md) | Re-run a study in a pinned environment and check it against its baseline. | [Projects](../components/projects.md) |
| [Open The Dashboard](open-the-dashboard.md) | Browse an instance's exported artifacts in the web dashboard. | [Interfaces](../components/interfaces.md) |
| [Write An Extension](write-an-extension.md) | Serve a role with a component that lives outside `gridalyn`. | Any |

## Where checking fits

A result is checked before it is believed. The CI fixture studies end their
workflow with a `validate_project_outputs` stage, so `gridalyn project run`
cannot report success on numbers nobody examined; operator-verified studies are
checked by an operator, as described in
[Operator Verification](../contributing/verification.md).

The project checks answer different questions: `validate` whether the
contract is well-formed, `sense-check` whether the numbers are plausible,
`regression` whether they moved against a pinned baseline. `verify` combines
the contract check, artifact status and the sense checks; it does not run
`regression`. [Testing And Validation](../contributing/testing-and-validation.md)
owns the full ladder and when to run each check.

Read [Components](../components/overview.md) first if a guide's vocabulary is
unfamiliar; every term it uses is defined there or in the
[Glossary](../reference/glossary.md).

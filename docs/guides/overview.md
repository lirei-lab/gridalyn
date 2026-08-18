# Guide Overview

Guides are task-oriented: each one shows how to produce or inspect a specific
artifact using the current CLI and project layout. They intentionally call
reusable platform commands — if a task needs copying a large project script,
that behavior probably belongs in `gridalyn/` instead, per
[Components](../components/overview.md)'s placement rule.

| Guide | Task |
| --- | --- |
| [Build Your Own Project](build-your-own-project.md) | Start a new study from the project contract. |
| [Project Template](project-template.md) | The declared shape every project follows. |
| [Author A Workflow](author-a-workflow.md) | Add a stage to a workflow DAG. |
| [Build A Twin](build-a-twin.md) | Produce a minimal digital-twin base from scratch. |
| [Synthetic Networks From GeoJSON](synthetic-network-from-geojson.md) | Build a network from real geospatial footprints. |
| [Reports And Figures](reports-and-figures.md) | Generate a governed report and a figure from a run. |
| [Open The Dashboard](open-the-dashboard.md) | Build and serve the dashboard SPA against generated catalogs. |
| [Write An Extension](write-an-extension.md) | Register a component from outside `gridalyn` without editing it. |
| [Reproducibility](reproducibility.md) | Get byte-stable results across machines and re-runs. |

Read [Components](../components/overview.md) first if a guide's vocabulary is
unfamiliar — every term it uses is defined there or in the
[Glossary](../reference/glossary.md).

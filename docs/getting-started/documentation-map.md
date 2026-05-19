# Documentation Map

Use this page when you are unsure where to go next. Gridalyn documentation is
organized around platform surfaces and user roles rather than repository
folders.

## Fast Paths

| Goal | Start here | Then read |
| --- | --- | --- |
| Understand the product | [Platform Overview](../platform/overview.md) | [Architecture Map](../platform/capability-architecture.md) |
| Run it locally | [Installation](installation.md) | [Quickstart](quickstart.md) |
| Reproduce demo projects | [Run Demo Projects](run-ev-project.md) | [Reproducibility Checklist](reproducibility.md) |
| Learn the model concepts | [Core Concepts](../concepts/overview.md) | [Network Model](../concepts/network-model.md) |
| Build with Python | [Python SDK Overview](../sdk/overview.md) | [Public Python API](../development/public-api.md) |
| Design an operation | [Utility Operations](../platform/operations.md) | [Locational Clearing](../flexibility/clearing.md) |
| Create a study | [Project Model](../projects/project-model.md) | [Workflow YAML](../workflows/workflow-yaml-reference.md) |
| Publish or release | [Testing And Validation](../development/testing-and-validation.md) | [Release Readiness](../platform/release-readiness.md) |
| Guide an AI coding agent | [AI Agent Guide](../development/ai-agent-guide.md) | [Testing And Validation](../development/testing-and-validation.md) |

## Section Meaning

| Section | What belongs there |
| --- | --- |
| Start | Step-by-step commands for installing, running, viewing, and reproducing. |
| Platform | Product identity, architecture, digital twin core, application surfaces, roadmap. |
| Core Concepts | Durable vocabulary for network models, scenarios, states, artifacts, and semantic relationships. |
| SDK | Python package surfaces and reusable development interfaces. |
| Operations | Flexibility and utility operations: providers, clearing, dispatch, validation, KPIs. |
| Demos | Executable project examples plus the project/workflow contract. |
| Reference | Commands, schemas, semantic graph, artifact rules, and validation. |
| Development | Repository structure, contribution workflow, tests, release checks, and AI-agent guidance. |

## Source Of Truth

Gridalyn has three durable source-of-truth layers:

| Layer | Owns | Do not use it for |
| --- | --- | --- |
| `configs/` | reusable grid and geography configuration | generated outputs |
| `projects/<name>/` | reproducible workflow contracts, scripts, outputs, reports, figures | reusable library logic or dashboard application code |
| `instances/default/digital_twin/` | default materialized twin instance consumed by dashboards, semantics, reports, and applications; exposed at the compatibility path `digital_twin/` | private notebooks or editorial drafts |

`examples/` is tutorial material. It is not the runtime backend for governed
projects.

## Verification Ladder

```bash
uv run gridalyn platform check-artifacts --summary-only
uv run gridalyn project validate projects/flexibility_cls --check-artifacts
uv run gridalyn project verify projects/flexibility_cls
uv run gridalyn project regression projects/flexibility_cls
uv run --with pytest python -m pytest -q
uv run mkdocs build --strict -f docs/mkdocs.yml
```

If one command fails, fix that layer before moving to the next command.

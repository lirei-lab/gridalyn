# Project Template Guide

Gridalyn projects are meant to be predictable. A template should create a
workspace that can be validated, planned, run, and inspected before any
domain-specific model is added.

## Recommended Template

Use `grid-study` for new studies:

```bash
uv run gridalyn project init projects/my_case --name my_case --template grid-study
```

It creates:

```text
projects/my_case/
  project.yaml
  workflow.yaml
  inputs/
  scripts/
    write_summary_report.py
  outputs/
    data/
    figures/
    manifests/
    operations/
    reports/
```

Run it immediately:

```bash
uv run gridalyn project run projects/my_case
uv run gridalyn project status projects/my_case --check-artifacts
```

The initial workflow writes `outputs/reports/project_summary.json` using the
platform report schema. That gives every project a valid first artifact.

## Minimal Template

Use `minimal` only when you want to build the workflow contract yourself:

```bash
uv run gridalyn project init projects/my_minimal_case --template minimal
```

It creates the same top-level folders but does not add a domain report stage.

## When Adding Stages

Each workflow stage should answer four questions:

| Question | Where it belongs |
| --- | --- |
| What command runs? | `workflow.yaml` stage `command` |
| What does it need first? | `workflow.yaml` stage `needs` |
| What does it produce? | `workflow.yaml` stage `outputs` |
| How is it validated? | `project.yaml` `validation` and project tests |

Prefer small stages with explicit outputs. A dashboard, report, or publication
should be able to trace every number back to a declared project artifact.

## Library Boundary

Use this rule when deciding where code lives:

| Code type | Location |
| --- | --- |
| Reusable modeling, simulation, analytics, or market logic | `gridalyn/` |
| Study-specific orchestration and path binding | `projects/<name>/scripts/` |
| Generated data, reports, figures, and operation records | `projects/<name>/outputs/` |
| Documentation for how to run or interpret the study | `projects/<name>/README.md` and MkDocs pages |

Every demo project should prove one platform capability clearly. No project
should become a hidden dependency for other projects.

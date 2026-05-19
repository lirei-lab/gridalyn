# Projects and Workflows

Projects are the governance layer for reproducible studies. A project declares
where inputs come from, which workflow stages run, where generated artifacts are
written, and which reports and figures must exist before the study is considered
ready.

Gridalyn includes multiple demo projects. Start with
`projects/minimal_grid_project/` or `projects/ieee_33_bus_demo/` when learning
the workflow contract; use `projects/flexibility_cls/` only when you need the
larger flexibility operations stack.

## Why Projects Exist

The digital twin base is generated from raw geography and grid configuration.
That means the project contract must start before `digital_twin/base`; it owns
the full chain from input configuration to final reports.

Use projects to avoid hidden dependencies on notebooks, tutorial scripts, or
private publication folders.

## Path Ownership

| Path | Owner | Rule |
| --- | --- | --- |
| `configs/` | shared configuration | reusable input configuration, not generated outputs |
| `projects/<name>/` | project owner | executable workflow contract, scripts, outputs, reports, figures |
| `digital_twin/` | platform artifact layer | canonical Parquet/JSON contracts consumed by dashboards and applications |
| `gridalyn/` | platform SDK | reusable logic only; no case-study outputs |
| `examples/` | tutorial owner | examples and compatibility wrappers only; not a project runtime backend |

## Project Layout

```text
projects/<project_name>/
  project.yaml
  workflow.yaml
  README.md
  scripts/
  outputs/
    data/
    json/
    figures/
    reports/
    manifests/
```

The generated outputs are project-local by default. Shared platform artifacts
such as `digital_twin/base`, `digital_twin/scenarios`, `digital_twin/semantic`,
and `digital_twin/dashboard/catalog.json` remain in the repository-level
digital twin directories.

## `project.yaml`

`project.yaml` is the study contract. It follows an `apiVersion`, `kind`,
`metadata`, `spec` shape so it remains familiar to users of Kubernetes,
Argo-style workflows, and modern data-orchestration systems.

Minimal shape:

```yaml
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: flexibility_cls
  version: 0.1.0
spec:
  pathBase: repo
  inputs: {}
  artifacts: {}
  workflow:
    file: projects/flexibility_cls/workflow.yaml
  validation:
    requiredReports: []
    requiredFigures: []
```

`spec.pathBase: repo` means all paths resolve from the repository root. That
keeps project manifests readable and avoids nested `../../` paths.

## `workflow.yaml`

`workflow.yaml` declares the executable stage graph. Stages should be small,
named by responsibility, and explicit about inputs and outputs.

```yaml
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: flexibility_cls
spec:
  stages:
    - id: prepare_topology_cache
      command: uv run python projects/flexibility_cls/scripts/pipeline/prepare_topology_cache.py
      outputs:
        - projects/flexibility_cls/outputs/cache/pg_graph_cache.pkl

    - id: generate_stochastic_profiles
      needs: [prepare_topology_cache]
      command: uv run python projects/flexibility_cls/scripts/pipeline/00_generate_stochastic_profiles.py
      outputs:
        - projects/flexibility_cls/outputs/data/substation_baseline_mc.parquet
```

The workflow runner executes stages in declared order, respects dependencies,
and writes a run manifest under `outputs/manifests/`.

## CLI

Create a project:

```bash
uv run gridalyn project init projects/my_case --name my_case
```

Validate:

```bash
uv run gridalyn project validate projects/my_case --check-artifacts
```

Plan:

```bash
uv run gridalyn project plan projects/my_case
```

Run:

```bash
uv run gridalyn project run projects/my_case
```

Status:

```bash
uv run gridalyn project status projects/my_case --check-artifacts
```

## Python API

```python
from gridalyn.foundation.platform import init_project, load_project, plan_project

created = init_project("projects/my_case", name="my_case")
project = load_project(created.root)
stages = plan_project(project)
```

## Validation Contract

Use `spec.validation.requiredReports` for JSON reports that must satisfy the
platform report contract.

Use `spec.validation.requiredFigures` for figures that must exist and be
non-empty.

The status command reports:

- expected report count;
- found report count;
- invalid report count;
- missing artifacts;
- project and workflow validity;
- run manifest location.

## Run Governance

Every dry run or execution writes a `study_run` object into:

```text
projects/<name>/outputs/manifests/project_run_manifest.json
```

The object records:

- `run_id` in the form `run:<project>:<digest>`;
- project and workflow identifiers;
- dry-run flag;
- status;
- start and end timestamps;
- Git commit when available;
- stage counts for planned, completed, and failed stages;
- lineage paths for the project and workflow manifests.

Reports can also carry governance links through the platform report helper:
`ReportMetadata(model_version_id=..., study_run_id=...)`.

## Design Rules

- Keep project outputs under `projects/<name>/outputs`.
- Keep publication-only plots outside executable workflow stages.
- Keep reusable logic in the Gridalyn SDK, not in a project script.
- Keep reusable configuration in `configs`; projects should not depend on
  tutorial paths under `examples`.
- Regenerate reports after changing workflow outputs.

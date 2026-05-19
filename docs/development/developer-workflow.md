# Developer Workflow

This page is the practical checklist for working on the current repository
without mixing generated artifacts, project outputs, and source changes.

## Common Commands

Create and inspect a project workspace:

```bash
uv run gridalyn project init projects/my_case --name my_case
uv run gridalyn project validate projects/my_case
uv run gridalyn project plan projects/my_case
uv run gridalyn project status projects/my_case
```

Check repository-level artifact policy:

```bash
uv run gridalyn platform check-artifacts --summary-only
```

Embed the platform from Python:

```python
from gridalyn.platform import check_artifact_policy, load_project, plan_project, validate_project

project = load_project("projects/flexibility_cls")
report = validate_project(project.path)
stages = plan_project(project)
artifact_report = check_artifact_policy(".")
```

Write a standard report:

```python
from gridalyn.platform import ReportMetadata, write_report

write_report(
    "projects/my_case/outputs/reports/sample_report.json",
    metadata=ReportMetadata(report_id="sample_report", source_domain="my_case"),
    summary={"valid": True},
)
```

Run unit tests:

```bash
uv run --with pytest python -m pytest -q
```

Run focused tests:

```bash
uv run --with pytest python -m pytest tests/test_semantic_graph.py -q
uv run --with pytest python -m pytest tests/test_canonical_reports.py -q
```

Generate the semantic graph:

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --flexibility-dir instances/default/digital_twin/flexibility \
  --timeseries-dir instances/default/digital_twin/timeseries \
  --out-dir instances/default/digital_twin/semantic
```

Validate graph semantics:

```bash
uv run gridalyn semantic validate \
  --semantic-dir instances/default/digital_twin/semantic
```

Generate locational clearing artifacts:

```bash
uv run gridalyn market locational-clearing \
  --scenario-id S4 \
  --top-constraints 3
```

Build current Flexibility CLS project reports:

```bash
uv run python projects/flexibility_cls/scripts/reports/build_study_reports.py
```

Build digital twin reports:

```bash
uv run python -m gridalyn.reporting.digital_twin
```

Build documentation:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

## Generated Files

Large simulation runs update many generated outputs:

- `instances/default/digital_twin/reports/canonical/`;
- `instances/default/digital_twin/semantic/`;
- `projects/flexibility_cls/outputs/`;
- root `site/` when MkDocs builds.

Generated project figures should remain under governed output folders. Private
publication drafts, review material, and compiled document artifacts are outside
the public platform architecture and should not drive workflow design.

Before committing, inspect `git status --short` and stage only the files that are
part of the intended change. Generated outputs should be committed only when the
user asks for a reproducible checkpoint or when the change intentionally updates
published artifacts.

## Documentation Rules

Keep documentation source under the domain folders in `docs/`. Do not commit
built HTML under `docs/site`; MkDocs writes the generated site to `/site`,
which is ignored.

When adding a new subsystem, update at least one of:

- `getting-started/documentation-map.md` if the reader path changes;
- `getting-started/reproducibility.md` if verification commands change;
- `platform/architecture.md` for system-level placement;
- `platform/digital-twin.md` for canonical data layout;
- `platform/projects-and-workflows.md` for project contract behavior;
- `workflows/flexibility-cls.md` for the larger flexibility workflow;
- `platform/reports.md` for report contract changes;
- `semantic-layer/semantic-graph.md` for ontology or graph changes;
- `platform/dashboard.md` for visualization and catalog changes.
- `development/artifact-policy.md` for Git, data, and generated-output policy.

## Commit Hygiene

Recommended flow:

```bash
git status --short
git add <intentional files>
git diff --cached --stat
git commit -m "Concise message"
```

Avoid broad `git add .` in this repository after running simulations. The
working tree often contains useful regenerated artifacts that are not part of the
current source change.

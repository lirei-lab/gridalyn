# Project Hygiene

Project hygiene keeps Gridalyn readable as a reusable SDK plus governed demo
projects. Source code, project contracts, tests, and documentation should tell
the platform story. Generated outputs and local experiments should stay in
declared artifact locations.

## Source Of Truth

| Path | Role | Keep Out |
| --- | --- | --- |
| `gridalyn/` | Reusable platform SDK code. | Project-specific orchestration, local outputs, generated reports. |
| `projects/<name>/project.yaml` | Project identity, problem, scenarios, experiments, inputs, outputs, and validation expectations. | Runtime state or implementation logic. |
| `projects/<name>/workflow.yaml` | Ordered workflow stages and commands. | Reusable modeling, solver, or market algorithms. |
| `projects/<name>/scripts/` | Thin project orchestration. | Shared platform behavior that should live in `gridalyn/`. |
| `projects/<name>/outputs/` | Generated project artifacts. | Manually edited source files. |
| `instances/default/digital_twin/` | Canonical local digital-twin instance consumed by dashboards, reports, semantics, and applications. | Private notebooks, draft material, or ad hoc scratch files. |
| `examples/` | Optional tutorials and small learning scripts. | Runtime dependencies for governed projects. |
| `docs/` | User, SDK, operations, project, and developer documentation. | Generated site output or publication drafts. |

## Artifact Placement

Use the project workspace contract for demo outputs:

```text
projects/<project>/
  outputs/
    data/
    figures/
    json/
    manifests/
    operations/
    reports/
    cache/
```

Use the digital-twin instance contract for platform-level materialized state:

```text
instances/default/digital_twin/
  base/
  models/
  scenarios/
  timeseries/
  flexibility/
  operations/
  semantic/
  reports/
  dashboard/
```

If an artifact proves one project workflow, put it under that project's
`outputs/`. If an artifact is part of the default platform instance consumed by
dashboard, semantic, reporting, or application surfaces, put it under
`instances/default/digital_twin/`.

## Project Script Boundary

Project scripts should be thin. They may:

- load project-local input files;
- pin demo parameters;
- call SDK APIs from `gridalyn/`;
- write declared outputs;
- assemble project reports from platform report helpers.

Project scripts should not:

- define reusable asset models, solver builders, market engines, or reporting
  frameworks;
- hard-code paths from another project;
- publish dashboard state directly;
- create hidden runtime dependencies on `examples/`;
- manually edit generated outputs.

When two projects need the same function, move it into the owning SDK module
before copying it across demos.

## Dashboard And Reporting Boundary

Dashboard-facing state should flow through canonical contracts:

- `instances/default/digital_twin/dashboard/catalog.json`;
- semantic graph artifacts under `instances/default/digital_twin/semantic/`;
- canonical reports under `instances/default/digital_twin/reports/`;
- project reports under `projects/<project>/outputs/reports/`;
- operations catalogs under `outputs/operations/` or
  `instances/default/digital_twin/operations/`.

Visualization code belongs under `gridalyn.interfaces.viz` when it is reusable.
Project-local figures are acceptable when they explain one demo result and are
declared in the project contract.

## Examples Policy

`examples/` is tutorial material. Production workflows should use platform CLI
commands and governed project contracts:

```bash
uv run gridalyn twin build --dry-run
uv run gridalyn project run projects/<project>
uv run gridalyn project verify projects/<project>
uv run gridalyn semantic validate
uv run gridalyn dashboard catalog
```

Shared grid and geography configuration belongs under `configs/`, not
`examples/`. Tutorial-generated maps, caches, and temporary outputs should not
be project runtime dependencies.

## Cleanliness Checks

Run the relevant checks before publishing or reviewing a change:

```bash
uv run gridalyn validate
uv run gridalyn project verify-all
uv run --with pytest python -m pytest -q
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
git diff --check
```

For a smaller project-only change, start with:

```bash
uv run gridalyn project verify projects/<project>
```

The release checklist in [Release Readiness](releasing.md)
combines these checks with dashboard validation.

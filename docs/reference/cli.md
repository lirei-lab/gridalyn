# CLI Reference

Gridalyn exposes the `gridalyn` command as the canonical entrypoint.

## Top-Level Help

```bash
uv run gridalyn --help
```

## Main Command Groups

| Command | Purpose |
| --- | --- |
| `gridalyn doctor` | Inspect the local install, workspace, projects, and optional capabilities. |
| `gridalyn validate` | Run the unified workspace validation ladder. |
| `gridalyn project` | Initialize, validate, plan, run, inspect, and regression-test governed projects. |
| `gridalyn twin` | Build and inspect digital twin artifacts. |
| `gridalyn market` | Generate providers, score network impact, clear flexibility, dispatch, settle, and verify operations. |
| `gridalyn semantic` | Build and validate ontology-aligned graph artifacts. |
| `gridalyn dashboard` | Generate dashboard catalogs and related metadata. |
| `gridalyn platform` | Run platform hygiene and artifact-policy checks. |

## Common Commands

```bash
uv run gridalyn doctor
uv run gridalyn validate
uv run gridalyn project list
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
uv run gridalyn project plan projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project regression projects/flexibility_cls
uv run gridalyn project sense-check projects/minimal_grid_project
uv run gridalyn project verify projects/minimal_grid_project
uv run gridalyn project verify-all
```

```bash
uv run gridalyn twin build --dry-run --skip-heavy
uv run gridalyn twin clip-buildings --buildings-file buildings.geojson --polygon-file polygon.json --output-file clipped.geojson
uv run gridalyn twin prepare-microsoft-buildings --input-file partition.geojsonl.gz --polygon-file polygon.json --output-file buildings.geojson
uv run gridalyn semantic build --profile north_america
uv run gridalyn semantic validate
uv run gridalyn dashboard catalog
uv run gridalyn platform check-artifacts --summary-only
```

Use the stricter validation path when you want project artifacts and the
configured flexibility regression:

```bash
uv run gridalyn validate --check-project-artifacts
uv run gridalyn validate \
  --project projects/flexibility_cls \
  --check-project-artifacts \
  --regression
```

For a larger operations workflow, replace `projects/minimal_grid_project` with
`projects/flexibility_cls`.

Create a runnable project scaffold:

```bash
uv run gridalyn project init projects/my_case --name my_case --template grid-study
uv run gridalyn project run projects/my_case
uv run gridalyn project status projects/my_case --check-artifacts
```

Run a project without writing the generated sense-check report:

```bash
uv run gridalyn project sense-check projects/rl_voltage_control_lightsim --no-write
uv run gridalyn project verify projects/rl_voltage_control_lightsim --no-write
```

`sense-check` returns exit code `0` only when all error-level objective checks
pass. Warning-level failures are reported in JSON but do not block the command.
`verify` is the recommended agent/CI command because it combines project
contract validation, artifact status, and sense checks in one JSON payload.
`verify-all` applies the same ladder to every governed project under
`projects/` and does not write sense-check reports unless `--write` is passed.

## Domain-Specific Entrypoints

Some script-friendly aliases are also installed:

```bash
uv run gridalyn-dt --help
uv run gridalyn-flex --help
uv run gridalyn-semantic --help
uv run gridalyn-dashboard --help
uv run gridalyn-platform --help
```

Prefer the top-level `gridalyn` command in documentation and project workflows
unless an automation script needs a narrower executable.

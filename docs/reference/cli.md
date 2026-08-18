# CLI Reference

Gridalyn exposes the `gridalyn` command as the canonical entrypoint.

## Top-Level Help

```bash
uv run gridalyn --help
```

Domain help is delegated to the domain parser:

```bash
uv run gridalyn project --help
uv run gridalyn twin --help
uv run gridalyn market --help
uv run gridalyn extension --help
```

## Main Command Groups

| Command | Purpose |
| --- | --- |
| `gridalyn doctor` | Inspect the local install, workspace, projects, and optional capabilities. |
| `gridalyn validate` | Run the unified workspace validation ladder. |
| `gridalyn project` | Initialize, validate, plan, run, inspect, and regression-test governed projects. |
| `gridalyn twin` | Build and inspect digital twin artifacts — any named instance, with declared capability layers. |
| `gridalyn market` | Generate providers, score network impact, clear flexibility, dispatch, settle, and verify operations. |
| `gridalyn semantic` | Build and validate ontology-aligned graph artifacts. |
| `gridalyn dashboard` | Generate dashboard catalogs and related metadata. |
| `gridalyn platform` | Run platform hygiene and artifact-policy checks. |
| `gridalyn extension` | List, validate, and scaffold extensions that register against a role without editing `gridalyn`. |

## Common Commands

```bash
uv run gridalyn doctor
uv run gridalyn validate
uv run gridalyn project list
uv run gridalyn project prepare-workspace projects/minimal_grid_project
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
uv run gridalyn project plan projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project regression projects/ev_hosting_flex
uv run gridalyn project sense-check projects/minimal_grid_project
uv run gridalyn project verify projects/minimal_grid_project
uv run gridalyn project verify-all
```

```bash
uv run gridalyn twin build --dry-run --skip-heavy
uv run gridalyn twin build --instance <name> --capabilities "" --dry-run
uv run gridalyn twin building-models --instance <name>
uv run gridalyn twin clip-buildings --buildings-file buildings.geojson --polygon-file polygon.json --output-file clipped.geojson
uv run gridalyn twin prepare-microsoft-buildings --input-file partition.geojsonl.gz --polygon-file polygon.json --output-file buildings.geojson
uv run gridalyn semantic build --profile north_america
uv run gridalyn semantic validate
uv run gridalyn dashboard catalog
uv run gridalyn platform check-artifacts --summary-only
uv run gridalyn extension list
uv run gridalyn extension new my_backend --role powerflow_backend --target /tmp/my-extensions
```

`extension validate <id>` only resolves an **installed** extension — running
it against a freshly scaffolded, not-yet-installed package exits 1 with a
located error naming what is actually registered. Install the scaffolded
package first (`pip install -e /tmp/my-extensions/my_backend`), then
`gridalyn extension validate my_backend` succeeds. See
[Write An Extension](../guides/write-an-extension.md) for the full loop.

`gridalyn twin` is a general mechanism for any project's twin: `--instance`
selects which named twin under `instances/<name>/digital_twin/` to operate on
(default `default`), and `build --capabilities` declares which on-demand
layers to include (an empty value is a generic model-first build; the legacy
`ev-hosting,flexibility` layers are the default when the flag is omitted).

Use the stricter validation path when you want project artifacts and the
configured flexibility regression:

```bash
uv run gridalyn validate --check-project-artifacts
uv run gridalyn validate \
  --project projects/ev_hosting_flex \
  --check-project-artifacts \
  --regression
```

For a larger operations workflow, replace `projects/minimal_grid_project` with
`projects/ev_hosting_flex`.

Create a runnable project scaffold:

```bash
uv run gridalyn project init projects/my_case --name my_case --template grid-study
uv run gridalyn project run projects/my_case
uv run gridalyn project status projects/my_case --check-artifacts
```

Check a project without writing the generated sense-check report. Both commands
read artifacts the project has already produced, so run it first:

```bash
uv run gridalyn project run projects/rl_voltage_control_lightsim
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

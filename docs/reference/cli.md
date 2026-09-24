# CLI Reference

`gridalyn` is the one command-line entry point. Its first argument is a
command: `quickstart`, `validate` and `doctor` run directly, and every other
command names a domain (`twin`, `project`, `market`, `semantic`, `dashboard`,
`platform`, `extension`) whose own parser reads the rest of the line. Most
domains also install a console script of their own, such as `gridalyn-dt` for
`gridalyn twin`; the [command tables](#command-reference) below list each one.

## How arguments reach a command

A domain subcommand is served in one of two ways:

- **By the command itself.** `project`, `platform`, `extension`, `twin build`
  and the twin building-footprint commands parse every argument they accept.
- **By a workflow script.** The twin layer commands (`twin base`,
  `twin powerflow`, ...) and every `market`, `semantic` and `dashboard`
  subcommand run a module from `gridalyn.projects.workflows`. The subcommand
  parses its own options, when it has any, and hands everything else on the
  line to the script's parser. The tables list both sets.

`gridalyn <domain> --help` lists a domain's subcommands, and
`gridalyn <domain> <subcommand> --help` prints every option that subcommand
accepts, the same as its console script (`gridalyn-dt base --help`). For a
pass-through subcommand that is its own options, when it has any, followed by
the options of the script it runs.

Path defaults in the tables are shown relative to the workspace root, for the
`default` twin instance. The twin layer commands move them with `--root` and
`--instance`, which they pass to the script as `GRIDALYN_WORKSPACE_ROOT` and
`GRIDALYN_INSTANCE`.

## Common workflows

Discover the commands and check the install:

```bash
uv run gridalyn --help
uv run gridalyn project --help
uv run gridalyn doctor
```

Run a CI fixture study and put it through the checks. What each check answers,
and which to run when, is on
[Testing And Validation](../contributing/testing-and-validation.md):

```bash
uv run gridalyn project validate projects/minimal_grid_project
uv run gridalyn project plan projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project verify projects/minimal_grid_project
uv run gridalyn project regression projects/minimal_grid_project
```

`gridalyn project run --stage <id>` runs one stage and the stages it depends
on, and `--dry-run` writes the run manifest with every stage `planned` without
executing one. Scaffolding a study of your own starts at
[Quickstart](../start/quickstart.md) and continues in
[Build Your Own Project](../guides/build-your-own-project.md); the extension
loop (`extension new`, install, `extension validate`) is in
[Write An Extension](../guides/write-an-extension.md).

Plan a twin build without running it. `--dry-run` writes nothing on its own;
`--manifest` keeps the plan as a file outside the repository:

```bash
uv run gridalyn twin build --dry-run --skip-heavy --manifest /tmp/twin-plan.json
```

The full build, instance selection and `--capabilities` are covered in
[Build A Twin](../guides/build-a-twin.md).

## Commands that rewrite tracked files

`twin build` and the commands served by a workflow script work in
`instances/<instance>/digital_twin/`, and most of them write there. In a
checkout several files under `instances/default/` are committed, so a command
run on the `default` instance can leave the working tree dirty without
failing. Check `git status -- instances` afterwards, and point the output
elsewhere when you only want to look:

- **`gridalyn twin build` writes its build manifest** to
  `instances/<instance>/digital_twin/reports/digital_twin_build_manifest.json`,
  which is committed for `default`. Pass `--manifest <path>` to write it
  elsewhere. A `--dry-run` writes nothing unless `--manifest` is given.
- **`gridalyn dashboard catalog` rewrites the committed
  `instances/default/digital_twin/dashboard/catalog.json`** when the twin's
  generated artifacts are all present; when any are missing it refuses,
  naming each file and the command that produces it, and writes nothing.
  Pass `--out <path>` to write it elsewhere. The dashboard itself is covered
  in [Open The Dashboard](../guides/open-the-dashboard.md).

The other script-served commands that write committed reports, scenarios,
flexibility summaries or the semantic graph take an output option too; the
tables below list it.

## `gridalyn market` needs the `ops` extra

Every `market` subcommand, and `gridalyn market --help` itself, first checks
that the `ops` capability (`cvxpy`) imports. Without it the command prints
which extra is missing and exits with status 2 before parsing anything.
Installing extras is covered in [Installation](../start/installation.md).

## Command reference

Generated from the parsers by `tools/generate_cli_reference.py`;
`tests/test_cli_reference.py` fails when this section and the code disagree.
Edit the parsers and rerun the tool rather than editing the tables.

<!-- BEGIN GENERATED: tools/generate_cli_reference.py -->

### `gridalyn`

Console script: `gridalyn`.

| Command | Aliases | Console script | Purpose |
| --- | --- | --- | --- |
| `quickstart` |  |  | Scaffold and run a small power-flow study (first simulation in one command). |
| `validate` |  |  | Run the unified workspace validation ladder. |
| `doctor` |  |  | Inspect the local Gridalyn installation, workspace, projects, and optional capabilities. |
| `twin` | `dt`, `model` | `gridalyn-dt` | Build and inspect twin (network model) artifacts. |
| `project` | `projects` | `gridalyn-project` | Create, validate, plan, and run project workflows. |
| `market` | `flex`, `flexibility` | `gridalyn-flex` | Run flexibility-market and network-impact commands. |
| `semantic` | `semantics` | `gridalyn-semantic` | Build and validate the semantic graph. |
| `dashboard` | `dash` | `gridalyn-dashboard` | Generate and validate dashboard catalogs. |
| `platform` | `governance` | `gridalyn-platform` | Run platform governance and artifact checks. |
| `extension` | `extensions` | none | List, validate, and inspect installed extensions. |

#### `gridalyn quickstart`

Scaffold and run a small power-flow study (first simulation in one command).

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required | Directory to create the project in. |
| `--name` | text |  | Project name (defaults to the directory name). |

#### `gridalyn validate`

Run the unified workspace validation ladder.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |
| `--project` | text, repeatable |  | Project path to validate. May be provided multiple times. |
| `--check-project-artifacts` | flag |  | Also check required project reports and figures exist. |
| `--regression` | flag |  | Also run configured project regression checks. |

#### `gridalyn doctor`

Inspect the local Gridalyn installation, workspace, projects, and optional capabilities.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |
| `--json` | flag |  | Print the full machine-readable payload instead of the summary. |

### `gridalyn twin`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `build` | Build or plan the twin's artifacts. |  |
| `clip-buildings` | Clip building GeoJSON to a polygon. |  |
| `download-osm-buildings` | Download OSM building footprints with OSMnx. |  |
| `prepare-microsoft-buildings` | Convert local Microsoft building-footprint partitions to GeoJSON. |  |
| `scenarios` | Generate EV adoption scenarios over the twin | `ev_scenarios` |
| `timeseries` | Generate EV charging time series for the scenarios | `ev_timeseries` |
| `base` | Export the twin's base network model | `export_digital_twin_base` |
| `network-cache` | Build the twin's pandapower cache from its contract | `prepare_digital_twin_network_cache` |
| `building-models` | Generate building models for the twin's dwellings | `generate_digital_twin_building_models` |
| `scenario-models` | Generate per-scenario network models | `generate_digital_twin_scenario_models` |
| `powerflow` | Run power flow over the twin's EV scenarios | `run_digital_twin_ev_powerflow` |
| `verify-scenarios` | Check the generated EV scenarios for contract violations | `verify_digital_twin_ev_scenarios` |
| `verify-timeseries` | Check the generated EV time series for contract violations | `verify_digital_twin_ev_timeseries` |
| `verify-powerflow` | Check the EV power-flow results for contract violations | `verify_digital_twin_ev_powerflow` |
| `asset-registry` | Generate the twin's device and asset registry | `generate_digital_twin_asset_registry` |
| `overload-report` | Report MV/LV transformers loaded past their rating | `report_mv_lv_transformer_overloads` |
| `dashboard-catalog` | Generate the twin's dashboard catalog | `generate_digital_twin_dashboard_catalog` |

#### `gridalyn twin build`

Build or plan the twin's artifacts.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root containing instances/&lt;instance&gt;/digital_twin (default: current directory). |
| `--instance` | text | `default` | Named twin instance under &lt;root&gt;/instances/&lt;instance&gt;/digital_twin (default: default). Build any project's twin by selecting its instance. |
| `--capabilities` | text |  | Comma-separated capability layers to include (default: the legacy ev-hosting,flexibility build). Pass an empty value for a generic model-first build with no capability layers. |
| `--skip-heavy` | flag |  |  |
| `--include-network-impact` | flag |  |  |
| `--dry-run` | flag |  | Print the build plan and write nothing (no manifest either, unless --manifest names a destination). |
| `--continue-on-error` | flag |  |  |
| `--manifest` | path |  | Destination for the build manifest (default: &lt;root&gt;/instances/&lt;instance&gt;/digital_twin/reports/digital_twin_build_manifest.json; a --dry-run writes one only when this is given). |

Known `--capabilities` values: `agent_interaction`, `ev-hosting`, `flexibility`, `metering`. Any other name is refused with the known set in the error.

#### `gridalyn twin clip-buildings`

Clip building GeoJSON to a polygon.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--buildings-file` | path | required |  |
| `--polygon-file` | path | required |  |
| `--output-file` | path | required |  |

#### `gridalyn twin download-osm-buildings`

Download OSM building footprints with OSMnx.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--polygon-file` | path | required |  |
| `--output-file` | path | required |  |

#### `gridalyn twin prepare-microsoft-buildings`

Convert local Microsoft building-footprint partitions to GeoJSON.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--input-file` | path | required |  |
| `--output-file` | path | required |  |
| `--polygon-file` | path |  |  |
| `--limit` | int |  |  |

#### `gridalyn twin scenarios`

Generate EV adoption scenarios over the twin

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.digital_twin.ev_scenarios`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--out-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--config` | path | `configs/grid/config.json` |  |
| `--assignment-seed` | int |  |  |
| `--charger-kw` | float | `3.84` |  |
| `--c-soft-fraction` | float | `0.65` |  |

#### `gridalyn twin timeseries`

Generate EV charging time series for the scenarios

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.digital_twin.ev_timeseries`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--out-dir` | path | `instances/default/digital_twin/timeseries` |  |
| `--config` | path | `configs/grid/config.json` |  |
| `--start-timestamp` | text | `2024-01-01 00:00:00` |  |
| `--resolution-minutes` | int |  |  |

#### `gridalyn twin base`

Export the twin's base network model

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.export_digital_twin_base`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--adapter-id` | text |  |  |
| `--cache-dir` | path | `instances/default/digital_twin/cache` |  |
| `--config` | path |  |  |
| `--out-dir` | path | `instances/default/digital_twin/base` |  |
| `--footprints` | path |  | Building footprints to build from, overriding the instance contract. Without a contract or this option the export falls back to reading the instance cache. |
| `--source-dir` | path |  | Source directory for adapters such as cim_parquet. |

#### `gridalyn twin network-cache`

Build the twin's pandapower cache from its contract

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.prepare_digital_twin_network_cache`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--cache-dir` | path | `instances/default/digital_twin/cache` |  |
| `--footprints` | path |  | Footprints to build from, overriding the instance contract. |
| `--config` | path |  | Grid configuration, overriding the instance contract. |

#### `gridalyn twin building-models`

Generate building models for the twin's dwellings

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_building_models`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--out-dir` | path | `instances/default/digital_twin/models` |  |
| `--profile` | text | `north_america_residential_v1` |  |

#### `gridalyn twin scenario-models`

Generate per-scenario network models

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_scenario_models`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--models-dir` | path | `instances/default/digital_twin/models` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--out-dir` | path | `instances/default/digital_twin/models/scenarios` |  |
| `--scenario-id` | text |  |  |

#### `gridalyn twin powerflow`

Run power flow over the twin's EV scenarios

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.run_digital_twin_ev_powerflow`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenarios` | one or more text |  | Scenario ids to solve; defaults to every scenario in the index. Pass a subset for a smoke run. |
| `--scenarios-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--timeseries-dir` | path | `instances/default/digital_twin/timeseries` |  |
| `--cache-dir` | path | `instances/default/digital_twin/cache` |  |
| `--config` | path | `configs/grid/config.json` |  |
| `--start-timestamp` | text | `2024-01-01 00:00:00` |  |
| `--weather` | one of `snapshot`, `synthetic`, `auto`, `pvgis` | `snapshot` | Weather source for the building baseline. The default reads the digest-pinned TMY the instance contract declares, which is both real Quebec weather and reproducible. |

#### `gridalyn twin verify-scenarios`

Check the generated EV scenarios for contract violations

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.verify_digital_twin_ev_scenarios`:

The script parses no arguments.

#### `gridalyn twin verify-timeseries`

Check the generated EV time series for contract violations

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.verify_digital_twin_ev_timeseries`:

The script parses no arguments.

#### `gridalyn twin verify-powerflow`

Check the EV power-flow results for contract violations

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.verify_digital_twin_ev_powerflow`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenarios` | one or more text | `S0` `S1` |  |
| `--timeseries-dir` | path | `instances/default/digital_twin/timeseries` |  |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |

#### `gridalyn twin asset-registry`

Generate the twin's device and asset registry

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_asset_registry`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--out-path` | path | `instances/default/digital_twin/scenarios/asset_registry.parquet` |  |
| `--summary-path` | path | `instances/default/digital_twin/scenarios/asset_registry_summary.json` |  |
| `--soft-participation-rate` | float | `0.3` |  |
| `--soft-assignment-seed` | int | `3042` |  |
| `--prefer-existing-soft-participants` | flag |  | Use base buildings.cls_participant when it exists and has true values. |

#### `gridalyn twin overload-report`

Report MV/LV transformers loaded past their rating

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.report_mv_lv_transformer_overloads`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--timeseries-dir` | path | `instances/default/digital_twin/timeseries` |  |
| `--out` | path | `instances/default/digital_twin/reports/mv_lv_transformer_overload_report.json` |  |
| `--scenarios` | one or more text |  | Scenario ids; defaults to every scenario in the index. |
| `--scenarios-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--top-n` | int | `10` |  |

#### `gridalyn twin dashboard-catalog`

Generate the twin's dashboard catalog

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root (default: current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_dashboard_catalog`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenario-index` | path | `instances/default/digital_twin/scenarios/index.json` |  |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--powerflow-summary` | path | `instances/default/digital_twin/timeseries/powerflow_smoke_summary.json` |  |
| `--semantic-dir` | path | `instances/default/digital_twin/semantic` |  |
| `--scenario-assets` | path | `instances/default/digital_twin/scenarios/asset_registry.parquet` |  |
| `--observations-dir` | path | `instances/default/digital_twin/observations` |  |
| `--out` | path | `instances/default/digital_twin/dashboard/catalog.json` |  |

### `gridalyn project`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `init` | Scaffold a new study directory from a template |  |
| `validate` | Check project.yaml/workflow.yaml against the schema (is the contract well-formed?) |  |
| `plan` | Print the stage DAG in execution order without running anything |  |
| `run` | Execute the workflow stages and write governed artifacts |  |
| `prepare-workspace` | Create the outputs/ directories a study's stages write into |  |
| `status` | Report which artifacts and reports a study has produced so far |  |
| `regression` | Compare results against baselines/results_baseline.json (did the numbers move?) |  |
| `sense-check` | Run the study's objective plausibility checks (do the numbers make sense?) |  |
| `verify` | Run the ladder: contract + artifact status + sense checks, as one payload. Excludes regression |  |
| `list` | List the studies found under a workspace root |  |
| `verify-all` | Run the verify ladder over every study under a workspace root |  |
| `catalog` | Write each study's dashboard catalog next to the study |  |

#### `gridalyn project init`

Scaffold a new study directory from a template

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | `.` |  |
| `--name` | text |  |  |
| `--template` | one of `grid-study`, `minimal`, `powerflow-demo` | `minimal` | Project scaffold template to create. |
| `--list-templates` | flag |  | List available templates and exit. |
| `--force` | flag |  |  |

| Template | Scaffolds |
| --- | --- |
| `grid-study` | Contract plus a summary-report stage wired for verification. |
| `minimal` | Smallest valid project contract with a placeholder workflow. |
| `powerflow-demo` | Runnable IEEE 33-bus power-flow study producing a figure and a governed report (requires only base dependencies, e.g. pandapower). |

#### `gridalyn project validate`

Check project.yaml/workflow.yaml against the schema (is the contract well-formed?)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |
| `--check-artifacts` | flag |  |  |

#### `gridalyn project plan`

Print the stage DAG in execution order without running anything

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |

#### `gridalyn project run`

Execute the workflow stages and write governed artifacts

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |
| `--dry-run` | flag |  |  |
| `--manifest-path` | text |  |  |
| `--stage` | text, repeatable |  | Run only this stage and its dependencies (repeatable). |
| `--quiet` | flag |  | Disable per-stage progress output. |

#### `gridalyn project prepare-workspace`

Create the outputs/ directories a study's stages write into

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |

#### `gridalyn project status`

Report which artifacts and reports a study has produced so far

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |
| `--check-artifacts` | flag |  |  |

#### `gridalyn project regression`

Compare results against baselines/results_baseline.json (did the numbers move?)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |

#### `gridalyn project sense-check`

Run the study's objective plausibility checks (do the numbers make sense?)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |
| `--no-write` | flag |  | Run checks without writing outputs/reports/project_sense_check_report.json. |

#### `gridalyn project verify`

Run the ladder: contract + artifact status + sense checks, as one payload. Excludes regression

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `project` | text | required |  |
| `--no-write` | flag |  | Run verification without writing outputs/reports/project_sense_check_report.json. |

#### `gridalyn project list`

List the studies found under a workspace root

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |

#### `gridalyn project verify-all`

Run the verify ladder over every study under a workspace root

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |
| `--write` | flag |  | Write project sense-check reports. |

#### `gridalyn project catalog`

Write each study's dashboard catalog next to the study

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |
| `--check` | flag |  | Report catalogs that no longer match their study; write nothing. |

### `gridalyn market`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `providers` | Generate the flexibility providers available on the twin | `generate_digital_twin_flexibility_providers` |
| `surrogate` | Fit the network-impact surrogate the clearing decides on | `generate_network_impact_surrogate` |
| `locational-clearing` | Clear flexibility locationally against network constraints | `generate_locational_flexibility_clearing` |
| `network-impact-catalog` | Generate the network-impact dashboard catalog | `generate_network_impact_dashboard_catalog` |

#### `gridalyn market providers`

Generate the flexibility providers available on the twin

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_flexibility_providers`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--models-dir` | path | `instances/default/digital_twin/models` |  |
| `--out-dir` | path | `instances/default/digital_twin/flexibility` |  |

#### `gridalyn market surrogate`

Fit the network-impact surrogate the clearing decides on

Passed through to `gridalyn.projects.workflows.scripts.generate_network_impact_surrogate`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenario-id` | text | `S4` |  |
| `--provider-registry` | path | `instances/default/digital_twin/flexibility/provider_registry.parquet` |  |
| `--sensitivity` | path | `instances/default/digital_twin/flexibility/network_sensitivity.parquet` |  |
| `--out-dir` | path | `instances/default/digital_twin/flexibility` |  |

#### `gridalyn market locational-clearing`

Clear flexibility locationally against network constraints

Passed through to `gridalyn.projects.workflows.scripts.generate_locational_flexibility_clearing`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` | Workspace root containing instances/default/digital_twin (default: current directory). |
| `--provider-path` | path |  |  |
| `--impact-path` | path |  |  |
| `--overload-report-path` | path |  |  |
| `--transformers-path` | path |  |  |
| `--transformer-timeseries-path` | path |  |  |
| `--out-dir` | path |  |  |
| `--report-path` | path |  |  |
| `--scenario-id` | text | `S4` |  |
| `--clearing-method` | one of `surrogate`, `topology` | `surrogate` |  |
| `--constraint-id` | text, repeatable |  |  |
| `--top-constraints` | int | `3` |  |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

#### `gridalyn market network-impact-catalog`

Generate the network-impact dashboard catalog

Passed through to `gridalyn.projects.workflows.scripts.generate_network_impact_dashboard_catalog`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenario-index` | path | `instances/default/digital_twin/scenarios/index.json` |  |
| `--out` | path | `instances/default/digital_twin/flexibility/network_impact_catalog.json` |  |

### `gridalyn semantic`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `build` | Generate the semantic graph from the twin | `generate_digital_twin_semantic_graph` |
| `validate` | Check the generated semantic graph for contract violations | `validate_digital_twin_semantics` |

#### `gridalyn semantic build`

Generate the semantic graph from the twin

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_semantic_graph`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--profile` | text | `north_america` |  |
| `--root` | path | `.` |  |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |
| `--flexibility-dir` | path | `instances/default/digital_twin/flexibility` |  |
| `--timeseries-dir` | path | `instances/default/digital_twin/timeseries` |  |
| `--out-dir` | path | `instances/default/digital_twin/semantic` |  |
| `--interaction-log` | path | `instances/default/digital_twin/operations/message_log.parquet` | Message log the agent_interaction capability reads. A path that does not exist is an empty log, so the default is safe for a twin that has run no protocol. |
| `--metering-points` | path | `instances/default/digital_twin/observations/metering_points.parquet` | Metering-point table the metering capability reads. A path that does not exist is an empty table, so the default is safe for a twin nobody meters. |
| `--semantic-capabilities` | zero or more text |  | Declared semantic capabilities (e.g. 'flexibility'). Defaults to flexibility for backwards compatibility; pass an empty list for a model-first core-only graph. |

#### `gridalyn semantic validate`

Check the generated semantic graph for contract violations

Passed through to `gridalyn.projects.workflows.scripts.validate_digital_twin_semantics`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path | `.` |  |
| `--semantic-dir` | path | `instances/default/digital_twin/semantic` |  |
| `--scenario-dir` | path | `instances/default/digital_twin/scenarios` |  |

### `gridalyn dashboard`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `catalog` | Generate the dashboard catalog from the twin | `generate_digital_twin_dashboard_catalog` |
| `verify` | Check the dashboard's catalog against the twin it describes | `verify_dashboard_consistency` |

#### `gridalyn dashboard catalog`

Generate the dashboard catalog from the twin

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path |  | Workspace root (default: GRIDALYN_WORKSPACE_ROOT, else the current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.generate_digital_twin_dashboard_catalog`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--scenario-index` | path | `instances/default/digital_twin/scenarios/index.json` |  |
| `--base-dir` | path | `instances/default/digital_twin/base` |  |
| `--powerflow-summary` | path | `instances/default/digital_twin/timeseries/powerflow_smoke_summary.json` |  |
| `--semantic-dir` | path | `instances/default/digital_twin/semantic` |  |
| `--scenario-assets` | path | `instances/default/digital_twin/scenarios/asset_registry.parquet` |  |
| `--observations-dir` | path | `instances/default/digital_twin/observations` |  |
| `--out` | path | `instances/default/digital_twin/dashboard/catalog.json` |  |

#### `gridalyn dashboard verify`

Check the dashboard's catalog against the twin it describes

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | path |  | Workspace root (default: GRIDALYN_WORKSPACE_ROOT, else the current directory). |
| `--instance` | text | `default` | Named twin instance (default: GRIDALYN_INSTANCE or 'default'). |

Passed through to `gridalyn.projects.workflows.scripts.verify_dashboard_consistency`:

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--catalog` | path | `instances/default/digital_twin/dashboard/catalog.json` |  |

### `gridalyn platform`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `check-artifacts` | Check Git artifact policy and the minimal demo dataset contract. |  |

#### `gridalyn platform check-artifacts`

Check Git artifact policy and the minimal demo dataset contract.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--root` | text | `.` |  |
| `--summary-only` | flag |  |  |

### `gridalyn extension`

| Subcommand | Purpose | Pass-through script |
| --- | --- | --- |
| `list` | List installed extensions without importing them (awareness). |  |
| `validate` | Load declared extension IDs and report resolution (declared-only). |  |
| `new` | Scaffold a conformant extension package. |  |

#### `gridalyn extension list`

List installed extensions without importing them (awareness).

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--group` | text | `gridalyn.extensions` |  |
| `--json` | flag |  | Emit JSON. |

#### `gridalyn extension validate`

Load declared extension IDs and report resolution (declared-only).

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--group` | text | `gridalyn.extensions` |  |
| `extension_ids` | zero or more text |  | Declared extension IDs to resolve (at least one required). |

#### `gridalyn extension new`

Scaffold a conformant extension package.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `name` | text | required | Extension ID / package name. |
| `--role` | text | `powerflow_backend` | Role the extension serves (default: powerflow_backend). |
| `--target` | text |  | Directory to write the package into (default: current directory). |
| `--force` | flag |  | Overwrite an already-existing package directory. |

<!-- END GENERATED -->

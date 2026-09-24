# Interfaces

## What problem this layer solves

Every layer below this one produces something governed — a network snapshot,
a settled market, a completed study run — and `interfaces` is the only layer
whose job is to let a person reach it: the `gridalyn` CLI, the reporting
helpers, visualization helpers, and the dashboard SPA. It never duplicates
platform logic; if a dashboard needs a number the platform hasn't computed,
that number belongs one layer down, not recomputed here.

## The vocabulary

- **The root CLI dispatcher** (`gridalyn/interfaces/cli/gridalyn.py`) — one
  entry point, `gridalyn`, that runs three top-level commands itself and
  delegates everything else to a domain CLI by name or alias.
- **`DOMAIN_MODULES`** — the seven domains the CLI dispatches to, with their
  aliases and help text (see [The contract](#the-contract)).
- **Reporting helpers** (`gridalyn.interfaces.reporting`) — canonical-report
  builders and JSON helpers (`canonical_report`, `write_report`, `write_json`,
  `load_json`, `report_input`, `artifact_references`, `sha256_file`,
  `relpath`, `now_iso`), the twin report builder
  `build_digital_twin_reports`, and `dispatch_timeseries_metrics`. It also
  re-exports `build_dashboard_catalog` and `write_dashboard_catalog`, which
  live in `gridalyn.projects.dashboard_catalog`; the old
  `gridalyn.interfaces.reporting.dashboard_catalog` path is a deprecated shim
  that warns on import.
- **Visualization helpers** (`gridalyn.interfaces.viz`) — `GridPlotter`, a
  Folium map of a synthetic network, and the matplotlib helpers
  `apply_hour_axis`, `format_hour_label`, `save_figure_pair` and
  `style_timeseries_axis`.
- **The dashboard SPA** (`dashboard/`) — a browser application that consumes
  generated catalogs and reports; it is a separate frontend project, not part
  of the `gridalyn` Python package.
- **Extensions** — externally-registered components that participate in a
  per-role registry without editing `gridalyn`; see
  [Write An Extension](../guides/write-an-extension.md).

## The contract

The root CLI is a thin dispatcher. It handles `quickstart`, `validate` and
`doctor` itself; every other command names a domain from `DOMAIN_MODULES` and
is handed to that domain's module:

| Domain | Aliases | Console script | Purpose |
| --- | --- | --- | --- |
| `twin` | `dt`, `model` | `gridalyn-dt` | Build and inspect twin (network model) artifacts. |
| `project` | `projects` | `gridalyn-project` | Create, validate, plan, and run project workflows. |
| `market` | `flex`, `flexibility` | `gridalyn-flex` | Run flexibility-market and network-impact commands. |
| `semantic` | `semantics` | `gridalyn-semantic` | Build and validate the semantic graph. |
| `dashboard` | `dash` | `gridalyn-dashboard` | Generate and validate dashboard catalogs. |
| `platform` | `governance` | `gridalyn-platform` | Run platform governance and artifact checks. |
| `extension` | `extensions` | — | List, validate, and inspect installed extensions. |

Each domain subcommand either calls a lower-layer function — `gridalyn project
run` calls `gridalyn.projects.api.run_workflow`, `gridalyn platform` calls the
foundation artifact-policy check — or runs a packaged workflow script under
`gridalyn.projects.workflows.scripts`, which is how every `market`,
`semantic` and `dashboard` subcommand and part of `twin` work. The CLI modules hold argument
parsing, not platform logic. `gridalyn market` checks for the `ops` extra
before it parses anything, so without that extra even `gridalyn market --help`
exits 2 with the missing-capability message. Every command and flag is in the
[CLI Reference](../reference/cli.md).

## Using it

```bash
uv run gridalyn --help
```

The domains listed in that output are read straight from `DOMAIN_MODULES` —
confirm the source matches what a user actually sees:

```python
from gridalyn.interfaces.cli.gridalyn import DOMAIN_MODULES

print(sorted(DOMAIN_MODULES))
```
```text
['dashboard', 'extension', 'market', 'platform', 'project', 'semantic', 'twin']
```

## Verifying it

```bash
uv run gridalyn twin --help
uv run gridalyn project --help
```

Both commands exit 0 and print the subcommands their domain module actually
registers — which is the same mechanism this page's own example used, not a
separate one documented only in prose.

## Where this sits

`interfaces` sits on [Projects](projects.md), and through it on every layer
below — it is the top of the stack, the layer a person actually touches. There
is nothing above it in the component walk. From here, [Guides](../guides/overview.md)
covers task-shaped how-tos, and [Reference](../reference/overview.md) covers
the CLI, the Python API, and the YAML contracts in full.

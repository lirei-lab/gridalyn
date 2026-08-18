# Interfaces

## What problem this layer solves

Every layer below this one produces something governed — a network snapshot,
a settled market, a completed study run — and `interfaces` is the only layer
whose job is to let a person reach it: the `gridalyn` CLI, the reporting
catalogs, visualization helpers, and the dashboard SPA. It consumes governed
artifacts and never duplicates platform logic; if a dashboard needs a number
the platform hasn't computed, that number belongs one layer down, not
recomputed here.

## The vocabulary

- **The root CLI dispatcher** (`gridalyn/interfaces/cli/gridalyn.py`) — one
  entry point, `gridalyn`, that delegates to domain CLIs by name or alias.
- **`DOMAIN_MODULES`** — the seven domains the CLI actually dispatches to:
  `twin` (aliases `dt`, `model`), `project` (`projects`), `market` (`flex`,
  `flexibility`), `semantic` (`semantics`), `dashboard` (`dash`), `platform`
  (`governance`), `extension` (`extensions`).
- **Reporting catalogs** — the dashboard-ready summaries built from governed
  report and manifest artifacts, never from a notebook or an ad hoc script.
- **The dashboard SPA** (`dashboard/`) — a browser application that consumes
  generated catalogs and reports; it is a separate frontend project, not part
  of the `gridalyn` Python package.
- **Extensions** — externally-registered components that participate in a
  per-role registry without editing `gridalyn`; see
  [Write An Extension](../guides/write-an-extension.md).

## The contract

Console scripts are the only sanctioned entry points a user or CI job should
call — `gridalyn`, `gridalyn-dashboard`, `gridalyn-dt`, `gridalyn-flex`,
`gridalyn-platform`, `gridalyn-project`, `gridalyn-semantic`. Each domain CLI
under `gridalyn/interfaces/cli/` reads governed artifacts (reports, manifests,
catalogs) that a lower layer already wrote; it does not open a project's raw
YAML or reach into `outputs/` with a hand-built path.

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

# Python API Reference

This page is generated from the source docstrings by `mkdocstrings`. It documents
the **layer facades** — the eight modules that make up Gridalyn's supported import
surface:

| Facade | Import it for |
| --- | --- |
| [`gridalyn`](#gridalyn) | The flat top-level convenience surface. |
| [`gridalyn.foundation`](#gridalyn.foundation) | Governance, the report contract, capabilities, workspaces. |
| [`gridalyn.twin`](#gridalyn.twin) | Network topology, ingest adapters, the semantic graph. |
| [`gridalyn.assets`](#gridalyn.assets) | Building, load, EV, DER modeling and synthetic data generation. |
| [`gridalyn.simulation`](#gridalyn.simulation) | Power-flow builders, scenarios, network-impact analytics. |
| [`gridalyn.operations`](#gridalyn.operations) | Flexibility-market clearing, dispatch, settlement, KPIs. |
| [`gridalyn.projects`](#gridalyn.projects) | The `StudyProject` contract, workflow runner, regression. |
| [`gridalyn.interfaces`](#gridalyn.interfaces) | CLI entry points, reporting catalogs, visualization. |

## Scope of this page

Import from a facade, not from a private submodule. `gridalyn.simulation` is a
supported import path; `gridalyn.simulation.simulators.powerflow.builder` is an
implementation detail that may move between releases.

Only the facades are rendered here. **Per-symbol reference pages for every
exported name are deliberately out of scope** — see
[Not covered here](#not-covered-here) at the bottom of the page.

## How the lazy facades are rendered

Every facade defines its public names in a `_LAZY_EXPORTS` map and resolves them
on first access through a module-level `__getattr__`, so that `import gridalyn`
stays cheap and optional heavy dependencies (pandapower, lightsim2grid) are never
imported until something actually needs them. See
[Module Boundaries](../contributing/module-boundaries.md) for why.

A consequence is that the exported names do not exist in the module namespace
until they are touched, so **static** analysis of these files finds no members at
all. The `mkdocstrings` python handler is therefore configured with
`force_inspection: true`: it imports each facade and reads its members, which
resolves every entry in `_LAZY_EXPORTS`. Each facade also defines a `__dir__`, so
`dir()` and `inspect.getmembers` report the same names the documentation does.

All eight facades are introspectable this way; none had to be omitted. A facade
entry that is a plain re-export or alias resolves to the symbol it points at, so
it is documented once, under its owning definition.

Only names carrying a docstring are shown. **213 of the 220 names exported by the
seven layer facades render; 7 do not**, because the function they ultimately
resolve to has no docstring yet:

| Facade | Name |
| --- | --- |
| `gridalyn.twin` | `build_semantic_graph`, `validate_semantic_graph` |
| `gridalyn.interfaces` | `build_digital_twin_reports`, `canonical_report`, `write_dashboard_catalog`, `write_json`, `write_report` |

They are importable and supported; they are simply undocumented, and they will
appear here as soon as they are described at their definition site.

---

::: gridalyn
    options:
      members: false

The top-level facade re-exports a curated subset of the layer facades below, so a
script can do `from gridalyn import build_ieee33_benchmark_feeder` without
knowing which layer owns it. Its 51 names are documented under their owning
layer rather than repeated here.

::: gridalyn.foundation

::: gridalyn.twin

::: gridalyn.assets

::: gridalyn.simulation

::: gridalyn.operations

::: gridalyn.projects

::: gridalyn.interfaces

---

## Not covered here

- **Per-symbol pages.** Dedicated pages for each of the ~287 exported targets are
  a separate piece of work, tracked as a follow-up. This page enables the
  machinery and covers the facades; exhaustive pages are a project of their own.
- **Private submodules.** Anything under a facade that is not in its
  `_LAZY_EXPORTS` map is internal and carries no stability promise.
- **Command-line usage.** See the [CLI Reference](cli.md).
- **YAML contracts.** See the [YAML Reference](workflow-yaml.md)
  and [Report Schemas](report-schema.md).

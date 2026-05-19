# Data And Artifact Model

Gridalyn is artifact-driven. A workflow should leave behind enough structured
evidence for another user, dashboard, script, or future service to understand
what model was used, what scenario was run, what outputs were produced, and
which validation checks passed.

## Source Layers

| Layer | Typical path | Purpose |
| --- | --- | --- |
| Source data | `configs/`, project `inputs/`, external data folders | Raw or configured inputs used to build the model. |
| Digital twin base | `instances/default/digital_twin/base/` | Static network and asset model snapshots. |
| Scenario layer | `instances/default/digital_twin/scenarios/`, project scenario outputs | Scenario metadata, asset roles, adoption levels, and controllability assumptions. |
| Time-series layer | `instances/default/digital_twin/timeseries/`, project `outputs/data/` | Simulation, forecast, load, EV, and dispatch profiles. |
| Flexibility layer | `instances/default/digital_twin/flexibility/`, project flexibility outputs | Providers, aggregators, offers, clearing decisions, dispatch, settlement, and network-impact artifacts. |
| Semantic layer | `instances/default/digital_twin/semantic/` | Ontology-aligned nodes, edges, profiles, and validation reports. |
| Reports | `instances/default/digital_twin/reports/`, project `outputs/reports/` | Stable JSON contracts consumed by dashboards, audits, tests, and external review. |
| Manifests | project `outputs/manifests/` | Run-level lineage, stage status, artifact inventory, and regression metadata. |

## Contract Rules

- Every generated report should include lineage to model version, scenario, run,
  inputs, and source files when possible.
- Large binary outputs should be reproducible from tracked inputs and scripts
  rather than committed directly.
- Project artifacts should live under the project that generated them.
- Shared digital twin artifacts should be promoted only when they are useful to
  more than one project or application.
- The dashboard should load catalog and report artifacts instead of reaching
  into project scripts.

## Practical Consequence

When adding a new workflow stage, decide first which artifact it produces:

| Stage type | Preferred output |
| --- | --- |
| Model generation | Parquet plus metadata JSON |
| Scenario generation | JSON manifest plus asset registry tables |
| Simulation | Time-series Parquet plus validation report |
| Market operation | Provider, clearing, dispatch, settlement, and scorecard JSON/Parquet |
| Figure generation | Figures under project `outputs/figures` plus a report or manifest pointing to them |
| Dashboard publishing | Catalog JSON referencing existing reports and data |

This keeps Gridalyn usable as a platform rather than a collection of one-off
scripts.

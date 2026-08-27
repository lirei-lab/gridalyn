# Naming Conventions

The public SDK uses verb prefixes consistently. Knowing them makes the API
predictable without reading source code.

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `load_*` | Read a declaration from a project contract (`project.yaml`) or file and return a typed object. No side effects. | `load_project`, `load_radial_feeder_spec`, `load_standard_powerflow_scenarios` |
| `build_*` | Construct an in-memory object (network, model, payload) from inputs. No files written. | `build_ieee33_benchmark_feeder`, `build_radial_pandapower_feeder`, `build_pandapower_summary` |
| `run_*` | Execute something with side effects on the passed object or the workspace. | `run_workflow`, `run_standard_powerflow_scenario`, `run_der_voltage_dispatch` |
| `write_*` | Emit an artifact (report, figure, table) to disk and return its path or payload. | `write_report`, `write_voltage_profile_figure`, `write_pandapower_element_tables` |
| `validate_*` / `verify_*` | Check a contract or result; `validate_*` returns structured findings, `project_verify` aggregates them into one pass/fail payload. | `validate_project`, `project_verify` |

Two domain terms that appear throughout:

- **feeder** — a single radial distribution circuit; builders that return one
  pandapower network use this term.
- **network** — the broader grid model, including synthesized multi-level
  topologies (`build_synthetic_network_from_geojson`).

When adding new public helpers, pick the prefix that matches the behavior
above rather than inventing a new one.

## Workflow stage ids

The same rule applies to the `id` of a stage in a study's `workflow.yaml`,
because a workflow read top to bottom is the clearest statement of what a study
does. Measured across the 8 studies, 45 of 59 stage ids already follow one:

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `prepare_*` | Create the workspace a later stage writes into. No results. | `prepare_workspace` |
| `build_*` | Construct the model the study runs on. | `build_der_feeder`, `build_synthetic_feeder`, `build_rl_feeder` |
| `generate_*` | Produce input data the study consumes. | `generate_building_footprints`, `generate_operational_scenarios` |
| `run_*` | Execute the study's mechanism — the thing it exists to do. | `run_minimal_powerflow`, `run_realtime_prosumer_market`, `run_daily_timeseries` |
| `analyze_*` | Derive a result from what a `run_*` stage produced. | `analyze_congestion_annual`, `analyze_credibility` |
| `train_*` | Fit a model the study will then evaluate. | `train_rl_voltage_agent`, `train_forecaster` |
| `export_*` | Publish a result outward, typically to the twin. | `export_twin_network_model` |
| `validate_*` | Check the study's own output before it is believed. | `validate_project_outputs` |

Read in that order the prefixes are the study's own sequence: prepare, build or
generate the model, run the mechanism, analyze the result, validate it, export
it.

**Known deviations, and why they are still here.** Ten stage ids predate this
convention. One — `solve_voltage_optimization` — was renamed to `run_*` when
the convention was written. The remaining nine are not a backlog anyone should
clear casually:

- **Six in `admm_thermal_consensus`** (`make_figures`, `make_uncertainty_figure`,
  `make_comparison_figure`, `uncertainty_sweep`, `imputer_comparison`,
  `comfort_validation`). A stage id here also names its Python module, because
  stages run as `{python} -m projects.<study>.scripts.pipeline.<module>`. That
  study's Phase 19 migration deliberately preserved module identities because
  its cached `imputer.pkl` carries a module path inside it, and its own README
  records that decision. Renaming these is a deliberate act against a
  documented one, and the cache on disk means a warm re-run would not even
  detect a mistake.
- **Three in `ev_hosting_flex`** (`compute_congestion_annual`,
  `apply_curtailment_contracts`, `compute_curtailment_economics`). Each is
  imported by other pipeline scripts and named in `docs/reference/workflow-yaml.md`,
  `docs/development/report-contract-audit.md`, the annual byte-stability seal
  test and the report-contract classifier — nine files for the widest of the
  three. The two documentation files sit inside the instruction ledger's corpus
  and the path checker's scope, so a rename is a documentation migration as
  much as a code one.

New stages take the prefixes above. Existing ones move only when someone is
already changing that study for another reason.

# Naming Conventions

The public SDK uses verb prefixes consistently. Knowing them makes the API
predictable without reading source code.

The table below describes the verbs the SDK **actually uses**, not an aspiration
for it. `tools/verb_prefixes.py` measures the gap: it reads the prefixes out of
this page, AST-scans every public module-level function under `gridalyn/`, and
reports the compliance rate. Run it before adding a verb:

```bash
python tools/verb_prefixes.py          # report
python tools/verb_prefixes.py --check  # fail if an undocumented verb is established
```

`--check` fails once an undocumented prefix reaches three public functions,
because at that point it is a verb the SDK uses and this page does not
acknowledge. An ignored convention stops being one.

## Reading and constructing

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `load_*` | Read a declaration from a project contract (`project.yaml`) or file and return a **typed** object. No side effects. | `load_project`, `load_radial_feeder_spec`, `load_standard_powerflow_scenarios` |
| `read_*` | Read a file into a plain structure (dict, DataFrame). The untyped sibling of `load_*`: use it when there is no contract dataclass to return. | `read_yaml`, `read_json_report` |
| `build_*` | Construct an in-memory object from inputs already in hand. Deterministic; writes no files. | `build_ieee33_benchmark_feeder`, `build_radial_pandapower_feeder`, `build_report` |
| `generate_*` | **Synthesize** data that did not previously exist, from a seed and a model. Distinct from `build_*`: the output is sampled, so the seed is part of the contract. | `generate_residential_load_profiles`, `generate_ev_scenarios` |

## Executing and transforming

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `run_*` | Execute the mechanism, with side effects on the passed object or the workspace. | `run_workflow`, `run_standard_powerflow_scenario`, `run_der_voltage_dispatch` |
| `apply_*` | Transform a structure passed in, by a stated rule, and return the transformed form. | `apply_hour_axis`, `apply_spatial_cls`, `apply_locational_selections` |
| `prepare_*` | Create the workspace, cache or directory a later call writes into. Returns no results. | `prepare_project_workspace`, `prepare_synthetic_topology_cache` |

## Emitting

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `write_*` | Emit an artifact to **disk** and return its path or payload. | `write_report`, `write_voltage_profile_figure`, `write_pandapower_element_tables` |
| `emit_*` | Produce records or rows **in memory** for a downstream consumer. The no-disk sibling of `write_*`. | `emit_flexibility_asset_nodes`, `emit_provider_registry`, `emit_scenarios` |
| `summarize_*` | Reduce a structure to the compact payload a report or scorecard carries. | `summarize_asset_registry`, `summarize_network_constraints` |
| `describe_*` | Return a component's self-description — its id, capability and stated bounds. | `describe_powerflow_backend`, `describe_surrogate`, `describe_policy` |

## Checking

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `validate_*` / `verify_*` | Check a contract or result; `validate_*` returns structured findings, `project_verify` aggregates them into one pass/fail payload. | `validate_project`, `project_verify` |
| `measure_*` | Quantify a stated property and return the number with its bound. Use this rather than `calculate_*`/`compute_*`. | `measure_error_bound`, `measure_local_voltage_sensitivity` |

## Resolving and registering

| Prefix | Meaning | Examples |
| --- | --- | --- |
| `register_*` | Add an entry to a registry, mutating process-level state. | `register_extension`, `register_powerflow_backend_extension` |
| `resolve_*` | Turn an id or a reference into the thing it names, raising when it does not resolve. | `resolve_declared_extensions`, `resolve_powerflow_backend` |
| `default_*` | Return the conventional default instance for a role. Noun-shaped by design — there is no action, only a choice of default. | `default_surrogate_registry`, `default_manifest_path` |
| `select_*` | Choose from candidates already in hand, returning one or a subset. | `select_cold_day`, `select_peak_load_day`, `select_archetype` |
| `find_*` | Search the filesystem or graph for something whose location is not known in advance. | `find_workspace_root`, `find_project_root` |
| `list_*` | Enumerate what is available, without resolving any of it. | `list_available_datasets`, `list_installed_extensions` |
| `parse_*` | Turn text or argv into structured values. No IO beyond the input. | `parse_args` |

## Prefixes that are not helpers

These are excluded from the compliance measurement, and no behaviour should be
inferred from them. They are acknowledged so a contributor meeting one in the
source does not read it as a verb.

| Prefix | What it is |
| --- | --- |
| `main` | A CLI entry point, one per module in `gridalyn/interfaces/cli/`. Takes no verb contract. Excluded by name, not by prefix. |
| `parse_args` | argparse's own companion to `main`, repeated once per CLI module by that library's shape rather than by choice. Excluded with it. |
| `handle_*` | A CLI subcommand handler, confined to `gridalyn/interfaces/cli/`. Do not use it in an SDK layer. |

**Noun-prefixed families.** Four families lead with the *domain* and let the
verb follow. They are coherent where they are, and each is closed: extend one
only inside its own module, and do not start a fifth.

| Family | Where | Shape |
| --- | --- | --- |
| `project_*` | `gridalyn/projects/api.py`, `loader.py`, `scripting.py` | The domain facade: `project_verify`, `project_sense_check`, `project_script` |
| `model_*` | `gridalyn/twin/adapters/authority.py` | The CGMES model-authority surface: `model_authority_set`, `model_profile` |
| `scenario_*` | `gridalyn/simulation` scenario helpers | Views over a scenario: `scenario_frame`, `scenario_ids`, `scenario_to_record` |
| `workspace_*` | `gridalyn/foundation/platform/workspace.py` | The `<noun>_from_<source>` alternate-constructor idiom: `workspace_from_path`, `workspace_from_root` |

## Prefixes deliberately not wanted

Named here so a contributor does not have to infer them from absence. Each is
still present in a handful of places that predate this page; those move when
someone is already changing that file.

| Prefix | Why not | Use instead |
| --- | --- | --- |
| `get_*` | Says nothing about cost or side effects — it covers a dict lookup and a network read equally. | `load_*`, `read_*`, `resolve_*` or `find_*`, whichever states what actually happens |
| `make_*` | A synonym of two verbs that already carry a distinction this one loses: deterministic construction versus seeded synthesis. | `build_*` or `generate_*` |
| `calculate_*` / `compute_*` | Two spellings of one idea, and neither says whether the result is a measurement or a derived payload. | `measure_*` for a quantified property, `build_*` for a derived structure |
| `process_*` / `do_*` | Contentless. | The verb for what is actually being done |

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

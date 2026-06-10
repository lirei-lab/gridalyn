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

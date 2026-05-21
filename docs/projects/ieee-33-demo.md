# IEEE 33-Bus Demo

`projects/ieee_33_bus_demo` is a compact demo project for Gridalyn's project
workflow contract. It uses Gridalyn's IEEE 33-bus benchmark feeder contract,
which wraps the common 33-bus radial distribution benchmark behind the SDK.

## Why This Demo Exists

Large flexibility workflows are too heavy for a first technical smoke test.
The IEEE 33-bus demo gives developers and utility users a smaller project that
still exercises:

- project manifests;
- pandapower execution;
- tabular output generation;
- JSON report contracts;
- figure generation;
- artifact validation.

In the documentation, this is the first official project to run. It shows the
platform mechanics on a known feeder before introducing richer scenario
generation, market clearing, topology-aware flexibility, and dashboard
catalogs.

## Run It

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
uv run gridalyn project status projects/ieee_33_bus_demo --check-artifacts
```

Expected generated artifacts:

```text
projects/ieee_33_bus_demo/outputs/data/buses.csv
projects/ieee_33_bus_demo/outputs/data/lines.csv
projects/ieee_33_bus_demo/outputs/data/loads.csv
projects/ieee_33_bus_demo/outputs/data/scenarios.csv
projects/ieee_33_bus_demo/outputs/data/scenario_results.csv
projects/ieee_33_bus_demo/outputs/data/scenario_voltage_profiles.csv
projects/ieee_33_bus_demo/outputs/reports/ieee33_powerflow_report.json
projects/ieee_33_bus_demo/outputs/reports/ieee33_scenario_comparison_report.json
projects/ieee_33_bus_demo/outputs/figures/ieee33_voltage_profile.png
projects/ieee_33_bus_demo/outputs/figures/ieee33_scenario_voltage_comparison.png
projects/ieee_33_bus_demo/outputs/manifests/project_run_manifest.json
```

## What It Demonstrates

The workflow has two stages:

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `run_ieee33_powerflow` | Builds the Gridalyn IEEE 33-bus benchmark feeder, runs a power flow, exports tables, writes a report, and plots the voltage profile. |
| `generate_operational_scenarios` | Applies deterministic load, PV, and EV scenarios; runs power flow for each; writes comparison tables, report, and figure. |

The generated report records:

- bus, line, load, and slack counts;
- total active and reactive load;
- line losses;
- minimum and maximum voltage;
- maximum line loading;
- pandapower convergence status.

This gives a small but real example of the core Gridalyn loop:

```text
model -> simulation -> artifacts -> report -> validation
```

## Operational Scenarios

The demo includes five deterministic scenarios:

| Scenario | Meaning |
| --- | --- |
| `baseline` | Original IEEE 33-bus feeder. |
| `load_growth_20` | Uniform 20 percent demand growth. |
| `pv_midday` | Distributed PV at selected downstream buses. |
| `ev_evening_peak` | EV charging demand at selected downstream buses. |
| `pv_plus_ev` | Mixed PV and EV condition. |

The scenario comparison report summarizes the best and worst voltage cases,
the voltage range, maximum line loading, and voltage violation counts. This is
the first operational bridge in the demo: it compares network states rather
than only exporting the base feeder.

## How To Extend It

Use this project as the starting point for small experiments:

| Extension | Where to add it |
| --- | --- |
| Add load growth or DER scenarios | a Gridalyn scenario contract and a thin project workflow stage |
| Add operational dispatch records | `outputs/operations/` and a platform operation run report |
| Add semantic graph export | a new stage that writes graph nodes and edges |
| Add dashboard catalog metadata | a new stage that materializes dashboard-ready JSON |

Reusable logic belongs in `gridalyn/`; project scripts should only bind the
demo workflow to concrete paths and parameters.

## Natural Next Extension

The next useful extension is a more explicit operational decision layer:

```text
baseline IEEE 33-bus feeder
  -> deterministic load/PV/EV scenarios
  -> scenario power-flow comparison
  -> candidate corrective action
  -> operation-ready report under outputs/operations/
```

That extension would demonstrate how Gridalyn transitions from a model demo to
an operations-oriented study without requiring a large end-to-end flexibility
workflow.

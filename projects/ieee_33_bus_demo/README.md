# IEEE 33-Bus Demo

A compact study built on the SDK's IEEE 33-bus benchmark feeder contract, which
wraps the common 33-bus radial distribution benchmark behind the platform's own
types.

## What this study asks

Whether the project contract holds on a *recognised* network rather than a
synthetic one. It is deliberately smaller than the flagship studies: use it to
exercise the workflow contract, the report contract, figure generation and
power-flow integration without running a full digital-twin case.

Beyond the base feeder it adds a first operational bridge — five deterministic
scenarios whose network states are compared, rather than a single feeder
exported:

```text
model -> simulation -> artifacts -> report -> validation
```

| Scenario | Meaning |
| --- | --- |
| `baseline` | Original IEEE 33-bus feeder |
| `load_growth_20` | Uniform 20 percent demand growth |
| `pv_midday` | Distributed PV at selected downstream buses |
| `ev_evening_peak` | EV charging demand at selected downstream buses |
| `pv_plus_ev` | Mixed PV and EV condition |

## Running it

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
uv run gridalyn project status projects/ieee_33_bus_demo --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `run_ieee33_powerflow` | Builds the benchmark feeder, runs a power flow, exports tables, writes a report and plots the voltage profile. |
| `generate_operational_scenarios` | Applies the deterministic load, PV and EV scenarios, runs power flow for each, and writes comparison tables, report and figure. |
| `run_daily_timeseries` | Applies the generated load profiles as hourly shape and per-bus diversity over the benchmark's own magnitudes. |

## What it produces

```text
outputs/data/buses.csv
outputs/data/lines.csv
outputs/data/loads.csv
outputs/data/scenarios.csv
outputs/data/scenario_results.csv
outputs/data/scenario_voltage_profiles.csv
outputs/reports/ieee33_powerflow_report.json
outputs/reports/ieee33_scenario_comparison_report.json
outputs/figures/ieee33_voltage_profile.png
outputs/figures/ieee33_scenario_voltage_comparison.png
outputs/manifests/project_run_manifest.json
```

Outputs are git-ignored; regenerate them locally when needed. The power-flow
report records bus, line, load and slack counts, total active and reactive
load, line losses, minimum and maximum voltage, maximum line loading and
pandapower convergence status. The scenario comparison report summarises the
best and worst voltage cases, the voltage range, maximum line loading and
voltage-violation counts.

## How it is verified

pandapower convergence is recorded in the report rather than assumed, so a
non-converged run is visible in the artifact.
`gridalyn project status --check-artifacts` confirms every declared artifact
appeared, `gridalyn project regression` compares against
`baselines/results_baseline.json`, and the study runs end to end in CI as one
of the six governed fixtures.

**What this study cannot check, and why.** Line loading is not pinned here.
`pandapower.networks.case33bw()` declares `max_i_ka = 99999` because the
canonical IEEE-33 dataset (Baran & Wu, 1989) specifies no ampacities, so
`loading_percent` on this feeder is current divided by an effectively infinite
rating — 0.00026% against a real 210 A. The baseline pinned that number until
2026-08-28 with a tolerance of 0.01, which is 3877% of the value: it could move
by a factor of 38 and pass. Giving the benchmark invented ratings would make
the study's numbers depend on a parameter the standard does not define, so the
metric was replaced by `max_voltage_violation_count` and
`best_voltage_scenario`, which the scenario-comparison stage actually computes.
Voltage, not thermal loading, is what this feeder can speak to.
`tests/test_regression_baseline_tolerances.py` now fails any baseline metric
whose tolerance exceeds 10% of its own expected value.

## Scope and limits

The magnitudes are the benchmark's, not a measured stock — that is the point of
using IEEE 33. The generated load profiles contribute hourly *shape* and
per-bus diversity on top of those magnitudes; they do not set the level. The
five scenarios are deterministic constructions for comparison, not forecasts.

## Where this sits

It is the smallest study that compares network *states* rather than exporting
one, which makes it the natural place to grow an operational decision layer:

```text
baseline IEEE 33-bus feeder
  -> deterministic load/PV/EV scenarios
  -> scenario power-flow comparison
  -> candidate corrective action
  -> operation-ready report under outputs/operations/
```

To extend it, keep reusable logic in `gridalyn/` and let project scripts bind
only paths and parameters:

| Extension | Where it goes |
| --- | --- |
| More load-growth or DER scenarios | a scenario contract in the SDK, plus a thin workflow stage |
| Operational dispatch records | `outputs/operations/` and a platform operation run report |
| Semantic graph export | a new stage writing graph nodes and edges |
| Dashboard catalog metadata | a new stage materialising dashboard-ready JSON |

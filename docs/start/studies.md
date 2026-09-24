# The Studies

Every study under `projects/` is a project directory with the same shape: a
`project.yaml` and a `workflow.yaml`, the stage scripts they call, a committed
baseline under `baselines/results_baseline.json`, and git-ignored `outputs/`.
The same commands run all of them.

## The two tiers

**CI fixture studies** are small and fast. Every push runs each one end to end
and checks it against its baseline with `gridalyn project regression`, so they
are what gates the study contract.

**Operator-verified studies** run too long, or need data too private, for CI.
An operator runs them on a local machine and verifies them against their
pinned results; their reproduce-and-pin tests skip when the outputs are
absent. The protocol is [Operator Verification](../contributing/verification.md).

## The ladder

Climb it in order. The first rung is one command that scaffolds a study of
its own and runs it; the second is every study that runs in seconds or
minutes; the third is the studies that take hours.

<!-- BEGIN GENERATED: study-inventory by tools/generate_studies_reference.py; do not edit by hand -->

### Rung 1: first result

| Command | Run time | What it is |
| --- | --- | --- |
| `gridalyn quickstart <directory>` | seconds | Scaffolds the `powerflow-demo` template into a new directory and runs it: one power flow, a governed report and a figure. See [Quickstart](quickstart.md). |

### Rung 2: small studies

| Study | Run time | Tier | Extras | What it is |
| --- | --- | --- | --- | --- |
| `cold_load_pickup_feeder` | seconds | CI fixture | none | Forty-eight Québec all-electric homes lose power for four hours at -25 °C; the study re-energises their feeder all at once and section by section, and reports transformer loading, feeder-head demand and voltage against the same evening without the outage. |
| `der_voltage_optimization` | seconds | CI fixture | `ops`, `sim` | Small synthetic feeder with Gridalyn DER dispatch and physical voltage verification. |
| `dr_agent_interaction` | seconds | CI fixture | none | Twenty Québec all-electric homes answer a day of OpenADR 3.1.0 demand-response events over a lossy channel, through the dr_program protocol. |
| `flex_trading_congestion` | seconds | CI fixture | none | A distribution operator buys battery flexibility over UFTP to hold a feeder-head import limit, over a lossy channel, with and without order acknowledgements. |
| `ieee_33_bus_demo` | seconds | CI fixture | `sim` | Runs power flow, operational scenarios and a daily time series on Gridalyn's IEEE 33-bus benchmark feeder contract. |
| `minimal_grid_project` | seconds | CI fixture | none | Minimal Gridalyn project that teaches the project contract with one tiny power-flow run. |
| `prosumer_battery_market` | seconds | CI fixture | none | Small synthetic feeder with distributed prosumers, batteries, and a real-time local market. |
| `synthetic_geojson_feeder` | seconds | CI fixture | none | Converts generated building-footprint GeoJSON into a synthetic distribution feeder. |
| `rl_voltage_control_lightsim` | minutes | CI fixture | `sim` | Trains a tabular Q-learning agent to control feeder voltage with a battery, using lightsim2grid for fast power-flow simulation. |
| `admm_thermal_consensus` | minutes | operator-verified | `ops`, `sim` | Network-validated distributed ADMM coordination of cold-climate electric-heating homes with ML imputation of communication-failed agents, validated on the IEEE-33 feeder with pandapower. |
| `measured_shadow_feeder` | minutes | operator-verified | none | Feed one measured week of per-home power through the semantic graph into a small feeder, solve it, and compare its peak transformer loading with the same feeder driven by the synthetic load generator. |

### Rung 3: full studies

| Study | Run time | Tier | Extras | What it is |
| --- | --- | --- | --- | --- |
| `ev_hosting_flex` | hours | operator-verified | `sim` | EV hosting capacity and flexibility across a 540-transformer distribution fleet, with the transformer rating convention as a declared axis. |

<!-- END GENERATED: study-inventory -->

The tables are generated from the repository by
`tools/generate_studies_reference.py`, and a test fails when they are stale:

- **Run time** is the study's `metadata.runtimeClass` in its `project.yaml`:
  the order of magnitude of a cold `gridalyn project run` measured on one
  developer machine, *seconds* under a minute, *minutes* under an hour,
  *hours* beyond. It decides the rung. A CI fixture study is never *hours*,
  and a test holds every study to declaring one. The quickstart's class comes
  from a measured run recorded in the generator.
- **Tier** is *CI fixture* for every study the `projects` job in
  `.github/workflows/ci.yml` runs and checks against its baseline, and
  *operator-verified* for the rest.
- **Extras** are the optional extras a study cannot run without: those its
  own modules pass to `require_capabilities` or import a module of, those of
  the SDK modules defining the names it imports, and those of any power-flow
  backend it declares in `spec.simulation`. `uv sync --extra dev` installs all
  of them; [Installation](installation.md) lists what each one adds.
- **What it is** is the first sentence of the study's `metadata.description`
  in its `project.yaml`.

`measured_shadow_feeder` reads a measured export that is private; without it,
the study runs on a generated stand-in record and says so in every artifact.
To build a feeder from your own footprints instead of generated ones, see
[Synthetic Networks From GeoJSON](../guides/synthetic-network-from-geojson.md).

## Running a study

[Quickstart](quickstart.md) runs `minimal_grid_project`. Any other study runs
the same way; here `ieee_33_bus_demo`. Print the stage DAG in execution order
without running anything:

```bash
uv run gridalyn project plan projects/ieee_33_bus_demo
```

Run it, with per-stage progress on the terminal:

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
```

While iterating on one stage, run only that stage and the stages it depends
on:

```bash
uv run gridalyn project run projects/ieee_33_bus_demo --stage run_ieee33_powerflow
```

A `--stage` run writes `project_run_manifest.partial.json` and records itself
in the full manifest, so a later `regression` warns that the outputs combine
runs. Check the study as Quickstart did:

```bash
uv run gridalyn project verify projects/ieee_33_bus_demo
uv run gridalyn project regression projects/ieee_33_bus_demo
```

Every study writes under the same output directories, which the first stage
creates with `gridalyn project prepare-workspace`:

```text
projects/<name>/outputs/data/
projects/<name>/outputs/figures/
projects/<name>/outputs/reports/
projects/<name>/outputs/manifests/
projects/<name>/outputs/operations/
projects/<name>/outputs/cache/
```

Not every study fills every one: small studies may write only reports and a
figure, operations studies also write `outputs/operations/`, and a study may
add directories of its own.

## The flagship study

`ev_hosting_flex` is the full research arc. From declared inputs it builds a
synthetic topology cache and exports it as a network model, generates a year
of stochastic building and EV profiles across Monte Carlo realizations,
computes congestion, applies curtailment contracts and replays them as
`dr_program` conversations, clears a fleet-wide locational contract market,
runs a set of risk and value analyses, validates the results with a pandapower
power flow, and closes with `build_study_reports`, which assembles the
study-level report. `uv run gridalyn project plan projects/ev_hosting_flex`
prints the full stage list without running anything.

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project verify projects/ev_hosting_flex
uv run gridalyn project regression projects/ev_hosting_flex
```

A full run from a cold cache takes hours; runs against an existing cache take
minutes. Its headline numbers, their uncertainty and how they were validated
are in the study's own `README.md` and `CALIBRATION.md` under
`projects/ev_hosting_flex/`, which are the source of truth for them.

Next: [Components](../components/overview.md)

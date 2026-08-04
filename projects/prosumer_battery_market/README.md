# Prosumer Battery Market

This project is a compact, reproducible example of Gridalyn as an operations
platform rather than a single flexibility study. It builds a small synthetic
radial feeder, places a few PV+battery prosumers on downstream buses, and runs a
deterministic real-time local market for battery discharge.

The market product is simple: when the feeder import forecast exceeds an
operating limit, prosumers offer battery discharge in 5-minute intervals. The
clearing engine ranks offers by price with a small locational preference for
downstream resources, dispatches batteries until the import requirement is met,
and verifies the resulting feeder state with pandapower.

## Run

```bash
uv run gridalyn project run projects/prosumer_battery_market
uv run gridalyn project status projects/prosumer_battery_market --check-artifacts
```

## Outputs

- `outputs/data/buses.csv`, `lines.csv`, `loads.csv`: synthetic feeder tables.
- `outputs/data/prosumers.csv`: PV+battery prosumer registry.
- `outputs/data/realtime_market_forecast.csv`: rolling-horizon import and reduction forecast.
- `outputs/operations/realtime_market_clearing.csv`: interval-level uniform-price clearing.
- `outputs/operations/realtime_market_offers.csv`: prosumer offer book and accepted MW.
- `outputs/operations/battery_dispatch.csv`: participant dispatch and SOC.
- `outputs/data/realtime_powerflow_results.csv`: post-market power-flow metrics.
- `outputs/reports/*.json`: canonical platform reports.
- `outputs/figures/*.png`: voltage and market-dispatch figures.

## Scope

This is intentionally small: 14 buses, 13 lines, 13 loads, 5 prosumers, and 12
real-time intervals. The market uses a rolling-horizon forecast and a
uniform-price auction inspired by transactive-energy real-time markets and
MPC-style DER scheduling. It is meant for demos, tests, and SDK development,
not as a calibrated market model.

---

<!-- Merged from the former docs/projects/prosumer-battery-market.md. The published
documentation now covers the project CONTRACT in general; per-project
detail lives with the project. -->

`projects/prosumer_battery_market` is a compact operations demo that uses a
synthetic feeder, distributed PV+battery prosumers, and a deterministic
real-time local market.

## Why This Demo Exists

The IEEE 33-bus demo shows the basic model-simulation-report loop. The
EV Hosting Flexibility project shows a larger network-aware flexibility workflow. This
prosumer demo sits between them: it is small enough for fast tests but includes
market participants, offers, dispatch, battery state of charge, and post-market
power-flow verification.

It exercises:

- project manifests;
- synthetic feeder generation;
- prosumer and battery registries;
- real-time market clearing;
- operational dispatch artifacts;
- pandapower verification after dispatch;
- canonical JSON reports and figures.

## Run It

```bash
uv run gridalyn project run projects/prosumer_battery_market
uv run gridalyn project status projects/prosumer_battery_market --check-artifacts
```

Expected generated artifacts:

```text
projects/prosumer_battery_market/outputs/data/buses.csv
projects/prosumer_battery_market/outputs/data/lines.csv
projects/prosumer_battery_market/outputs/data/loads.csv
projects/prosumer_battery_market/outputs/data/prosumers.csv
projects/prosumer_battery_market/outputs/data/realtime_market_forecast.csv
projects/prosumer_battery_market/outputs/data/realtime_powerflow_results.csv
projects/prosumer_battery_market/outputs/operations/realtime_market_clearing.csv
projects/prosumer_battery_market/outputs/operations/realtime_market_offers.csv
projects/prosumer_battery_market/outputs/operations/battery_dispatch.csv
projects/prosumer_battery_market/outputs/reports/synthetic_feeder_report.json
projects/prosumer_battery_market/outputs/reports/prosumer_realtime_market_report.json
projects/prosumer_battery_market/outputs/figures/synthetic_feeder_voltage_profile.png
projects/prosumer_battery_market/outputs/figures/prosumer_market_dispatch.png
projects/prosumer_battery_market/outputs/manifests/project_run_manifest.json
```

## What It Demonstrates

The workflow has three stages:

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_synthetic_feeder` | Builds a 14-bus radial feeder, runs the base power flow, writes feeder/prosumer tables, a report, and a voltage figure. |
| `run_realtime_prosumer_market` | Clears 12 five-minute market intervals for five PV+battery prosumers using a rolling-horizon forecast and uniform-price auction, then writes dispatch, offer, power-flow, report, and figure outputs. |

## Asset Modeling Strategy

The project owns its concrete feeder and prosumer parameters in `project.yaml`.
The project-local `network_model.py` loads that declarative contract through
`gridalyn.projects` helpers and passes the resulting SDK contracts into
Gridalyn simulation builders.

The reusable SDK contracts are:

- `ProsumerAsset`;
- `PVAsset`;
- `BatteryAsset`;
- `prosumer_assets_to_frame`.

The feeder is built through `gridalyn.simulation.build_radial_pandapower_feeder`.
Market dispatch maps the asset contracts into a solver network through
`gridalyn.simulation.apply_pv_generation_to_pandapower` and
`gridalyn.simulation.apply_battery_dispatch_to_pandapower`.

That keeps the project focused on scenario setup and market orchestration. The
asset identity and tabular contract can be reused by other projects, dashboards,
semantic-graph exporters, or future service APIs while solver mappings remain
in the simulation layer.

## Market Logic

The market product is battery discharge to reduce feeder import above a
real-time operating limit. The current implementation is
`rolling_horizon_uniform_price_auction`: a compact adaptation of
transactive-energy real-time auctions and MPC-style forecast use. For each
interval:

1. the market operator issues a four-interval load/PV/import forecast;
2. the reduction requirement is `max(import - limit, 0)`;
3. prosumer batteries submit offer quantities constrained by power, state of
   charge, and a future-energy reserve from the forecast horizon;
4. offers clear by network-adjusted bid price;
5. accepted prosumers are paid a uniform clearing price equal to the marginal
   accepted offer;
6. pandapower verifies the post-dispatch feeder state.

This is not a calibrated market design. It is a clean platform example showing
how participants, operational constraints, dispatch, verification, and reports
fit into one reproducible project.

## Method References

- Transactive energy systems use market processes and automated device bidding
  for price-based dispatch at distribution level; TESS describes this pattern
  and real-time auction mechanisms.
- MPC-based DER controllers use forecasts of PV/load and real-time prices over
  a prediction horizon, then apply immediate control actions in rolling fashion.

The demo combines those ideas in a small deterministic implementation so the
workflow remains fast and inspectable.

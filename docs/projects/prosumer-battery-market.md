# Prosumer Battery Market Demo

`projects/prosumer_battery_market` is a compact operations demo that uses a
synthetic feeder, distributed PV+battery prosumers, and a deterministic
real-time local market.

## Why This Demo Exists

The IEEE 33-bus demo shows the basic model-simulation-report loop. The
Flexibility CLS project shows a larger network-aware flexibility workflow. This
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

The project does not define its own energy-asset model. It uses the reusable SDK
contracts in `gridalyn.assets`:

- `ProsumerAsset`;
- `PVAsset`;
- `BatteryAsset`;
- `prosumer_assets_to_frame`;
- `apply_pv_generation_to_pandapower`;
- `apply_battery_dispatch_to_pandapower`.

That keeps the project focused on scenario setup and market orchestration. The
asset identity, tabular contract, and pandapower mapping can be reused by other
projects, dashboards, semantic-graph exporters, or future service APIs.

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

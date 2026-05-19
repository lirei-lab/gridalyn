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

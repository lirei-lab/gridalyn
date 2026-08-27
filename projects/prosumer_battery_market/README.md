# Prosumer Battery Market

A compact study of Gridalyn as an operations platform rather than a single
flexibility analysis. It builds a small synthetic radial feeder, places PV+
battery prosumers on downstream buses, and runs a deterministic real-time local
market for battery discharge.

## What this study asks

Whether participants, operational constraints, dispatch, verification and
reports fit inside one reproducible project — the operations loop, at a size
that stays inspectable.

The market product is deliberately simple: when the feeder import forecast
exceeds an operating limit, prosumers offer battery discharge in five-minute
intervals. The clearing engine ranks offers by price with a small locational
preference for downstream resources, dispatches batteries until the import
requirement is met, and verifies the resulting feeder state with pandapower.

## Running it

```bash
uv run gridalyn project run projects/prosumer_battery_market
uv run gridalyn project status projects/prosumer_battery_market --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_synthetic_feeder` | Builds a 14-bus radial feeder, runs the base power flow, writes feeder/prosumer tables, a report and a voltage figure. |
| `run_realtime_prosumer_market` | Clears 12 five-minute intervals for five prosumers using a rolling-horizon forecast and uniform-price auction, then writes dispatch, offer, power-flow, report and figure outputs. |
| `export_twin_network_model` | Exports the resulting network model to the twin. |

## What it produces

| Artifact | What it holds |
| --- | --- |
| `outputs/data/buses.csv`, `lines.csv`, `loads.csv` | Synthetic feeder tables |
| `outputs/data/prosumers.csv` | PV+battery prosumer registry |
| `outputs/data/realtime_market_forecast.csv` | Rolling-horizon import and reduction forecast |
| `outputs/operations/realtime_market_clearing.csv` | Interval-level uniform-price clearing |
| `outputs/operations/realtime_market_offers.csv` | Offer book and accepted MW |
| `outputs/operations/battery_dispatch.csv` | Participant dispatch and state of charge |
| `outputs/data/realtime_powerflow_results.csv` | Post-market power-flow metrics |

Plus the canonical platform reports under `outputs/reports/` and voltage and
market-dispatch figures under `outputs/figures/`.

## How it is verified

The market's own last step is verification: pandapower checks the
post-dispatch feeder state, so a clearing that satisfies the market but
violates the network is visible rather than reported as success. Around that,
`gridalyn project status --check-artifacts` confirms the artifacts appeared,
`gridalyn project regression` compares against
`baselines/results_baseline.json`, and the study runs in CI as one of the six
governed fixtures.

## Scope and limits

Intentionally small: 14 buses, 13 lines, 13 loads, 5 prosumers, 12 real-time
intervals. **This is not a calibrated market design.** The clearing rule,
`rolling_horizon_uniform_price_auction`, is a compact adaptation of
transactive-energy real-time auctions and MPC-style forecast use — per
interval:

1. the operator issues a four-interval load/PV/import forecast;
2. the reduction requirement is `max(import - limit, 0)`;
3. batteries submit offers constrained by power, state of charge, and a
   future-energy reserve from the forecast horizon;
4. offers clear by network-adjusted bid price;
5. accepted prosumers are paid a uniform price equal to the marginal accepted
   offer;
6. pandapower verifies the post-dispatch state.

The design draws on transactive-energy systems, where market processes and
automated device bidding drive price-based distribution-level dispatch, and on
MPC-based DER control, which uses PV/load/price forecasts over a horizon and
applies immediate actions in rolling fashion. It combines those ideas
deterministically so the workflow stays fast; it does not reproduce either.

## Where this sits

The project owns its concrete feeder and prosumer parameters in `project.yaml`;
its local `network_model.py` loads that contract through the
[Projects](../../docs/components/projects.md) helpers and passes SDK contracts
into the simulation builders. Asset identity — `ProsumerAsset`, `PVAsset`,
`BatteryAsset`, `prosumer_assets_to_frame` — comes from
[Assets](../../docs/components/assets.md), while solver mappings
(`apply_pv_generation_to_pandapower`, `apply_battery_dispatch_to_pandapower`)
stay in [Simulation](../../docs/components/simulation.md).

That split is what lets the same asset contracts be reused by other studies,
dashboards and semantic-graph exporters without dragging a solver along.

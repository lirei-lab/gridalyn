# Market And Operations SDK

The market and operations modules manage flexibility providers, aggregators,
offers, locational clearing, dispatch, settlement, and operational scorecards.

## Separation Of Concerns

| Layer | Responsibility |
| --- | --- |
| `gridalyn.operations` | Public operations facade plus provider registry, clearing, dispatch, settlement, and scorecards. |
| `gridalyn.operations.market` | Lower-level market mechanics used by workflows and the facade. |
| `gridalyn.simulation.analytics` | Network-impact features, predictions, and validation helpers. |
| `gridalyn.foundation` | Stable governance and report contracts that applications and projects can call. |

New SDK examples should use this structure directly: operations own market
decisions, simulation owns impact and validation analytics, and foundation owns
governed reports and lineage.

Operations modules consume network-constraint interfaces instead of importing
synthetic datagen models directly. Project workflows may instantiate
`gridalyn.assets.datagen.MVNetwork` or load a real network adapter, then pass
that object into dispatch/market services.

## Prosumer Real-Time Market

Prosumer battery clearing is an operations concern, not a demo-script concern.
Use `ProsumerRealtimeMarketConfig` plus `run_prosumer_realtime_market` when a
project needs rolling-horizon forecast, offer ranking, battery dispatch, and
power-flow verification:

```python
from gridalyn.operations.market import (
    ProsumerRealtimeMarketConfig,
    run_prosumer_realtime_market,
)

config = ProsumerRealtimeMarketConfig(
    interval_minutes=5,
    interval_count=12,
    import_limit_mw=2.55,
    forecast_horizon_intervals=4,
    load_multipliers=(...),
    pv_factors=(...),
    load_forecast_bias_by_lead=(...),
    pv_forecast_bias_by_lead=(...),
)
result = run_prosumer_realtime_market(
    prosumers=prosumer_table,
    build_feeder=build_feeder,
    config=config,
)
```

The result contains `clearing`, `dispatch`, `forecast`, `offers`, and
`powerflow` tables. Project scripts should only bind local assets/configuration
and persist the declared artifacts.

## Design Rule

Provider selection should be graph- and topology-aware. Aggregator bids are not
enough by themselves; the operation must understand where assets are connected
and whether the selected response relieves the targeted network constraint.

See [Utility Operations](../platform/operations.md) and
[Locational Clearing](../flexibility/clearing.md).

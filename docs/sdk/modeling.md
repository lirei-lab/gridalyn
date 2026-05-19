# Modeling

Modeling modules generate asset and behavior tables used by scenarios,
simulations, flexibility operations, and reports.

## Current Domains

| Domain | Description |
| --- | --- |
| Buildings | PyCity-style building, zone, end-use, and device abstractions. |
| Thermal forecasts | Dynamic thermal capacity and operating envelopes. |
| Synthetic networks | Building-footprint GeoJSON to `PowerGridGraph`, pandapower network, cache files, and validation report. |
| Study feeders | Compact radial feeder specifications for optimization, markets, and learning-control demos. |
| EV and EVSE | Charging assets, scenario participation, and controllability roles. |
| DER control assets | PV plus battery contracts for voltage-control and distributed-energy studies. |
| Flexibility envelopes | Provider capabilities and response limits. |
| Scenario devices | Scenario-specific overlays on base assets. |

## Design Direction

Modeling should expose reusable components, not study-specific scripts. Project
workflows should be able to combine model generators to create different cases
without copying internals from another demo project.

See [Building Models](../platform/building-models.md).

## Synthetic Network Builder

Use `build_synthetic_network_from_geojson` when a project needs to create a
network model from building footprints instead of hand-copying the historical
tutorial sequence.

```python
from pathlib import Path

from gridalyn.assets.modeling import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path=Path("projects/my_project/inputs/buildings.geojson"),
    config_path=Path("configs/grid/config.json"),
    out_dir=Path("projects/my_project/outputs/cache"),
    clustering_crs="auto",
    write_cache=True,
    run_powerflow=True,
)

print(result.validation_report["valid"])
print(result.validation_report["counts"])
```

The builder writes `synthetic_network_validation_report.json` when `out_dir` is
provided. With `write_cache=True`, it also writes `pg_graph_cache.pkl` and
`pp_net_cache.pkl`, which can be exported through the digital-twin adapter.

The root shortcut `from gridalyn import build_synthetic_network_from_geojson`
is also supported for project scripts. Historical `gridalyn.modeling` imports
remain compatibility aliases.

## Prosumer Energy Assets

Gridalyn exposes small reusable contracts for distributed prosumer resources:

```python
from gridalyn.assets import BatteryAsset, PVAsset, ProsumerAsset

asset = ProsumerAsset(
    prosumer_id="P01",
    bus_id=4,
    pv=PVAsset(asset_id="pv:P01", capacity_mw=0.18),
    battery=BatteryAsset(
        asset_id="battery:P01",
        power_mw=0.12,
        capacity_mwh=0.36,
        initial_soc_mwh=0.25,
        min_soc_mwh=0.07,
    ),
    offer_price_usd_per_mwh=58.0,
)
```

Use `prosumer_assets_to_frame` for stable project artifacts and
`apply_pv_generation_to_pandapower` / `apply_battery_dispatch_to_pandapower`
when mapping those assets into power-flow studies.

## Feeder and Voltage-Control Assets

Small projects should not hand-build pandapower networks unless the point of the
project is the network-construction algorithm itself. Use `RadialFeederSpec`
for compact benchmark feeders and `VoltageControlDERSpec` for PV/battery
control assets:

```python
from gridalyn.assets import (
    BatteryAsset,
    RadialFeederSpec,
    VoltageControlDERSpec,
    build_voltage_control_feeder,
)

feeder = RadialFeederSpec(
    name="demo_feeder",
    bus_count=10,
    sn_mva=2.0,
    base_voltage_kv=12.47,
    slack_vm_pu=1.01,
    loads_mw={1: 0.08, 2: 0.09, 3: 0.10},
)
der = VoltageControlDERSpec(
    asset_id="der:demo",
    controlled_bus_id=3,
    pv_bus_id=3,
    battery_bus_id=3,
    pv_capacity_mw=0.35,
    battery=BatteryAsset(
        asset_id="battery:demo",
        power_mw=0.08,
        capacity_mwh=0.24,
        initial_soc_mwh=0.12,
        min_soc_mwh=0.04,
    ),
    max_soc_mwh=0.22,
    action_space_mw=(-0.08, 0.0, 0.08),
)

net = build_voltage_control_feeder(feeder, der)
```

The RL voltage-control demo uses these contracts so the project demonstrates
Gridalyn's modeling layer instead of embedding all network and DER logic inside
project-local scripts.

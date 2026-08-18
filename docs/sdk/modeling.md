# Modeling

Modeling modules generate asset and behavior tables used by scenarios,
simulations, flexibility operations, and reports.

## Current Domains

| Domain | Description |
| --- | --- |
| Buildings | PyCity-style building, zone, end-use, and device abstractions. |
| Thermal forecasts | Dynamic thermal capacity and operating envelopes. |
| Network-adjacent asset inputs | Building footprints, scenario device tables, and asset registries consumed by twin and simulation workflows. |
| Study feeders | Compact radial feeder specifications for optimization, markets, and learning-control demos. |
| EV and EVSE | Charging assets, scenario participation, and controllability roles. |
| DER control assets | PV plus battery contracts for voltage-control and distributed-energy studies. |
| Transformer thermal models | IEEE C57.91-style thermal limits and forecast contracts. |
| Flexibility envelopes | Provider capabilities and response limits. |
| Scenario devices | Scenario-specific overlays on base assets. |

## Design Direction

Modeling should expose reusable components, not study-specific scripts. Project
workflows should be able to combine model generators to create different cases
without copying internals from another demo project.

Gridalyn follows an EnFlow-like separation of roles without copying EnFlow's
API directly:

| Role | Gridalyn home | Boundary |
| --- | --- | --- |
| Asset contracts | `gridalyn.assets.modeling` | Dataclasses, validation, tabular contracts, and pure physical model helpers. |
| Synthetic input generators | `gridalyn.assets.datagen` | Weather/load generation, TMY selection, aggregate synthetic stress-test models. |
| Solver modelers | `gridalyn.simulation` | `pandapower`, LightSim2Grid, network construction, replay, and validation analytics. |
| Operation modelers | `gridalyn.operations` | Provider selection, clearing, dispatch, settlement, constraints, and KPIs. |
| Experiment packaging | `gridalyn.projects` | Dataset/environment/objective/scenario binding through `project.yaml` and `workflow.yaml`. |

The strict rule is that asset modelers do not import solver engines,
operations, project workflows, or datagen. They define reusable contracts that
other layers consume.

**This is layer ownership, not role separation.** The table above answers
"which of the seven packages owns this kind of code" — a different question
from "which swappable role does a network-control component play." In
2026-08-10 a second separation was built for **four** roles:
physical power-flow backend, surrogate, observation, and control policy.

**Three of the four are registries; observation is not.** Say "four roles,
three registries" — the two counts differ on purpose.

| Role | Home | Resolution |
| --- | --- | --- |
| Power-flow backend | `gridalyn.simulation.backends` | `PowerFlowBackendRegistry`, explicit ID |
| Surrogate | `gridalyn.simulation.surrogates` | `SurrogateRegistry`, explicit ID |
| Control policy | `gridalyn.simulation.policies` | `PolicyRegistry`, explicit ID |
| Observation | `gridalyn.twin.observation` | A contract plus one builder, `observe_network` — **no registry** |

Observation has one implementation because nothing in this repository yet needs
a second; a registry ahead of that need would be the speculative abstraction the
platform's own conventions warn against, and its absence is asserted by a test
rather than left to look like an oversight. It also no longer lives in
`gridalyn.simulation`: in 2026-08-12 it moved down to
`gridalyn.twin.observation`, because what a network currently shows is a
property of the model, not of the solver. `gridalyn.simulation.observation`
still resolves as a deprecated re-export that emits a `DeprecationWarning`.

Each registry resolves by name rather than being fused into one class, with the
choice recorded in `provenance.powerflow_backend`. Earlier,
`VoltageControlEnvironment` fused all four roles into one 138-line class — a
layer-ownership violation the table above never flagged, because "solver
modelers" already correctly described where the code lived; it just did not
separate the roles *within* that one home. Both claims are true now, and they
are about different axes: the first table is package boundaries, this one is
role boundaries.

See [Building Models](building-models.md).

For stochastic load profiles, weather windows, packaged ARX weights, and
aggregate MV-network stress-test assumptions, see
[Data Generation](data-generation.md). Those helpers feed modeling workflows,
but they are documented separately because they describe synthetic inputs rather
than durable asset entities.

Transformer thermal behavior lives in modeling because it is a physical asset
model. Synthetic workflows may import it from `gridalyn.assets.modeling` when
they need aggregate stress-test constraints.

## Synthetic Network Builder

Use `build_synthetic_network_from_geojson` when a project needs to create a
network model from building footprints instead of hand-copying the historical
tutorial sequence. The builder is documented here because it consumes building
and asset assumptions, but the API is owned by `gridalyn.simulation` because it
creates a `pandapower` network and optional power-flow validation report.

```python
from pathlib import Path

from gridalyn.simulation import build_synthetic_network_from_geojson

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
is also supported for compact project scripts, but new documentation should
prefer `from gridalyn.simulation import build_synthetic_network_from_geojson`.

Use `build_synthetic_network_from_config` when the workflow already owns a
validated configuration mapping and should not round-trip it through a temporary
file.

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
`gridalyn.simulation.apply_pv_generation_to_pandapower` / `gridalyn.simulation.apply_battery_dispatch_to_pandapower`
when mapping those assets into power-flow studies.

Bundled demos keep concrete case values in `project.yaml` and load them through
`gridalyn.projects` model-input helpers. The SDK owns the reusable contracts and
builders; projects own their scenario parameters.

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
)
from gridalyn.simulation import build_voltage_control_feeder

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

The RL voltage-control demo declares its concrete feeder, DER, and profiles in
`project.yaml`, then loads them into these contracts. That keeps project data
declarative while avoiding project-specific Python specs inside the SDK.

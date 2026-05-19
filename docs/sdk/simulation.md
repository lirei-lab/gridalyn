# Simulation

Simulation modules validate whether scenarios and operations are physically
plausible on the network model.

## Current Scope

- pandapower-based powerflow validation;
- LightSim2Grid-backed fast AC power-flow environments;
- reusable voltage-control environments for optimization and learning demos;
- voltage and thermal loading outputs;
- transformer overload checks;
- scenario time-series validation;
- comparison between fast network-impact estimates and physics validation.

## Voltage-Control Environment

`VoltageControlEnvironment` packages a Gridalyn feeder specification, a
PV/battery control asset, load/PV profiles, and a LightSim2Grid adapter into a
small deterministic environment. Projects can use it for tabular RL, policy
evaluation, or optimization loops without reimplementing low-level grid-model
mutation.

```python
import numpy as np

from gridalyn.assets import BatteryAsset, RadialFeederSpec, VoltageControlDERSpec
from gridalyn.simulation import VoltageControlEnvironment, VoltageControlEnvironmentSpec

spec = VoltageControlEnvironmentSpec(
    feeder=RadialFeederSpec(
        name="demo",
        bus_count=4,
        sn_mva=1.0,
        base_voltage_kv=12.47,
        slack_vm_pu=1.01,
        loads_mw={1: 0.04, 2: 0.05, 3: 0.06},
    ),
    der=VoltageControlDERSpec(
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
    ),
    load_multiplier_profile=np.array([0.9, 1.1]),
    pv_profile=np.array([0.0, 0.75]),
    timestep_hours=0.25,
    voltage_target_pu=1.01,
    voltage_low_pu=0.98,
    voltage_high_pu=1.04,
)

env = VoltageControlEnvironment(spec)
record = env.step(0, 0.0)
```

## Design Rule

Fast screening models and market clearing can propose actions, but operational
claims should be backed by validation reports. When a surrogate is used, reports
should state which physics checks were run and which constraints remain.

See [Network Impact Verification](../flexibility/network-impact-surrogate.md).

# Simulation

Simulation modules validate whether scenarios and operations are physically
plausible on the network model.

## Current Scope

- GeoJSON-to-`pandapower` synthetic network construction;
- pandapower-based powerflow validation;
- standard pandapower table, voltage-figure, report, and scenario helpers;
- LightSim2Grid-backed fast AC power-flow environments;
- reusable voltage-control environments for optimization and learning demos;
- voltage and thermal loading outputs;
- transformer overload checks;
- scenario time-series validation;
- comparison between fast network-impact estimates and physics validation.

## Synthetic Network Builder

`build_synthetic_network_from_geojson` is the native project-facing builder for
turning footprint GeoJSON plus a Gridalyn grid config into:

- a Gridalyn topology bundle;
- a solver-ready `pandapowerNet`;
- optional cache files for downstream adapters;
- `synthetic_network_validation_report.json`.

```python
from gridalyn.simulation import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="configs/grid/config.json",
    out_dir="projects/my_project/outputs/cache",
    write_cache=True,
    run_powerflow=True,
)

assert result.validation_report["valid"]
```

Use this API from project scripts when the workflow needs a generated
electrical network. Use `gridalyn.assets` for the durable asset entities and
synthetic input tables that feed simulation.

## Power-Flow Study Helpers

Project scripts should not reimplement routine pandapower serialization. Use
the simulation helpers to keep demos thin and to make reports consistent:

```python
from gridalyn import foundation, simulation

net = simulation.build_radial_pandapower_feeder(feeder_spec)
tables = simulation.write_pandapower_element_tables(net, "outputs/data")
figure = simulation.write_voltage_profile_figure(
    net,
    "outputs/figures/voltage_profile.png",
    title="Voltage Profile",
)
simulation.write_powerflow_report(
    "outputs/reports/powerflow_report.json",
    metadata=foundation.ReportMetadata(
        report_id="powerflow_report",
        source_domain="my_project",
        project={"name": "my_project"},
    ),
    net=net,
    artifacts=[*tables.values(), figure],
)
```

For deterministic load/PV/EV operating cases, declare
`StandardPowerflowScenario` objects and call
`run_standard_powerflow_scenario`. The project owns the scenario list; the SDK
owns how the scenario mutates and validates the solver network.

## Transformer Peak Validation

Use `validate_transformer_peak_scenarios` when a study needs to compare
scenario peak demand against both nameplate loading and a transformer thermal
limit. The project provides scenario labels and peak-load values; Gridalyn owns
the compact pandapower network, transformer type, loading calculation, voltage
check, and congestion flags.

```python
from gridalyn.simulation import (
    TransformerPeakValidationConfig,
    validate_transformer_peak_scenarios,
)

result = validate_transformer_peak_scenarios(
    scenarios={"S2_20pct": {"unmanaged_peak_mw": 12.4}},
    config=TransformerPeakValidationConfig(
        s_rated_mva=15.0,
        s_rated_kva=15_000.0,
        theta_max_c=110.0,
        power_factor=0.95,
        hv_voltage_kv=120.0,
        mv_voltage_kv=25.0,
    ),
)
assert result["scenarios"][0]["converged"]
```

Keep project scripts responsible for paths, local constants, and declared
artifacts. Do not duplicate transformer-type registration or peak-loading loops
inside demos.

## Voltage-Control Environment

`VoltageControlEnvironment` packages a Gridalyn feeder specification, a
PV/battery control asset, and load/PV profiles into a small deterministic
environment. Projects can use it for tabular RL, policy evaluation, or
optimization loops without reimplementing low-level grid-model mutation.

It *composes* rather than hardcodes its parts: the solver is resolved from the
power-flow backend registry (`backend_id=` defaults to `lightsim2grid`, the
engine this environment has always used), what a step returns is built through
the observation contract, and `run_policy_episode` drives a full episode from a
registered policy. Substituting any of the three does not require touching the
environment.

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

## Output Boundary

Simulation code produces physical validation records and solver results. Project
workflows and digital-twin instance contracts decide where those results are
persisted, and dashboard-facing publication goes through report or catalog
interfaces rather than simulation-specific exporters.

# Building Models

The `gridalyn` core now includes a small generative building-model layer between the static
digital twin and the scenario/flexibility analysis. The goal is to make each
building explicit as a reusable model entity, not only as a row in a load table.

## Purpose

The first implementation is intentionally lightweight and deterministic:

- It loads base buildings and connectivity through
  `gridalyn.twin.NetworkModelRepository`.
- It assigns a North America residential archetype from floor area.
- It creates one thermal zone per building.
- It creates HVAC device rows for Soft CLS style flexibility.
- It creates EVSE device rows only when the input building table already marks
  an EV instance.
- It creates scenario overlays from `asset_registry.parquet` so EV adoption and
  CLS roles remain scenario-specific rather than polluting the base model.

This follows the entity decomposition philosophy of pyCity: buildings contain
zones, zones and buildings have devices, and devices support energy/flexibility
analysis. We do not currently depend on pyCity, because the platform needs a
stable Parquet contract first.

## Outputs

```text
instances/default/digital_twin/models/
  building_models.parquet
  thermal_zones.parquet
  device_registry.parquet
  end_use_loads.parquet
  building_model_manifest.json
  scenarios/
    S*_device_registry.parquet
    scenario_summary.parquet
    scenario_model_manifest.json
```

The main tables are:

| Table | Role |
| --- | --- |
| `building_models.parquet` | Building-level archetype, connectivity, capacity, and thermal metadata. |
| `thermal_zones.parquet` | Simplified conditioned zones and setpoint assumptions. |
| `device_registry.parquet` | HVAC and EVSE controllable device registry. |
| `end_use_loads.parquet` | Heating, cooling, and non-HVAC end-use estimates. |
| `scenarios/S*_device_registry.parquet` | Scenario-specific Soft CLS and Hard CLS device overlay. |
| `scenarios/scenario_summary.parquet` | Scenario counts and available flexibility capacity. |

## Command

```bash
uv run gridalyn twin building-models
```

Generate scenario overlays after the scenario asset registry:

```bash
uv run gridalyn twin scenario-models
```

The full digital twin build runs this step immediately after `export_base`:

```bash
uv run gridalyn twin build --skip-heavy
```

## Python API

```python
from pathlib import Path

from gridalyn.assets import load_base_inputs, write_building_model_artifacts

buildings, connectivity = load_base_inputs(Path("instances/default/digital_twin/base"))
manifest = write_building_model_artifacts(
    buildings,
    connectivity,
    out_dir=Path("instances/default/digital_twin/models"),
)
```

`load_base_inputs` is repository-first: it uses the same base topology contract
as the dashboard, semantic graph, and flexibility provider layer. This keeps
building model synthesis independent from the physical storage layout of the
base network snapshot.

For tests or custom projects, call the synthesis function directly:

```python
import pandas as pd

from gridalyn.assets import (
    synthesize_building_model_tables,
    synthesize_scenario_device_tables,
)

tables = synthesize_building_model_tables(buildings, connectivity)
scenario_tables = synthesize_scenario_device_tables(
    tables["building_models"],
    tables["device_registry"],
    pd.read_parquet("instances/default/digital_twin/scenarios/asset_registry.parquet"),
)
```

## Thermal Limit Model

Transformer dynamic operating limits are platform modeling primitives, not
study-local helpers. Use `gridalyn.assets.datagen.build_thermal_forecast` when
a workflow needs a synthetic TMY/weather-driven forecast, and use
`gridalyn.assets.modeling.thermal` when the workflow already owns an explicit
ambient-temperature trace:

```python
from gridalyn.assets.datagen import build_thermal_forecast
from gridalyn.assets.modeling.thermal import (
    thermal_forecast_metadata,
)

forecast = build_thermal_forecast(
    336,
    resolution_minutes=5,
    s_rated_kva=15_000.0,
    theta_max=110.0,
)
metadata = thermal_forecast_metadata(forecast)
```

Study projects may wrap this API to pin their own transformer rating, thermal
limit, weather profile, and resolution, reusing the same peak-demand weather
selector as their stochastic load generator.

## Profile

The default profile is `north_america_residential_v1`. It currently includes:

- `na_residential_small`
- `na_residential_medium`
- `na_residential_multifamily`

The profile is not a calibrated building-energy model yet. It is a stable
synthetic baseline with explicit units, deterministic parameter assignment, and
network lineage back to buses, feeders, and transformers.

## Next Steps

The natural next step is calibration:

- add profile variants by climate zone and building vintage;
- use measured or EnergyPlus-style data to tune archetype parameters;
- link scenario EV adoption to the model-layer device registry;
- expose building/device entities in the semantic graph and FalkorDB exporter;
- let flexibility clearing select providers through building/device model IDs
  instead of ad hoc load rows.

The current provider registry already consumes scenario model overlays when
available. Each provider row carries `scenario_device_ids`, `device_ids`,
`building_model_id`, `device_types`, and `aggregator_id`. The semantic graph
then exposes those scenario devices as `dt:ScenarioDevice` nodes connected to
their `cls:FlexibilityProvider` through `HAS_FLEXIBILITY_RESOURCE`.

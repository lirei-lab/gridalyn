# Data Generation

Gridalyn includes synthetic data-generation helpers for repeatable grid studies.
They are useful for tutorials, demos, Monte Carlo stress tests, and public
workflows where real AMI, SCADA, weather, or building telemetry cannot be
distributed.

The stable modeling API is still `gridalyn.assets`. The lower-level
`gridalyn.assets.datagen` package is an experimental generation layer for
synthetic load, weather, and aggregate MV-network assumptions.

## What It Provides

| Surface | Purpose | Public posture |
| --- | --- | --- |
| `gridalyn.assets.datagen.GridLoadFacade` | Generates heating and background load matrices from weather. | Experimental, reproducible. |
| `gridalyn.assets.datagen.agents` | Synthetic building and EV agents used by thermodynamic workflows. | Experimental, reproducible. |
| `gridalyn.assets.datagen.download_tmy` | Retrieves or synthesizes a TMY weather profile and caches it outside the SDK tree. | Stable enough for examples. |
| `gridalyn.assets.datagen.select_cold_day` | Selects a cold weather window for winter stress tests. | Stable enough for examples. |
| `gridalyn.assets.datagen.select_peak_load_day` | Selects a winter demand proxy window based on heating degree-hours. | Stable enough for examples. |
| `gridalyn.assets.datagen.build_thermal_forecast` | Generates a synthetic ambient-temperature forecast and maps it into a transformer limit model. | Stable enough for examples. |
| `gridalyn.assets.datagen.MVNetwork` | Checks aggregate MV-network thermal constraints for market and flexibility studies. | Experimental aggregate model. |

Use these helpers when a workflow needs synthetic inputs. Use project manifests,
reports, and sense checks to make the generated assumptions traceable.

## Load Generation

`GridLoadFacade.generate_loads` returns two matrices in kilowatts:

```python
from gridalyn.assets.datagen import GridLoadFacade, download_tmy, select_cold_day

tmy = download_tmy()
weather = select_cold_day(tmy, duration_hours=24)["temp_air"]

heat_kw, background_kw = GridLoadFacade.generate_loads(
    generator_type="parametric",
    df_weather=weather,
    n_houses=100,
    resolution_minutes=15,
    seed=42,
)
```

Both matrices have shape `(time_steps, n_houses)`. `generator_type` can be:

| Type | Meaning |
| --- | --- |
| `parametric` | Uses packaged LightGBM macro-shape weights when available, otherwise a deterministic analytical macro shape, plus seeded AR(1) diversity. |
| `thermodynamic` | Uses explicit RC-style residential building agents. |

The parametric generator is self-contained at runtime. If packaged LightGBM
weights are not present, it falls back to an analytical synthetic baseline so
public clones and lightweight installs still run. In both modes, the output is
a synthetic baseline, not a utility-calibrated forecast model.

For lower-level customization, import the generator directly from its native
asset-generation module:

```python
from gridalyn.assets.datagen import ParametricArxGenerator
```

## MV-Network Configuration

## Thermal Forecast Generation

The transformer thermal model itself lives in `gridalyn.assets.modeling`. The
TMY/weather-driven generator lives here because it creates synthetic input data:

```python
from gridalyn.assets.datagen import build_thermal_forecast
from gridalyn.assets.modeling.thermal import thermal_forecast_metadata

forecast = build_thermal_forecast(
    96,
    resolution_minutes=15,
    s_rated_kva=15_000.0,
    theta_max=110.0,
)
metadata = thermal_forecast_metadata(forecast)
```

Use `gridalyn.assets.modeling.thermal.build_thermal_forecast_from_ambient` when
a project already owns an explicit weather trace and should not call synthetic
weather generation.

## MV-Network Configuration

The aggregate MV model can be created directly:

```python
from gridalyn.assets.datagen import MVNetwork, MVNetworkConfig

network = MVNetwork.from_config(
    MVNetworkConfig(
        transformer_kva=15_000.0,
        voltage_mv_kv=25.0,
        power_factor=0.95,
        theta_max_c=110.0,
    )
)

status = network.check_constraint(p_total_kw=12_500.0, ambient_c=-15.0)
```

Or from a Gridalyn grid config:

```python
from gridalyn.assets.datagen import MVNetwork

network = MVNetwork.from_grid_config("configs/grid/config.json")
```

Project code may wrap this API to pin local ratings, weather windows, scenario
rates, or reliability thresholds. Those assumptions should live in
`projects/<project>/scripts/config.py` or in project input files, not hidden
inside a reusable SDK module.

## Reproducibility

- Set `GRIDALYN_DATAGEN_CACHE_DIR` to redirect weather caches into a project
  output folder.
- Use explicit seeds when generating load profiles.
- Write generated profiles and validation summaries as declared project
  artifacts.
- Do not commit generated caches or project outputs.

The default weather cache is `examples/generated/cache`, which is ignored by
the repository.

## Limits

These generators are designed for transparent synthetic studies. They do not
certify an operational decision, replace measured load research, or guarantee
calibration to a feeder, climate zone, building vintage, appliance mix, or
customer class.

Before making operational claims, combine generated inputs with:

- project contract validation;
- objective-level sense checks;
- power-flow or thermal validation reports;
- explicit documentation of ratings, thresholds, seeds, and scenario
  assumptions.

## Relationship To Modeling

Use [Modeling](modeling.md) for durable asset entities: buildings, devices,
prosumers, DER, feeders, transformer thermal primitives, thermal forecasts, and
scenario overlays.

Use this page when the workflow needs synthetic trajectories or aggregate
stress-test assumptions to feed those models.

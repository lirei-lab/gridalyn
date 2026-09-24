# Assets

## What problem this layer solves

`twin` tells you what the network is. `assets` tells you what is *connected*
to it — the buildings, EV chargers, batteries, PV and other distributed energy
resources whose behavior a study actually cares about. It splits into two
concerns: **modeling** (typed specs for physical devices) and **datagen**
(reproducible synthetic time series for the ones that need one — mainly
residential load).

## The vocabulary

- **Feeder and network specs** — `RadialFeederSpec`
  (`gridalyn/assets/modeling/feeders.py`) describes a synthetic radial feeder
  as data, not as a hand-built pandapower network: `name`, `bus_count`,
  `sn_mva`, `base_voltage_kv`, `slack_vm_pu`, `loads_mw`, `q_to_p_ratio`, the
  line parameters `line_length_km`, `line_r_ohm_per_km`, `line_x_ohm_per_km`,
  `line_c_nf_per_km`, `line_max_i_ka`, optional per-segment `line_lengths_km`,
  the drawing offset `bus_y_step`, and `metadata`. `IeeeBenchmarkFeederSpec` /
  `IEEE_33_BUS_BENCHMARK` carry the IEEE 33-bus case the same way.
- **DER and prosumer specs** — `BatteryAsset`, `PVAsset`, `ProsumerAsset`
  (`energy_assets.py`), `DERDispatchAsset` (`der_dispatch.py`) and
  `VoltageControlDERSpec` (`voltage_control.py`) are the typed shapes a project
  declares its distributed resources in.
- **Transformer thermal limits** — `TransformerThermalModel` turns an ambient
  temperature trace into a dynamic active-power limit (IEEE C57.91
  steady-state inverse); `ThermalForecast` holds the result, and
  `build_thermal_forecast` builds one from a cold day of weather.
- **Building model tables** — `synthesize_building_model_tables`
  (`synthesis.py`) fills the twin's building tables from a static per-archetype
  lookup (`archetypes.py`, profile `north_america_residential_v1`). It has no
  time dimension. Its R, C and kW/m² values are **deliberately independent** of
  the RC simulator's below: one sizes structural records, the other drives a
  stateful simulation with pinned baselines. Two tables of R and C are not
  drift; change one only after reading why the other exists.
- **Load profiles** — per-dwelling kW time series, from one of two engines
  behind a single key. The rest of this section is about them.

### Two load engines, one key

`generate_residential_load_profiles(generator=...)`
(`gridalyn/assets/datagen/api.py`), and `spec.inputs.loadGeneration.generator`
in a project, route through `GridLoadFacade` to one of:

| `generator` | What it is | Dwelling population |
|---|---|---|
| `"parametric"` (default) | Packaged LightGBM macro-shape models for heating and background, plus per-dwelling AR diversity. No physics. | Fixed by the trained weights. An `archetype=` is **refused** with a `ValueError`: there is no envelope to re-parameterise. |
| `"thermodynamic"` | Per-dwelling RC thermal simulator (`make_buildings` / `simulate_buildings`, below). | `DEFAULT_ARCHETYPE`, or the `ThermalArchetype` passed as `archetype=`. |

Both return heating kW and background kW separately and sum them into a
`(time_steps, n_units)` DataFrame. **Both depend on the packaged background
weights**: the thermodynamic engine draws its appliance background from the
same macro model, so the LightGBM runtime matters to it too.

`loadGeneration` has no `archetype` key, so a project that selects
`thermodynamic` in YAML gets `DEFAULT_ARCHETYPE`. A study that carries its own
calibration — `ev_hosting_flex`, `admm_thermal_consensus`,
`dr_agent_interaction` — calls the agents API directly and states its
archetype there.

### The RC dwelling simulator

`gridalyn/assets/datagen/agents/` is the building model every study with its
own building calibration runs on. Each `Building` is a first-order RC air node heated by
electric baseboards, with an appliance background on top, and its parameters
are drawn per dwelling so that a fleet has realistic diversity.

- **Archetype** — a `ThermalArchetype` is the population a fleet is sampled
  from: mean and spread of `R` and `C`, baseboard capacity, cooling capacity,
  background load. Two ship:
    - `DEFAULT_ARCHETYPE` is derived from annual **energy** (degree-days over
      heating kWh). It answers "what does this dwelling use in a year?".
    - `QUEBEC_ALL_ELECTRIC` is derived from **installed capacity**, what a
      utility sizes for. On the same feeder it reads roughly twice the
      per-dwelling peak. It also lets appliance electricity heat the air node
      (`internal_gain_fraction = 0.6`), with `R` refitted to 5.7 alongside it
      against the metered Hydro-Québec homes: October–April
      monthly means within ±5 %, pooled peaks per home within ±1 % at 6, 12 and
      60 homes. The default archetype keeps no internal gains, as before.

    Neither is wrong, so a figure quoted from either belongs with the archetype
    it came from. A re-parameterised archetype consumes the same random draws
    in the same order, so changing a value never shifts an unrelated draw.

    `DEFAULT_ARCHETYPE` sizes its heaters to the design load: a dwelling's
    `p_heat_max` is its drawn capacity, floored at the steady-state loss at the
    −25 °C design temperature, `(T_SET − design) / R`. Drawn independently of
    `R`, about a quarter of default dwellings could not hold the setpoint at
    −25 °C. The floor applies after the draw, so every other sampled value is
    unchanged. It is opt-in, through `design_outdoor_c` and
    `heater_sizing_margin` on `ThermalArchetype`, so an archetype stated
    explicitly, `QUEBEC_ALL_ELECTRIC` included, samples exactly as before.

- **Controller** — `simulate_buildings(..., control=...)`:
  `"proportional"` (default) is a quantized 10-level law that reproduces
  historical runs; `"hysteresis"` gives each dwelling 3–6 zones with their own
  air temperature and thermostat, each latching independently. Real
  baseboards latch, so `"hysteresis"` is the one that reproduces cycling.
- **Integrator** — `Building.step(..., integrator=...)`: `"euler"` (default,
  forward Euler) or `"exact"` (exact-discrete RC update). `simulate_buildings`
  always uses the default.
- **Solar gains** — `ThermalArchetype(solar_aperture_m2=...)` with
  `simulate_buildings(..., irradiance_wm2=...)`: sunlight heats the air node
  at `solar_aperture_m2 × GHI / 1000` kW, split across zones like the other
  gains. The aperture lumps glazing, orientation and shading into one fitted
  number. Every shipped archetype keeps `0.0`, which is bit-identical to the
  model without sun. Against the metered homes, 2 m² with `R` 5.5 flattens
  the October–April monthly bias from −2.3 % … +4.7 % to −0.6 % … +0.5 %.
  It also reproduces the measured midday heating dip. `ev_hosting_flex`
  adopts that pair together with its water-heater recalibration.
  `QUEBEC_ALL_ELECTRIC` keeps `R` 5.7 with no aperture, because its callers
  pass no irradiance, and without sun the lower `R` would overheat. The
  synthetic weather source carries zero irradiance, so studies on it keep the
  no-sun pair too. Irradiance must share the temperature series' index, and each
  value must sit at its own timestamp. The committed study TMY labels hour
  means at their start, and the HQ export labels them at their end, so both
  need centring first (`load_annual_tmy_ghi`, `tools/fit_dwelling_year.py`).
- **Daytime setback** — `make_buildings(..., setback=SetbackBehaviour(...))`
  gives each dwelling a stochastic weekday setback schedule: whether it sets
  back at all, programmed versus occasional, departure and return hours,
  depth, and which days are empty. `HQ_MEASURED_SETBACK` carries the
  distributions fitted to metered Hydro-Québec homes, with `adoption=0.0` —
  no setback — because the metered record does not pin adoption to one value;
  a study sets and sweeps it. Setback draws come from their own stream, so
  attaching one never moves any other draw.
- **Building mass** — an archetype may add a second thermal node for the
  dwelling's walls, floors and furniture (`mass_capacitance_kwh_per_c`,
  `air_mass_resistance_c_per_kw`, `mass_conductance_share`, and
  `solar_mass_fraction` for the sunlight that lands on it). `R` still sets the
  steady-state loss; the mass only changes when heat flows. Off by default in
  every shipped archetype. It matters when the heat stops for hours: against
  EnergyPlus on 23 Québec fleet dwellings, the air node alone puts the indoor
  drop after an 8-hour outage at about twice the measured 11 °C, while
  air 1.8 kWh/°C, mass 10 kWh/°C, 2.0 °C/kW between them and 30 % of the
  envelope through the mass lands within 1.5 °C and keeps the metered cycling
  and pooled peaks within a few percent of the single node. Only the Euler
  integrator runs it.
- **Outages** — `simulate_buildings(..., outage=(start, end))` cuts power
  and appliance load for the window; when it ends every thermostat that has
  been calling draws at once. `measure_cold_load_pickup` compares that run
  with the same fleet run without the outage: indoor drop, pickup peak per
  home for groups of each size, recovery time and the energy repaid. The
  pickup peak in kW is set by installed capacity, so the ratio to normal load
  rises as the weather warms — 1.6 at −25 °C, 2.3 at −10 °C, 3.2 at 0 °C for
  groups of 60 on the Québec dwelling with its mass — and a transformer should
  be judged on the kW, not the ratio. A feeder restored in stages is one
  window per section: `generate_restoration_fleet`
  (`gridalyn.assets.datagen.agents.restoration`) runs each section through its
  own window from the same dwellings, seeds and appliance background, so a
  staged restoration, a simultaneous one and the no-outage reference differ by
  their windows alone. The `cold_load_pickup_feeder` study (see
  [The Studies](../start/studies.md)) solves that through a feeder of 75 kVA
  transformers: after 4 hours at −25 °C every transformer runs near 130 % of
  nameplate for hours, and staging trims the feeder-head peak but not the
  transformers' — each is switched back with all its homes at once.
- **Other agents** — `make_dhw_tank_fleet` generates thermostatic electric
  hot-water tanks with staggered reheats; `make_cold_coupled_ev_fleet`
  generates EV charging load; `EVCharger` is a stateful *actuator* for
  control studies, not a load generator.

### Which model for which question

- **The RC model** for anything that turns on coincidence, cycling or
  small-group peaks — with `control="hysteresis"`.
- **The EnergyPlus reference** for annual energy, per-end-use split or
  envelope response. It runs EnergyPlus through OpenStudio-HPXML over real
  NRCan Québec archetypes, in `tools/ochre_calibration/`, deliberately outside
  the SDK: the toolchain is ~1.6 GB and pins numpy below this repository's
  floor, so it cannot run in CI and hands over parquet instead. Nothing in the
  SDK calls it.
- **The metered record `datasets/hq`** when the two disagree — neither model
  is the arbiter for the other. `tests/test_building_diversity_vs_hq.py`
  encodes that comparison.
- **Not the parametric engine** for anything that turns on a diversified peak.
  Its homes draw their heating noise independently, so they peak together far
  less than measured ones: on a weather-matched cold week its coincidence
  factor runs 17–32 % below the metered curve from 6 to 24 homes, where
  the RC fleet sits within a few percent above it. It is a fixture-grade
  generator — fast, reproducible, right in shape and energy — and
  `tests/test_datagen_diversity.py` pins its coincidence factor so the gap
  cannot move unobserved.

The measured results — the flexibility relief on a disjoint holdout, the RC
model's error bound under full curtailment (it understates relief: read it as
conservative, not accurate), and the coincidence curve against `datasets/hq` —
are tracked as receipts, each number with its source file:
`tools/ochre_calibration/receipts/`.

The error bound also ships beside the model, as
`gridalyn.assets.datagen.agents.RC_CURTAILMENT_RELIEF_BOUND` (an `ErrorBound`,
equal to the receipt field for field). A study that takes flexibility relief
from the RC agents records it in the report that quotes the relief —
`inputs=[{"name": "rc_model_error_bound", "type": "error_bound",
**RC_CURTAILMENT_RELIEF_BOUND.as_dict()}]` — and
`tests/test_rc_error_bound_is_carried.py` fails a study that runs the agents
without it, unless it is exempted with the reason it takes no relief from
them.

The parametric engine's training data, feature set, weight digests and
temperature support are recorded in
`gridalyn/assets/datagen/models/weights/PROVENANCE.md`.
Below the coldest temperature it was trained on, a tree predicts a constant,
so the generator holds the tree at that edge and extends heating along a slope
fitted to the same metered record.

## The contract

`spec.inputs.loadGeneration` accepts exactly these keys; anything else is
rejected with an error that names the offending key and the supported set.

| Key | Required | Default | Meaning |
|---|---|---|---|
| `nUnits` | yes | — | Number of dwellings (columns). |
| `seed` | yes | — | Base seed. |
| `generator` | no | `parametric` | `parametric` or `thermodynamic`. |
| `day` | no | `peak` | `peak` (peak-demand day) or `cold` (coldest day) of the weather year. |
| `durationHours` | no | `24` | Length of the window. |
| `resolutionMinutes` | no | `15` | Time step. |
| `weather` | no | `synthetic` | Weather source. The SDK function defaults to `auto`; the project loader overrides it so a study is byte-stable across machines rather than depending on what PVGIS returns that day. |
| `multipliers` | no | — | Sub-mapping read by `load_generated_load_multipliers`, below. |

`multipliers` reduces the profiles to per-interval load multipliers:

| Key | Required | Default | Meaning |
|---|---|---|---|
| `intervals` | yes | — | Number of bins. |
| `peakMultiplier` | yes | — | Value the maximum bin is scaled to. |
| `intervalMinutes` | no | — | Bin length; required when `window` is `peak`. |
| `window` | no | `full` | `full` (the whole window) or `peak` (the sub-window around the peak). |

**The engine that ran is on the record.** Without the LightGBM runtime or the
packaged weights, the generator falls back to an analytical macro model that
produces different profiles from the same seed. It emits a warning when it
does, but still exits 0, so the warning alone is easy to lose. The run
manifest's `provenance.macro_model` records the deciding conditions —
`expected` (`lgbm` or `analytical`), `lightgbm_runtime`, `packaged_weights` —
and is what makes two runs comparable.

**Downstream shaping** goes through `aggregate_load_multipliers`,
`scale_profiles_to_peaks` and `coincident_peak_loads_mw`
(`gridalyn.assets.datagen`), not through ad-hoc DataFrame arithmetic in a stage
script. Weather comes from `download_tmy`, with `select_peak_load_day` and
`select_cold_day` picking the window.

## Using it

The parametric engine, as a project's `loadGeneration` block drives it:

```python
from gridalyn.assets.datagen.api import generate_residential_load_profiles

profiles = generate_residential_load_profiles(
    6, day="peak", seed=42, weather="synthetic"
)
print(profiles.shape, list(profiles.columns)[:3])
```
```text
  Peak-demand day (no-EV proxy): 2023-12-18  (occupied HDH = 35.22 °C, mean T = -18.3 °C)
(96, 6) ['unit_000', 'unit_001', 'unit_002']
```

Six units, one day at 15-minute resolution (96 = 24h × 4), columns
`unit_000`, `unit_001`, ... — deterministic for a fixed seed under
`weather="synthetic"`. The first line is the day selector's progress note, on
stderr, so stdout carries only what the snippet prints.

The RC simulator, with a stated archetype, latching thermostats and half the
dwellings setting back:

```python
from dataclasses import replace

import pandas as pd

from gridalyn.assets.datagen import download_tmy, select_cold_day
from gridalyn.assets.datagen.agents import (
    HQ_MEASURED_SETBACK,
    QUEBEC_ALL_ELECTRIC,
    make_buildings,
    simulate_buildings,
)

weather = select_cold_day(download_tmy(source="synthetic"))["temp_air"]
buildings = make_buildings(
    6,
    seed=42,
    archetype=QUEBEC_ALL_ELECTRIC,
    setback=replace(HQ_MEASURED_SETBACK, adoption=0.5),
)
runs = simulate_buildings(
    buildings, weather.resample("15min").mean(), control="hysteresis"
)
total_kw = pd.DataFrame({unit: run["p_total_kw"] for unit, run in runs.items()})
print(total_kw.shape, round(total_kw.sum(axis=1).max(), 1))
print([b.setback.adopts for b in buildings])
```
```text
  Coldest day: 2023-12-18  (daily mean -18.3 °C)
(96, 6) 62.5
[True, False, True, False, True, False]
```

`simulate_buildings` returns one DataFrame per dwelling, keyed by unit id,
with heating, cooling, background and total kW and the indoor temperature.
The last line shows which dwellings drew a setback schedule.

## Verifying it

The engines are not interchangeable, and the API says so — an archetype handed
to the parametric engine is refused rather than silently ignored:

```bash
python3 -c "
from gridalyn.assets.datagen.agents import QUEBEC_ALL_ELECTRIC
from gridalyn.assets.datagen.api import generate_residential_load_profiles
try:
    generate_residential_load_profiles(
        6, seed=42, weather='synthetic', archetype=QUEBEC_ALL_ELECTRIC
    )
except ValueError as error:
    print(error)"
```
```text
  Peak-demand day (no-EV proxy): 2023-12-18  (occupied HDH = 35.22 °C, mean T = -18.3 °C)
archetype applies to generator_type='thermodynamic' only; the parametric engine is a trained macro-shape model with no RC envelope to re-parameterise. Pass generator_type='thermodynamic', or drop the archetype to accept the packaged model as calibrated.
```

Or generate a full project's loads and check `provenance.macro_model` in its
run manifest to confirm which macro model actually ran:

```bash
uv run gridalyn project run projects/minimal_grid_project
python3 -c "
import json
m = json.load(open('projects/minimal_grid_project/outputs/manifests/project_run_manifest.json'))
print(m.get('provenance', {}).get('macro_model', 'not recorded by this project'))"
```

## Where this sits

`assets` sits on [Twin](twin.md): a building or DER only means something once
it can be anchored to a bus or transformer in the network model, via the
`building_grid_connectivity` table. What builds on `assets` is
[Simulation](simulation.md): the layer that takes the network plus what is
connected to it and asks whether the result is physically valid.

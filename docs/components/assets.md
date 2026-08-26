# Assets

## What problem this layer solves

`twin` tells you what the network is. `assets` tells you what is *connected*
to it — the buildings, EV chargers, batteries, PV and other distributed energy
resources whose behavior a study actually cares about. It splits into two
concerns: **modeling** (typed specs for physical devices) and **datagen**
(reproducible synthetic time series for the ones that need one — mainly
residential load).

## The vocabulary

- **Feeder and network specs** — `RadialFeederSpec` (`name`, `bus_count`,
  `sn_mva`, `base_voltage_kv`, `slack_vm_pu`, `loads_mw`, `q_to_p_ratio`, per-km
  line electrical parameters, plus `metadata`) describes a synthetic radial
  feeder as data, not as a hand-built pandapower network.
- **DER and prosumer specs** — `BatteryAsset`, `PVAsset`, `ProsumerAsset`
  (`gridalyn/assets/modeling/energy_assets.py`) and `DERDispatchAsset`
  (`der_dispatch.py`) are the typed shapes a project declares its distributed
  resources in.
- **The load-generation flow** — `spec.inputs.loadGeneration` in a project's
  YAML resolves through `load_generated_load_profiles`
  (`gridalyn/projects/model_inputs.py`) to
  `generate_residential_load_profiles` (`gridalyn/assets/datagen/api.py`),
  which returns a `(time_steps, n_units)` kW DataFrame on a
  `resolution_minutes` `DatetimeIndex`.
- **The macro model** — the `"parametric"` generator uses packaged LightGBM
  weights; `lightgbm` is a **base** dependency here, not optional, because
  without the runtime the generator silently falls back to a different
  analytical model. `provenance.macro_model` in the run manifest records which
  one a run actually used.

## The contract

`_LOAD_GENERATION_KEYS` is the whole accepted vocabulary for
`loadGeneration`: `generator`, `nUnits`, `seed`, `day`, `durationHours`,
`resolutionMinutes`, `weather`, `multipliers`. Only `nUnits` and `seed` are
required; everything else defaults. An unsupported key is rejected loudly,
never silently ignored — `_load_generation_mapping` names both the offending
key and the supported set in its error.

**Weather is fixed for study reproducibility.** The SDK default for `weather`
is `"auto"`, but the project loader overrides it to `"synthetic"`, so a
study's results are byte-stable across machines rather than depending on
whatever PVGIS returns that day.

**Two components, summed.** Internally, load generation produces heating kW
and background kW separately and sums them — a study never needs to reconcile
the two components itself, only the combined kW DataFrame.

## Which generator, and when

There is more than one way to produce a dwelling's load here, and they are not
interchangeable. Reading only the section above leaves the impression of a
single generator; the two heavy studies run on a different one.

| Route | Physics | Consumed by |
|---|---|---|
| `loadGeneration` → `generate_residential_load_profiles` | Packaged LightGBM macro model over aggregates, plus an analytical fallback | The six fast governed studies |
| `make_buildings` / `simulate_buildings` (`gridalyn/assets/datagen/agents/buildings.py`) | Per-dwelling RC air node, 3–6 independently latching zone thermostats, AR(1) background | `ev_hosting_flex`, `admm_thermal_consensus` |
| `tools/ochre_calibration/` | EnergyPlus via OpenStudio-HPXML over real NRCan Québec archetypes | Nothing — it is a reference, not a runtime generator |

The third is deliberately outside the SDK. Its toolchain is ~1.6 GB, it cannot
run in CI, and its dependencies pin numpy below this repo's floor, so it runs
out of process and hands over parquet.

**What each gets right, measured against `datasets/hq`.** The metered
all-electric subset (n=215, 15-minute) is the arbiter for both models; neither
is the arbiter for the other.

The RC model reproduces *cycling*, and that is its reason for existing: real
baseboards latch, so a house steps rather than glides, and the diversity of a
small group comes from that. On a weather-matched cold week its mean load runs
about 15 % below the metered set at the calibration this repo ships
(`R_STUDY_B = 7.5`); refitting that single constant to ≈ 6.2 closes the mean
error to under 1 % on a held-out half of the dwellings, while the peak stays
roughly 18 % low — a structural limit of distributing capacity across zones,
not something the constants can reach.

The EnergyPlus harness reproduces *envelope and energy*. Annual electricity
matches the metered median to 0.7 %, and at design-cold temperatures the
coincidence factor of a 6-home group matches exactly. Its weakness is the
mirror image: it models heating as modulating within the timestep, so it
under-represents cycling (19 % of 15-minute steps move more than 2 kW against
32 % measured over the same full year), and its annual-maximum coincidence is
too high at large pools.

The practical rule: use the RC model for anything that turns on coincidence,
cycling or small-group peaks, and the EnergyPlus reference for anything that
turns on annual energy, per-end-use split or envelope response. When the two
disagree, neither settles it — `datasets/hq` does, which is what
`tests/test_building_diversity_vs_hq.py` already encodes.

The parametric macro model is not characterised against the metered set here;
`provenance.macro_model` records which variant a run used, and that record is
what makes two runs comparable.

## Using it

```python
from gridalyn.assets.datagen.api import generate_residential_load_profiles

profiles = generate_residential_load_profiles(
    6, day="peak", seed=42, weather="synthetic"
)
print(profiles.shape, list(profiles.columns)[:3])
```
```text
(96, 6) ['unit_000', 'unit_001', 'unit_002']
```

Six units, one day at 15-minute resolution (96 = 24h × 4), columns
`unit_000`, `unit_001`, ... — deterministic for a fixed seed under
`weather="synthetic"`.

## Verifying it

```bash
python3 -c "
from gridalyn.projects.model_inputs import _LOAD_GENERATION_KEYS
print(sorted(_LOAD_GENERATION_KEYS))"
```
```text
['day', 'durationHours', 'generator', 'multipliers', 'nUnits', 'resolutionMinutes', 'seed', 'weather']
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

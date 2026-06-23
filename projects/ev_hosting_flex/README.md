# EV Hosting Flex Project

This workspace is the governed project implementation for the **EV hosting-capacity
flexibility** case study. It is a deliberately lighter, congestion-focused sibling
of `flexibility_cls`: it has **no** monetary market, settlement ledger, or
multi-stage stochastic clearing. The analytical focus is **line/feeder congestion**
and **per-node flexibility contracts** that curtail EV charging only during the few
congested winter hours.

**Thesis & headline.** A firm-connected EV may join the feeder only if the network
never congests — the single worst winter hour governs the limit. An EV under a
**flexibility contract** accepts a power cap during those few congested hours, so far
more can connect year-round:

```text
hosting_expansion_percent = (flexible_ev_count - firm_ev_count) / firm_ev_count
```

The cost of that growth is `curtailed_energy_fraction` (annual curtailed EV energy /
annual EV demand), kept under a YAML-configurable acceptability tolerance
(primary criterion: annual curtailed-energy fraction < 1%).

The workflow generates the project data, annual profiles, congestion metrics,
flexibility-contract accounting, peak-hour AC validation, case figures, and canonical
reports under this workspace:

```text
projects/ev_hosting_flex/outputs/
```

```bash
uv run gridalyn project validate projects/ev_hosting_flex
uv run gridalyn project validate projects/ev_hosting_flex --check-artifacts
uv run gridalyn project plan projects/ev_hosting_flex
uv run gridalyn project run projects/ev_hosting_flex --dry-run
uv run gridalyn project status projects/ev_hosting_flex --check-artifacts
uv run gridalyn project regression projects/ev_hosting_flex
```

`run` writes an execution manifest to:

```text
projects/ev_hosting_flex/outputs/manifests/project_run_manifest.json
```

`regression` compares the regenerated numerical outputs against the lightweight
baseline in:

```text
projects/ev_hosting_flex/baselines/results_baseline.json
```

(The regression baseline is sealed in Phase 12 — see *Pipeline & status* below.)

The project contract makes the case reproducible by declaring inputs, artifact
locations, workflow stages, reports, figures, and the run manifest emitted by the
project runner.

Paths in `project.yaml` and `workflow.yaml` are relative to the repository root
because the project sets:

```yaml
spec:
  pathBase: repo
```

That keeps project manifests readable: `projects/ev_hosting_flex/...` and
`configs/...` refer to repository paths instead of paths relative to the nested
project folder.

The project runtime is the Gridalyn SDK plus declared project and instance
artifacts. Stage scripts are thin: they call the SDK through its public facades and
keep the project-specific physics (radial downstream-sum proxy, per-node EV
allocation, flexibility-contract accounting) in project-local helper modules.

## Synthetic Network Creation

The workflow starts with `prepare_workspace`, a platform-owned stage that creates
the standard project output directories. The next stage, `prepare_topology_cache`,
builds the project-owned synthetic network cache used by the annual profiles,
congestion proxy, and pandapower checks.

Unlike `flexibility_cls`, this study uses a **project-local** building-footprint
GeoJSON (decision D-03) so the case is self-contained:

```text
projects/ev_hosting_flex/inputs/buildings.geojson
```

It also opts into **load-aware line/feeder sizing** through a project-local grid
config (so the shared `configs/grid/config.json` stays byte-identical and other
studies are unaffected):

```text
projects/ev_hosting_flex/inputs/synthetic_network_config.json   # lines.sizing.mode = load_aware
```

The cache stage runs:

```bash
uv run python projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py
```

It converts building footprints into a `PowerGridGraph` through the public
`gridalyn.simulation` facade, builds the synthetic LV/MV/HV topology, materializes
the pandapower model, **deterministically selects a single radial feeder**, and
derives the per-line/per-transformer thermal ratings (kW) and the radial
downstream-bus map the congestion proxy depends on. It writes:

```text
projects/ev_hosting_flex/outputs/cache/pg_graph_cache.pkl
projects/ev_hosting_flex/outputs/cache/pp_net_cache.pkl
projects/ev_hosting_flex/outputs/cache/grid_cache_meta.json
projects/ev_hosting_flex/outputs/cache/building_footprint_validation_report.json
projects/ev_hosting_flex/outputs/cache/topology_cache_manifest.json
projects/ev_hosting_flex/outputs/cache/line_transformer_ratings_kw.json
projects/ev_hosting_flex/outputs/cache/downstream_bus_map.json
projects/ev_hosting_flex/outputs/cache/feeder_selection.json
projects/ev_hosting_flex/outputs/cache/node_nameplate_kw.json
projects/ev_hosting_flex/outputs/cache/node_building_count.json
```

The cache stage **asserts the selected feeder is radial with no embedded
generation** (the precondition for the downstream-sum proxy) and fails loudly with a
located, remediating error otherwise. The topology cache manifest embeds the source
footprint SHA-256 so downstream profiles, congestion, and validation can be traced
back to the source building layer.

To rebuild the cache after changing the footprint source or sizing config, force a
rebuild:

```bash
uv run python projects/ev_hosting_flex/scripts/pipeline/prepare_topology_cache.py \
  --force-rebuild
```

## Pipeline & status

The study is the v1.2 `ev_hosting_flex` milestone and is built incrementally across
Phases 8–12. The 7-stage `workflow.yaml` DAG:

| # | Stage | Builds | Status |
|---|-------|--------|--------|
| 1 | `prepare_workspace` | standard `outputs/{data,json,reports,cache,figures}` dirs | live |
| 2 | `prepare_topology_cache` | synthetic radial twin + per-line/transformer kW ratings + downstream map | live (Phase 8) |
| 3 | `generate_annual_profiles` | deterministic 8760h winter-peaked base load + per-node EV unit load | live (Phase 9) |
| 4 | `compute_congestion` | radial downstream-sum proxy loading, congestion metrics, **firm** hosting limit | live (Phase 9) |
| 5 | `apply_flexibility_contracts` | per-node EV cap in congested hours, curtailment accounting, **flexible** limit | stubbed (Phase 10) |
| 6 | `validate_powerflow` | pandapower AC at peak hours; proxy↔AC error + voltage sanity | stubbed (Phase 11) |
| 7 | `build_study_reports` | canonical reports, figures, regression baseline | stubbed (Phase 12) |

Project-local physics lives in thin helper modules consumed by the stage scripts:

```text
projects/ev_hosting_flex/scripts/_topology.py     # kW ratings, radial downstream BFS, feeder selection
projects/ev_hosting_flex/scripts/_profiles.py     # parametric winter-peaked base + per-node EV charging
projects/ev_hosting_flex/scripts/_congestion.py   # downstream-sum proxy, congestion metrics, firm sweep
```

## Line loading (proxy) and the firm limit

For a radial feeder with no embedded generation, line/transformer flow ≈ the sum of
demand at all downstream nodes, so:

```text
loading_percent = downstream_kw / element_rating_kw * 100
```

This lets the study sweep 8760h × N EV-penetration levels in seconds without a
per-hour AC solve. The **firm** hosting limit (`firm_ev_count`) is the largest swept
EV count with **zero** overloads on any line or the head transformer at any of the
8760 hours, computed at integer `EV_SWEEP` granularity. It is the headline
denominator; the **flexible** limit (Phase 10) is its numerator. pandapower AC power
flow (Phase 11) validates the proxy at the worst peak hours.

## Network sizing basis (diversity reconciliation)

The twin is sized in **two layers that use different diversity assumptions**, and the
feeder is deliberately re-sized so it operates cleanly **before** any EV connects — so
the EVs, not the base load, are what cause congestion.

1. **Topology layer (SDK generator).** The synthetic network is built with
   `diversity_factor_lv = 5`, so each building's coincident contribution is
   `max_load_per_building / 5 = 50 / 5 = 10 kW`. This 10 kW/home coincident demand
   (≈32.35 MW twin-wide) drives the transformer **count** and the initial load-aware
   line `max_i_ka` selection.

2. **Profile layer (this study, Phase 9).** The deterministic 8760h base load
   (`_profiles.py`) is **fully coincident** — every building follows the same
   `nameplate × winter × daily × weekly` envelope, so they all peak in the same winter
   evening hour. That peak reaches **≈1.764 × nameplate** (`WINTER_PEAK_FACTOR` plus the
   daily/weekly pattern), i.e. **17.64 kW/home**, not the 10 kW the topology assumed.

These two layers disagree by the **annual peak factor ≈ 1.764**, which left the
selected feeder overloaded at **zero EVs** (the head transformer `transformer:78` was
199.5 kW vs a 458.6 kW winter base peak → 229.9 %; interior lines such as `line:1454`
were at 199 %). That made `firm_ev_count = 0` — a degenerate headline denominator.

The fix (stage 2, project-local, `_topology.size_feeder_subtree_kw`) re-sizes **all 27
elements of the selected feeder subtree** — the head transformer **and** the interior
lines — to the annual winter-peak downstream demand divided by the
`TRANSFORMER_UTILIZATION_MARGIN` (0.8):

```text
rating_kw = downstream_nameplate_kw × annual_peak_factor(≈1.764) / 0.8
# head transformer:78  199.5 kW  →  574 kW
```

After the resize, at **0 EVs the worst element sits at ≈79.9 %** (the ~80 % target,
recorded in `feeder_selection.json → feeder_transformer_sizing`), so the base feeder is
healthy and congestion is **EV-driven**: `firm_ev_count = 20`, first overload at 40 EVs.

> **Diversity assumption (D-01 / FUT-04).** The profile is fully coincident
> (`diversity = 1`). For an **hourly, all-electric, cold-climate** feeder this is
> **defensible** — space-heating load is intrinsically highly coincident (cold-driven
> peaks line up across homes; the literature puts the heating diversity factor at
> ≈ **1.0–1.2**, i.e. ≤ ~15 % peak reduction). It is at most *mildly* conservative —
> **not** the 1.5–2.5 range, which applies to instantaneous thermostat cycling or mixed
> loads, not the hourly heating envelope. The per-home winter peak (~17.6 kW) sits at the
> high end of the realistic ~10–15 kW band for a Québec all-electric dwelling (~13 kW
> installed baseboard + DHW/appliances). The parameter that is genuinely *inconsistent*
> with this load type is the **topology** `diversity_factor_lv = 5` (suited to mixed
> urban load, not all-electric heat) — but the stage-2 subtree resize already sizes the
> feeder to the diversity-1 profile, so that knob now only affects transformer *count*.
> See [`CALIBRATION.md`](CALIBRATION.md) for the Québec sources and the
> `TRANSFORMER_UTILIZATION_MARGIN` / `diversity_factor_lv` calibration. Stochastic
> per-home diversity is deferred to FUT-04.

## Configuration

The tunable knobs are centralized in `projects/ev_hosting_flex/scripts/config.py`
and read by every stage (reproducibility conventions are locked here):

| Knob | Default | Meaning |
|------|---------|---------|
| `POWER_FACTOR` | `0.95` | pf for the kW rating derivation (line & transformer) |
| `LINE_LOADING_LIMIT_PERCENT` | `100` | congestion threshold (% loading) |
| `WINTER_PEAK_FACTOR` / `SUMMER_TROUGH_FACTOR` | `1.6` / `0.7` | seasonal envelope of the base building load |
| `EV_UNIT_KW` | `7.2` | per-EV charging power |
| `CHARGING_WINDOW` | `(17, 22)` | daily charging window (overlaps the winter evening peak) |
| `DIVERSITY_FACTOR` | `0.6` | simultaneous-draw fraction at a node |
| `EV_SWEEP` | `(0, 20, …, 200)` | EV-penetration grid the firm/flexible sweeps walk |
| `CALENDAR_HOURS` | `8760` | annual hourly horizon (non-leap year) |
| `SEED` / `DTYPE` / `ROUND_DECIMALS` | `42` / `float64` / `6` | determinism + pre-write rounding (1e-6 regression tolerance) |
| `FEEDER_ID` | `None` | feeder-selection override (default: deterministic max-downstream-load) |

## Design & requirements

The approved design contract and the requirement IDs this study implements:

```text
docs/superpowers/specs/2026-06-22-ev-hosting-flex-design.md   # approved design (the requirements source)
```

`flexibility_cls` is the gold-standard reference for the topology-cache pattern, the
`ProjectScript` report contract, and the regression baseline.

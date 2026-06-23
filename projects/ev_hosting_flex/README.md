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

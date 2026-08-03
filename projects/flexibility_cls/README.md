# Flexibility CLS Project

This workspace is the governed project implementation for the EV capacity
limitation case study.

> **Scope — read `LIMITATIONS.md` before citing numbers.** The contribution here
> is the **market mechanism** (locational CLS clearing, Soft/Hard flexibility
> allocation, settlement, network-impact validation) on a *synthetic distribution
> feeder*. The **load hypotheses are not calibrated to Québec**: the building base
> uses the SDK defaults and peaks at 5.9 kW/home at −23 °C (41 % below the HQ
> 10–15 kW design band; real HQ feeders measure 8.8 kW/home), and the SDK EV
> generator has no cold coupling and pre-smooths each charging session — so
> Québec-specific or cold-climate claims about hosting capacity, winter peak, or
> the size of the flexibility opportunity are **not supported by this load model**.
> For the validated Québec archetype see `projects/ev_hosting_flex/`.

The workflow generates the project data, scenarios, market/dispatch outputs,
case-analysis figures, validation JSON, operational artifacts, and canonical
reports under this workspace:

```text
projects/flexibility_cls/outputs/
```

Operational artifacts are emitted under:

```text
projects/flexibility_cls/outputs/operations/
projects/flexibility_cls/outputs/reports/operational_kpi_report.json
```

They materialize active network constraints, provider offers, dispatch
instructions, settlement records, and mechanism-intelligence KPIs from the
digital-twin flexibility layer. `outputs/operations/operation_run.json` records
the auditable operation execution, and `outputs/operations/operations_catalog.json`
indexes those files for dashboard/API consumers while marking scenario
availability explicitly.

```bash
uv run gridalyn project validate projects/flexibility_cls
uv run gridalyn project validate projects/flexibility_cls --check-artifacts
uv run gridalyn project plan projects/flexibility_cls
uv run gridalyn project run projects/flexibility_cls --dry-run
uv run gridalyn project status projects/flexibility_cls --check-artifacts
uv run gridalyn project regression projects/flexibility_cls
```

`run` writes an execution manifest to:

```text
projects/flexibility_cls/outputs/manifests/project_run_manifest.json
```

`regression` compares the regenerated numerical outputs against the lightweight
baseline in:

```text
projects/flexibility_cls/baselines/results_baseline.json
```

It writes a machine-readable report to:

```text
projects/flexibility_cls/outputs/reports/regression_report.json
```

The project contract makes the case reproducible by declaring inputs, artifact
locations, workflow stages, reports, figures, and the run manifest emitted by
the project runner.

Paths in `project.yaml` and `workflow.yaml` are relative to the repository root
because the project sets:

```yaml
spec:
  pathBase: repo
```

That keeps project manifests readable: `projects/flexibility_cls/...`,
`instances/default/digital_twin/...`, and `configs/...` refer to repository paths
instead of paths relative to the nested project folder.

The project runtime is the Gridalyn SDK plus declared project and instance
artifacts.

## Synthetic Network Creation

The workflow starts with `prepare_workspace`, a platform-owned stage that creates
the standard project output directories. The next stage, `prepare_topology_cache`,
creates the project-owned synthetic network cache used by the stochastic profiles
and pandapower checks. The default input is the clipped Trois-Rivieres
building-footprint GeoJSON declared in `project.yaml`:

```text
examples/tutorials/data/buildings_inside_polygon.geojson
```

That stage runs:

```bash
uv run python projects/flexibility_cls/scripts/pipeline/prepare_topology_cache.py
```

It converts building footprints into a `PowerGridGraph`, builds the synthetic
LV/MV/HV topology, materializes the pandapower model, and writes:

```text
projects/flexibility_cls/outputs/cache/building_footprint_validation_report.json
projects/flexibility_cls/outputs/cache/pg_graph_cache.pkl
projects/flexibility_cls/outputs/cache/pp_net_cache.pkl
projects/flexibility_cls/outputs/cache/grid_cache_meta.json
projects/flexibility_cls/outputs/cache/topology_cache_manifest.json
```

The validation report records footprint count, geometry types, CRS, bounds,
area summary, invalid-geometry warnings, and the source SHA-256 hash. The
topology cache manifest embeds that lineage so downstream profiles, dispatch,
and validation can be traced back to the source building layer.

To run the same project with a different footprint source, first prepare a
project-local GeoJSON from OSMnx or Microsoft Global ML Building Footprints,
then force the topology cache to rebuild:

```bash
uv run python projects/flexibility_cls/scripts/pipeline/prepare_topology_cache.py \
  --input-file projects/flexibility_cls/inputs/buildings.geojson \
  --force-rebuild
```

The source preparation commands and quality checks are documented in:

```text
docs/tutorials/synthetic-network-from-geojson.md
```

Full user-facing documentation lives in:

```text
docs/workflows/flexibility-cls.md
docs/platform/projects-and-workflows.md
```

# Build A Twin

A twin instance is a named workspace under `instances/<name>/` holding one
network model and everything derived from it: scenarios, time series, the
semantic graph, reports and the dashboard catalog. The network model is a
digital *model* in the sense [Twin](../components/twin.md) defines; a
deployment becomes a digital shadow only when it is fed measured data, which
[Feed Measured Data](feed-measured-data.md) covers. `instances/default/` is the
instance the dashboard and the CLI defaults use.

## An Instance Declares How It Is Built

Every instance carries a `twin.yaml` contract naming the source its base tables
are built from and the row counts that build produces. The shape, with the
counts and the digest left for the real file to supply:

```yaml
apiVersion: gridalyn/v1
kind: TwinInstance
metadata:
  name: default                     # must match the directory name
spec:
  base:
    adapter: synthetic_pandapower   # a registered network adapter id
    footprints: projects/ev_hosting_flex/inputs/buildings.geojson
    config: configs/grid/config.json
    expected:                       # row counts the declared source produces
      buildings: <count>
      buses: <count>
      connectivity: <count>
      lines: <count>
      loads: <count>
      transformers: <count>
  weather:
    path: gridalyn/assets/datagen/data/tmy_trois_rivieres.csv
    sha256: <digest>
```

Paths resolve against the workspace root. Every field shown is required, and a
missing or malformed one is refused with the contract path, the YAML location
and the expected shape (`gridalyn/twin/network/instance.py`).

- **`expected`** is a pin, not a comment.
  `tests/test_twin_instance_contract.py` rebuilds the default instance from its
  declaration on every test run and fails if any pinned count moves, so a change
  that reshapes the twin is caught where it happens. The suite rebuilds only
  the default instance; another instance's pins are loaded, not rebuilt.
- **`weather`** pins the TMY the building loads are built from. Unpinned,
  `download_tmy` takes PVGIS or a synthetic fallback depending on whether the
  machine has network, records neither choice, and the two give different
  loads. The EV power-flow step refuses a snapshot whose digest does not match.
  Re-pin deliberately with `python tools/snapshot_weather.py` (needs network),
  which writes the CSV and prints the digest to declare.

This is the posture a study takes in its `project.yaml`: the inputs are
declared, so the outputs can be checked.

## Rebuild An Instance

In this repository `default` is also the committed instance, so rebuilding it
rewrites the tracked files under `instances/default`; `git checkout --
instances/` restores them.

```bash
uv run gridalyn twin base --instance default
```

The command reads the instance's contract, builds the network fresh from the
declared footprints and grid config, and writes the five base tables plus
`metadata.json` into `instances/<name>/digital_twin/base/`. It prints the
contract it built from, the resolved model identity and the row counts.

The build is deterministic: the same declaration produces byte-identical
Parquet tables, and the same `model_version_id` for the same output directory.
`metadata.json` records each table's row count and SHA-256, so a rebuild can be
checked against the committed one.

!!! warning "A rebuild rewrites tracked files"
    The Parquet tables are gitignored, but two files the rebuild writes are
    tracked: `base/metadata.json` and
    `reports/network_adapter_validation_report.json`. Their timestamps always
    change; the config hash and model id change too whenever the grid config
    has changed since the committed export. Review the diff before committing
    it, or build somewhere else.

To build without touching the instance, send the output elsewhere:

```bash
uv run gridalyn twin base --out-dir /tmp/gridalyn-base
```

An output directory outside `instances/<name>/digital_twin/base/` receives the
validation report beside the tables, so the working tree stays clean.

### Override the declaration

For a one-off experiment, or a source the contract does not describe, the
export takes these options. They belong to the export script, and
`gridalyn twin base --help` lists them after the subcommand's own `--root` and
`--instance`:

| Option | Overrides | Default |
| --- | --- | --- |
| `--footprints <geojson>` | `spec.base.footprints` | the contract's footprints |
| `--config <json>` | `spec.base.config` | the contract's config, else `configs/grid/config.json` |
| `--adapter-id <id>` | `spec.base.adapter` | the contract's adapter, else `synthetic_pandapower` |
| `--source-dir <dir>` | the whole contract, for adapters that read a source directory such as `cim_parquet` | none |
| `--out-dir <dir>` | where the tables and `metadata.json` are written | `instances/<name>/digital_twin/base/` |
| `--cache-dir <dir>` | the cache read when no footprints are declared | `instances/<name>/digital_twin/cache/` |

```bash
uv run gridalyn twin base --footprints <path/to/buildings.geojson>
uv run gridalyn twin base --adapter-id cim_parquet --source-dir <path/to/cim>
```

An instance with no `twin.yaml` and no `--footprints` falls back to reading a
previously built network from its `cache/` directory (`pp_net_cache.pkl`). It
works, but what it produces depends on a gitignored pickle nobody can name
afterwards, and the command prints a warning when it takes that path.

## Add A New Instance

Create the directory, write its contract, then build it:

```text
mkdir -p instances/my_feeder
$EDITOR instances/my_feeder/twin.yaml     # metadata.name must be my_feeder
uv run gridalyn twin base --instance my_feeder
```

`expected` must hold at least one integer count for the contract to load, and
the export does not compare against it: write the counts the first build prints
into `expected`. An instance directory without a contract fails
`test_every_instance_declares_a_contract`, which is deliberate: an instance
nobody can rebuild is an artifact, not a model.

The building models are synthesized at one floor area for every building, not
from the footprints: a ground print is not a floor area without a storey count.
Declare it under `spec.models.floorArea`, as a positive `valueM2` and a `source`
citing where the figure comes from; a value without a source is refused.
Without the block the SDK default of 100 m² applies, and the building model
manifest records it as `sdk_default` rather than `declared`. The `default`
instance declares 148.7 m², the average single-detached floor space in Quebec
from Natural Resources Canada's Comprehensive Energy Use Database; its
`twin.yaml` carries the derivation.

`twin base` reads the contract, and the footprints, grid config and weather
snapshot it names, from the workspace root: `--root` when given, otherwise the
current directory. The steps above work in any workspace that holds those
files, not only in the repository; pass `--root <workspace>` to build an
instance of a workspace you are not standing in. When the contract is absent,
the fallback message names the `twin.yaml` path it looked for.

## Plan The Full Build

`gridalyn twin build` chains every layer of an instance, from the base export
through scenarios, building models and the semantic graph to the canonical
reports and the dashboard catalog. Plan it without writing into the
repository:

```bash
mkdir -p /tmp/twin-plan
uv run gridalyn twin build --dry-run --skip-heavy --root /tmp/twin-plan
```

It prints the planned steps and writes nothing; add `--manifest <path>` to keep
the plan as a file. `--skip-heavy` drops the EV power-flow step and every step
that reads its output (the transformer overload report, locational clearing
and the dashboard catalog), and the build manifest lists each of them as
`skipped` with the reason. `--instance` selects another instance, and
`--capabilities` names the capability layers to include.

!!! warning "A full build rewrites tracked files"
    Without `--dry-run`, `twin build` writes the build manifest
    (`instances/<name>/digital_twin/reports/digital_twin_build_manifest.json`)
    and every layer under its root. Run from the repository root, that
    rewrites the `default` instance's tracked manifests, reports and dashboard
    catalog. Keep `--root` on a scratch directory unless you intend to
    regenerate the shipped instance.

## Next Steps

- [Synthetic Networks From GeoJSON](synthetic-network-from-geojson.md) builds a
  network from your own building footprints; its worked example is the
  `synthetic_geojson_feeder`
  study, one of the CI fixture studies.
- [Feed Measured Data](feed-measured-data.md) turns a deployment into a digital
  shadow, with the
  `measured_shadow_feeder`
  study as its worked example.
- [The studies](../start/studies.md) lists every study and its tier.

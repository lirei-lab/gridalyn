# Network Repository

The network repository is the SDK boundary for reading model snapshots and
topology relationships. It should let applications and workflows ask for the
part of the model they need without knowing how the underlying Parquet or source
adapter is organized.

## Current Use Cases

- load base network assets;
- inspect buses, lines, transformers, and buildings;
- connect scenario assets to topology;
- support dashboard catalogs and reports;
- support semantic graph generation;
- support network-impact and flexibility operations.

## The Declared Column Contract

The repository does not guess at column names when it reads the base tables.
Every column is declared once in `gridalyn.twin.network.schema`, by the **role**
it plays rather than by a spelling:

- A `ColumnSpec` declares a role, an **ordered** set of accepted spellings, a
  dtype, whether a non-empty frame must carry the column, and which canonical
  artifact the column references. More than one spelling means different in-repo
  producers genuinely write different names for the same role — the CIM adapter
  writes `feeder_id` where the synthetic adapter writes `lv_feeder_bus_id` — and
  the resolution order is behaviour, not decoration.
- Spellings that no producer writes were **removed** rather than kept as
  defensive noise.

The contract is a Python module, not a JSON Schema, for two reasons. Its two
load-bearing ideas — an ordered alias set per role, and which columns reference
the bus table — have no JSON Schema vocabulary, so they would degrade into
convention encoded in custom keys. And a `.py` file ships under
`include = ["gridalyn*"]` by construction, which makes the packaging defect class
("a runtime-resolved data file missing from the wheel") structurally impossible
rather than merely avoided.

The module is reachable at `gridalyn.twin.network.schema` and is deliberately
**not** re-exported from the `gridalyn.twin` facade: it is the contract between
the repository and its adapters, and both of its production consumers live
inside that layer.

## Validation Has Three States, Not Two

`validate_integrity()` distinguishes cases that used to collapse into one:

| Situation | Result |
| --- | --- |
| A required base artifact is **absent** | **error** — `valid` is `False` |
| The artifact exists but carries **no rows** | **warning** — `valid` stays `True` |
| A row-bearing table is missing a declared **required** column | **error** |
| Everything present and declared | checked, then reported |

The middle row is forced by evidence rather than chosen for leniency: the CIM
parquet adapter legitimately exports zero-row tables.

Before this contract existed, an empty directory validated as `valid = True` —
an absent model was indistinguishable from an intact one, and at least one
caller had hand-rolled its own absence check to work around it. The error now
names the artifact, the `base_dir`, and the command that fixes it:

```text
<base_dir>/grid_buses.parquet: required base artifact 'grid_buses' is absent, so
this model cannot be told apart from an intact one (base_dir=<base_dir>); build
the base with `gridalyn twin base` (or `gridalyn twin build`), or point the
repository at a directory holding all of: building_grid_connectivity.parquet,
buildings.parquet, grid_buses.parquet, grid_lines.parquet,
grid_transformers.parquet
```

Missing *provenance* is a separate, softer axis. A base directory without a
`metadata.json` loads with a `MissingProvenanceWarning` and
`provenance_status` recording the degradation; the repository accepts
`provenance="require" | "warn" | "ignore"` to escalate or silence it. The two
axes stay orthogonal on purpose — `build_base_metadata` validates the artifacts
*before* writing the manifest it produces, so forcing `require` would make
manifest generation impossible.

## Target Queries

| Query | Purpose |
| --- | --- |
| by feeder | Run analysis on a utility-relevant network section. |
| by transformer | Evaluate local overload and flexibility relief. |
| by building or asset | Trace controllable assets to network constraints. |
| by scenario | Load only active assets for a study case. |
| downstream zone | Support locational clearing and targeted validation. |

See [Network Model](../concepts/network-model.md) and
[Public Python API](public-api.md).

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

## Target Queries

| Query | Purpose |
| --- | --- |
| by feeder | Run analysis on a utility-relevant network section. |
| by transformer | Evaluate local overload and flexibility relief. |
| by building or asset | Trace controllable assets to network constraints. |
| by scenario | Load only active assets for a study case. |
| downstream zone | Support locational clearing and targeted validation. |

See [Network Model](../concepts/network-model.md) and
[Public Python API](../development/public-api.md).

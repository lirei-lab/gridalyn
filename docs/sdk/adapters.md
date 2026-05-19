# Adapters

Adapters translate external or generated sources into Gridalyn model contracts.
Synthetic generation is one adapter path, not the platform itself.

## Adapter Types

| Adapter type | Role |
| --- | --- |
| GeoJSON | Read, validate, filter, and prepare geographic source data from OSMnx, Microsoft Building Footprints, or local GIS exports. |
| Synthetic network | Generate synthetic distribution network snapshots from configs and geography. |
| Pandapower | Build or consume simulation-ready network models. |
| CIM-like Parquet | Move toward utility-grade CIM-aligned model snapshots. |
| Future utility adapters | GIS, DMS, AMI, SCADA, DERMS, market, and weather integrations. |

## Rules

- Adapters should write validation reports.
- Adapters should preserve source IDs and lineage.
- Adapters should produce canonical model contracts rather than workflow-specific
  tables.
- Project scripts may call adapters, but adapter logic belongs in `gridalyn`.

See [Python SDK Architecture](../development/core-package-architecture.md).

For a complete footprint-to-grid walkthrough, see
[Synthetic Networks From GeoJSON](../tutorials/synthetic-network-from-geojson.md).

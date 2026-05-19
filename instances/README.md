# Instances

`instances/` contains materialized Gridalyn workspaces. An instance is runtime
state: generated topology tables, scenarios, time series, semantic graph
artifacts, reports, and dashboard catalogs.

The default local/demo instance is:

```text
instances/default/digital_twin/
```

The repository root keeps `digital_twin` as a compatibility symlink to that
directory so existing CLI defaults and dashboard URLs such as
`/digital_twin/dashboard/catalog.json` continue to work.

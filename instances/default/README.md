# Default Instance

This is the default local Gridalyn digital-twin instance used by the dashboard,
documentation examples, and compatibility CLI defaults.

The important contract is inside:

```text
digital_twin/
  base/
  scenarios/
  timeseries/
  models/
  flexibility/
  semantic/
  reports/
  dashboard/
```

Generated heavy artifacts such as Parquet time series remain ignored by Git.
Small JSON manifests and catalogs can be versioned when they document the
demo/default state.

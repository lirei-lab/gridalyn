# Reporting

Reporting modules turn workflow and operation outputs into stable JSON
contracts. Reports are the bridge between simulations, dashboards,
reproducibility checks, and external review.

## Report Principles

- include model and run lineage;
- reference inputs and outputs explicitly;
- avoid hidden notebook state;
- keep large time-series in Parquet and summarize them in JSON;
- make dashboard consumption predictable.

## Current Outputs

- project run manifests;
- digital twin report manifests;
- scenario summaries;
- transformer overload reports;
- flexibility and network-impact reports;
- figure inventories and external-review summaries.

See [Reports And Manifests](../platform/reports.md).

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

## Shared Helpers

Use `gridalyn.interfaces.reporting` for report-shaping utilities that are not
specific to one project. For example, `dispatch_timeseries_metrics` summarizes
a dispatch Parquet/DataFrame into JSON-safe metrics:

```python
from gridalyn.interfaces.reporting import dispatch_timeseries_metrics

metrics = dispatch_timeseries_metrics("projects/my_case/outputs/data/dispatch.parquet")
```

Use `gridalyn.interfaces.viz` for small Matplotlib conventions that should be
consistent across demos, such as hour-of-day axes and paired PNG/PDF exports:

```python
from gridalyn.interfaces.viz import apply_hour_axis, save_figure_pair

apply_hour_axis(ax, start=0, end=28)
save_figure_pair(fig, "projects/my_case/outputs/figures/profile.png")
```

Project scripts still own figure content, captions, and study-specific visual
choices. The SDK owns repeated artifact, time-axis, and report-summary
mechanics.

See [Reports And Manifests](../reference/reports.md).

# Core Concepts

Gridalyn concepts explain the durable objects that appear across the SDK,
projects, reports, semantic graph, and dashboard. Read these pages when you
need to understand the vocabulary before using commands or APIs.

## Concept Map

<div class="landing-grid landing-grid--cards">
<a class="landing-card" href="../../platform/digital-twin/">
<h3>Digital Twin Core</h3>
<p>The canonical artifact layer for network, asset, scenario, time-series, semantic, report, and application data.</p>
</a>
<a class="landing-card" href="../network-model/">
<h3>Network Model</h3>
<p>Connectivity nodes, line segments, transformers, loads, feeders, and utility topology identity.</p>
</a>
<a class="landing-card" href="../data-and-artifact-model/">
<h3>Artifacts</h3>
<p>The Parquet, JSON, report, manifest, and figure conventions that make outputs traceable and reproducible.</p>
</a>
<a class="landing-card" href="../scenarios/">
<h3>Scenarios</h3>
<p>How Gridalyn represents changes in demand, assets, operations, forecasts, and simulation assumptions.</p>
</a>
<a class="landing-card" href="../model-states/">
<h3>Model States</h3>
<p>How generated data, validated data, operational states, and application-ready states are separated.</p>
</a>
<a class="landing-card" href="../../reference/semantic-graph/">
<h3>Semantic Graph</h3>
<p>North America-oriented ontology alignment for grid assets, buildings, DER, telemetry metadata, and flexibility operations.</p>
</a>
</div>

## Reading Order

1. Start with [Digital Twin Core](../platform/digital-twin.md).
2. Read [Network Model](network-model.md) to understand topology identity.
3. Read [Artifacts](data-and-artifact-model.md) before writing generated data.
4. Read [Scenarios](scenarios.md) and [Model States](model-states.md) before
   building a new project.
5. Read [Semantic Graph](../reference/semantic-graph.md) when artifacts
   need ontology-aligned relationships or graph export.

## Rule Of Thumb

If a term appears in project YAML, report JSON, CLI output, dashboard catalogs,
or public SDK APIs, it should be explainable from this section. If it is only an
implementation detail, it belongs in SDK or Development documentation instead.

<section class="home-hero">
  <p class="home-kicker">Distribution grid digital twin platform</p>
  <h1>Gridalyn</h1>
  <p class="home-lead">
    Build distribution-grid digital twins, run reproducible project workflows,
    validate grid operations, and publish traceable reports from one governed
    Python platform.
  </p>
  <div class="home-actions">
    <a class="md-button md-button--primary" href="getting-started/quickstart/">Quickstart</a>
    <a class="md-button" href="projects/overview/">Explore demos</a>
  </div>
</section>

Gridalyn combines a reusable Python SDK, governed project workflows, network
simulation, semantic artifacts, flexibility operations, and dashboard-ready
reports. The documentation is organized by what a user is trying to do, not by
repository folders.

## Choose A Path

<div class="home-grid home-grid--triplet">
  <a class="home-card" href="getting-started/quickstart/">
    <span class="home-card__title">Run Gridalyn</span>
    <span class="home-card__text">Install the workspace, check the CLI, run a compact demo, and inspect generated outputs.</span>
  </a>
  <a class="home-card" href="platform/overview/">
    <span class="home-card__title">Understand The Platform</span>
    <span class="home-card__text">Learn the digital twin core, platform layers, project model, operations layer, and application surfaces.</span>
  </a>
  <a class="home-card" href="concepts/overview/">
    <span class="home-card__title">Learn Core Concepts</span>
    <span class="home-card__text">Understand network models, scenarios, artifacts, model states, and semantic graph relationships.</span>
  </a>
  <a class="home-card" href="sdk/overview/">
    <span class="home-card__title">Build With The SDK</span>
    <span class="home-card__text">Use the <code>gridalyn</code> Python package for models, simulation, operations, reports, semantics, and automation.</span>
  </a>
  <a class="home-card" href="projects/overview/">
    <span class="home-card__title">Explore Demos</span>
    <span class="home-card__text">Run benchmark feeders, synthetic GeoJSON networks, prosumer markets, optimization demos, and RL voltage control.</span>
  </a>
  <a class="home-card" href="platform/operations/">
    <span class="home-card__title">Design Operations</span>
    <span class="home-card__text">Study providers, aggregators, locational clearing, dispatch, settlement, network-impact verification, and KPIs.</span>
  </a>
</div>

## Platform Model

<div class="platform-diagram">
  <div class="platform-flow">
    <div class="platform-step">
      <span class="platform-step__number">01</span>
      <div>
        <span class="platform-step__eyebrow">Foundation</span>
        <strong>Governance</strong>
        <p>IDs, units, lineage, validation rules, artifact policy, and run manifests.</p>
      </div>
    </div>
    <div class="platform-arrow">
      <span>defines trusted contracts</span>
    </div>
    <div class="platform-step platform-step--primary">
      <span class="platform-step__number">02</span>
      <div>
        <span class="platform-step__eyebrow">Core</span>
        <strong>Digital Twin</strong>
        <p>Network model, assets, scenarios, model states, telemetry metadata, and semantic graph.</p>
      </div>
    </div>
    <div class="platform-arrow">
      <span>feeds reusable capabilities</span>
    </div>
    <div class="platform-step">
      <span class="platform-step__number">03</span>
      <div>
        <span class="platform-step__eyebrow">Execution</span>
        <strong>Projects, Simulation, Operations</strong>
        <p>Workflow stages, synthetic network generation, powerflow checks, markets, clearing, and dispatch.</p>
      </div>
    </div>
    <div class="platform-arrow">
      <span>publishes evidence</span>
    </div>
    <div class="platform-step">
      <span class="platform-step__number">04</span>
      <div>
        <span class="platform-step__eyebrow">Outputs</span>
        <strong>Reports And Verification</strong>
        <p>Canonical JSON reports, figures, manifests, project status, and sense checks.</p>
      </div>
    </div>
  </div>
  <div class="platform-interface">
    <div>
      <span class="platform-step__eyebrow">Interfaces</span>
      <strong>SDK, CLI, Dashboard</strong>
      <p>Build, run, inspect, and consume the same governed artifacts without duplicating platform logic.</p>
    </div>
    <div class="platform-interface__chips">
      <span>reads model</span>
      <span>runs workflows</span>
      <span>serves outputs</span>
    </div>
  </div>
</div>

## First Commands

```bash
uv sync --extra dev
uv run gridalyn --help
uv run gridalyn project validate projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
```

For the research study — the full arc, calibrated inputs, pinned headlines:

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project verify projects/ev_hosting_flex
```

That study also exercises the locational clearing API — provider registry,
constraint events and contract selection. It is
long-running (tens of minutes) and is verified by an operator rather than in
CI.

## Documentation Map

| Section | Purpose |
| --- | --- |
| [Start](getting-started/quickstart.md) | Installation, quickstart, first-hour path, demo execution, dashboard, and reproducibility. |
| [Platform](platform/overview.md) | Architecture, digital twin core, concepts, applications, and roadmap. |
| [Platform, SDK, And Projects](platform/platform-sdk-projects.md) | Boundaries for reusable code, governed artifacts, executable demos, and applications. |
| [Core Concepts](concepts/overview.md) | Durable vocabulary for network models, artifacts, scenarios, states, and semantics. |
| [SDK](sdk/overview.md) | Public Python surfaces for models, adapters, simulation, operations, reporting, and semantics. |
| [Operations](platform/operations.md) | Flexibility providers, market clearing, dispatch, settlement, verification, and KPIs. |
| [Projects](projects/overview.md) | Executable projects that demonstrate platform capabilities at different levels of complexity. |
| [Reference](reference/overview.md) | CLI, YAML, report schemas, semantic graph, artifact policy, and validation rules. |
| [Development](development/overview.md) | Repository structure, contribution workflow, testing, release readiness, and AI-agent guidance. |

## Public Boundary

- `gridalyn/`: canonical Python SDK package and import namespace.
- `projects/`: executable demo and study projects using the same contract.
- `instances/default/digital_twin/`: default materialized twin instance.
- `dashboard/`: browser application consuming generated catalogs and reports.
- `examples/`: tutorial material, not project runtime logic.

Generated caches, large data, PDFs, and derived artifacts should stay out of Git
unless the [Artifact Policy](development/artifact-policy.md) explicitly allows
them.

# Platform Overview

Gridalyn is organized as a platform, not as a single study script. Its job is to
hold a coherent distribution-grid model, generate and validate scenarios, expose
reusable Python interfaces, and publish traceable artifacts for projects,
dashboards, reports, and future services.

## Platform Layers

| Layer | Responsibility | Main docs |
| --- | --- | --- |
| Platform governance | Naming, source-of-truth rules, model/run lineage, artifact policy. | [Architecture Map](capability-architecture.md), [Artifact Policy](../development/artifact-policy.md) |
| Layer model | Responsibility boundaries between the twin, models, simulation, operations, projects, and applications. | [Platform Layer Model](platform-layer-model.md) |
| Digital twin core | Canonical network, asset, scenario, time-series, semantic, and report artifacts. | [Digital Twin Core](digital-twin.md) |
| Python SDK | Reusable package APIs for adapters, modeling, simulation, reporting, semantics, and operations. | [Python SDK Overview](../sdk/overview.md) |
| Operations | Provider management, locational clearing, dispatch, settlement, verification, and KPIs. | [Utility Operations](operations.md) |
| Demos and projects | Reproducible workflows with declared inputs, stages, outputs, manifests, and regressions. | [Demo Projects](../projects/overview.md), [Project Model](../projects/project-model.md) |
| Applications | Dashboard, reports, semantic graph, and future service surfaces. | [Applications And Interfaces](applications-and-interfaces.md) |

## Source-Of-Truth Rule

Gridalyn follows a strict dependency direction:

```text
source data/configs -> digital twin core -> workflows/operations -> reports/applications
```

Reusable behavior belongs in `gridalyn/`. Project scripts orchestrate reusable
behavior and write declared artifacts. Dashboards and reports consume artifacts,
not hidden assumptions or notebooks.

## Architectural Stance

Gridalyn is not trying to copy one existing platform. It combines the durable
utility network-model philosophy of platforms such as Evolve, the distribution
application idea of GridAPPS-D, the clean study/simulation separation of Sienna,
and the explicit model interfaces common in modular energy frameworks. The
important Gridalyn addition is a first-class operations and flexibility layer:
providers, aggregators, clearing, dispatch, settlement, verification, and KPIs
are core platform capabilities, not project-specific afterthoughts.

The detailed responsibility map is in the
[Platform Layer Model](platform-layer-model.md).

## What Is Stable Today

- `gridalyn` CLI entrypoints;
- documented public API surfaces under `gridalyn.foundation`, `gridalyn.twin`,
  `gridalyn.assets`, `gridalyn.simulation`, `gridalyn.operations`,
  `gridalyn.projects`, and `gridalyn.interfaces`;
- project contracts under `projects/<name>/`;
- default digital-twin instance artifacts under `instances/default/digital_twin/`;
- canonical reports and project manifests;
- documentation and artifact policy checks.

## What To Treat As Non-Public

- The public platform name, package namespace, and CLI are Gridalyn.
- Demo workflows prove platform capabilities but should not define the platform
  identity.
- Generated outputs, local caches, archived notes, and one-off study scripts are
  not part of the stable user-facing API.

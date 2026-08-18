# The Platform, In One Pass

Gridalyn is seven packages under `gridalyn/`. Each one imports only from the
packages below it — `foundation → twin → assets → simulation → operations →
projects → interfaces` — and that single rule is enforced, not aspirational:
`tests/test_layer_direction.py` and the `tests/test_*_boundaries.py` suite fail
the build on an upward import.

This page is the map. The seven pages that follow it walk the stack bottom to
top, one layer per page, each ending with a link to the next — so reading them
in order is reading the platform in the same direction its own imports run.

## The stack

```text
gridalyn/interfaces/    CLI, reporting, visualization
       |
gridalyn/projects/      StudyProject + Workflow contract, runner, sense checks
       |
gridalyn/operations/    Providers, locational clearing, dispatch, settlement
       |
gridalyn/simulation/    Power-flow builders, backends, surrogates, policies
       |
gridalyn/assets/        Building, load, EV, DER, thermal modeling + datagen
       |
gridalyn/twin/          Network model, adapters, semantic graph, observation
       |
gridalyn/foundation/    Governance, report contract, capabilities, workspace
                         [standard library only]
```

`foundation` is the floor: it depends on nothing else in this repository.
Every other layer depends on the ones below it and is depended on by the ones
above it. Nothing here is symmetric — `interfaces` may import from `twin`, but
`twin` may never import from `interfaces`.

## The seven layers, one sentence each

| Layer | Answers | Read next |
| --- | --- | --- |
| [Foundation](foundation.md) | How does a run prove what it did? | governance, the report contract, capability gating, workspace paths |
| [Twin](twin.md) | What is the grid, canonically? | network model, identity, schema, observed state |
| [Assets](assets.md) | What is connected to the grid? | buildings, EVs, DER, thermal models, synthetic data |
| [Simulation](simulation.md) | Does it hold up physically? | power flow, backends, surrogates, policies |
| [Operations](operations.md) | What can the grid absorb, and at what price? | providers, clearing, dispatch, settlement |
| [Projects](projects.md) | How does a study reproduce itself? | `StudyProject`, `Workflow`, the runner, regression |
| [Interfaces](interfaces.md) | How does a person reach any of this? | CLI, reports, dashboard |

Start at [Foundation](foundation.md) and follow each page's last section to the
next; by the end you have read the platform in the order its own imports run.
Unfamiliar terms are collected in the [Glossary](../reference/glossary.md); every
public class and function this walk names is indexed by module in the
[Public API Index](../reference/public-api.md), and rendered from its live
docstrings in the [Python API Reference](../reference/python-api.md).

## Why this order, and not the org chart

A distribution-grid platform could be organized around use cases (studies,
markets, dashboards) or around this import stack. Gridalyn is organized around
the stack, deliberately: a use case can always be described in terms of the
layers it touches, but a layer described in terms of every use case that
touches it never settles into a stable contract. `operations/clearing`, for
example, is one page here regardless of how many studies call it.

Two prior efforts are visible in the platform's shape without being copied
wholesale: the durable utility network-model philosophy of platforms such as
Evolve, and the clean study/simulation separation of tools like Sienna. What
Gridalyn adds on top is treating providers, clearing, dispatch, settlement and
KPIs as a first-class platform layer (`operations`) rather than
per-study glue code — every study that needs a market reuses the same
`operations` contract instead of reimplementing it.

## What is stable, what is not

**Stable**: the `gridalyn` CLI entry points; the documented public surface of
each of the seven layers (the pages this section links to); the `project.yaml`
/ `workflow.yaml` contract under `projects/<name>/`; the default digital-twin
instance under `instances/default/digital_twin/`; the canonical report and
manifest shapes.

**Not public**: anything reached only through a private submodule path (for
example `gridalyn.simulation.simulators.powerflow.builder` rather than
`gridalyn.simulation`); generated caches and instance data; retired paths kept
only for git history.

## Where a new capability belongs

Ask which of the seven questions above it answers, and place it in that layer.
If it genuinely spans two layers, it is almost always because one of them is
being asked to do the other's job — the fix is usually to thin the higher layer
down to orchestration and push the actual behavior into the lower one, not to
invent an eighth layer.

If two projects independently need the same behavior, that behavior belongs in
`gridalyn/`, not duplicated in `projects/<name>/scripts/`. A project script's
job is to call the SDK and write declared artifacts, not to reimplement it.

# Simulation

## What problem this layer solves

`twin` and `assets` together describe a network and what is connected to it,
as data. `simulation` is where that data becomes a solvable power-flow
network and gets checked physically: does every bus hold voltage, does every
line stay under its thermal rating. It also owns the machinery for standing
in for a full solve when one is too slow — surrogates — and for deciding what
action a controller takes — policies.

## The vocabulary

- **`PandapowerGridBuilder`** — converts a feeder spec or a twin snapshot into
  a solvable pandapower network.
- **Three registries, four roles, resolved by explicit ID (never
  `entry_points`)**:

  | Registry | Role | Resolves | Recorded in provenance as |
  | --- | --- | --- | --- |
  | `PowerFlowBackendRegistry` | which solver runs | `lightsim2grid` (capability `sim`) or `pandapower_native` | `provenance.powerflow_backend` |
  | `SurrogateRegistry` | which surrogate stands in for a solve | e.g. `network_impact_physics_lookup_v1`, `network_impact_tabular_v1`, each with a stated error bound | — |
  | `PolicyRegistry` | which control policy decides an action | project-registered control policies | — |

  A **fourth** role — observation, "what does the network currently show" —
  is deliberately **not** a registry. It is a single-builder contract
  (`observe_network`) that lives in [Twin](twin.md), because current network
  state is a property of the twin, not of the solver. Three registries, four
  roles: never write "four registries."

```mermaid
flowchart LR
    subgraph REG["three registries · gridalyn/simulation"]
        direction TB
        B["PowerFlowBackendRegistry"]
        S["SurrogateRegistry"]
        P["PolicyRegistry"]
    end
    subgraph TW["not a registry · gridalyn/twin"]
        direction TB
        O["observe_network<br/>single-builder contract"]
    end

    B --> RB["which solver runs"]
    S --> RS["what stands in for a solve"]
    P --> RP["which policy decides an action"]
    O --> RO["what the network currently shows"]

    classDef reg fill:#e0f2f1,stroke:#00897b,color:#004d40
    classDef notreg fill:#fff3e0,stroke:#ef6c00,color:#e65100,stroke-width:2px
    classDef role fill:#e8eaf6,stroke:#3f51b5,color:#1a237e
    class B,S,P reg
    class O notreg
    class RB,RS,RP,RO role
```

Four roles, three registries. The registries resolve by explicit ID and never
by `entry_points`; observation sits one layer down instead, because current
network state is a property of the twin rather than of whichever solver
happened to produce it.

- **`lightsim2grid` is genuinely optional**, gated through
  `require_capabilities("sim", ...)`; `pandapower` itself is a base
  dependency and always available, so the `pandapower_native` backend never
  needs a capability check.

## The contract

A backend's identity is recorded, not implied: whichever `PowerFlowBackend` a
run actually used lands in `provenance.powerflow_backend`, so two runs on
different machines can be compared knowing which solver produced each. A
surrogate declares a stated error bound rather than being trusted blind — a
surrogate that has not measured its own error against the physics it stands in
for does not belong in `SurrogateRegistry`.

That rule is not specific to network impact, and since the contract was
generalised the machinery is not either. `measure_relief_error_bound` still
measures the two registered surrogates against finite-difference physics
labels, but it is now one caller of `measure_error_bound`, which compares any
surrogate against any physical reference in that domain's own units. Pairing
stays the caller's job: how a prediction is matched to an observation is
domain knowledge — join keys for a tabular impact frame, a shared timestamp
for a dispatch replay — and inferring it centrally would reintroduce exactly
the specialisation the generalisation removed.

The distinction worth holding is between the **contract** and the
**registry**. The contract now covers any surrogate/reference pair; the
registry still holds the two network-impact surrogates, because entering it
means implementing `fit`/`predict`/`verify` over that domain's frames. A
surrogate measured through `measure_error_bound` therefore has a real,
falsifiable bound without necessarily being resolvable by ID — those are two
different claims, and conflating them is the easy mistake here.

## Using it

```python
from gridalyn.simulation.backends import default_powerflow_backend_registry

registry = default_powerflow_backend_registry()
for descriptor in registry.list_descriptors():
    print(descriptor.backend_id, "->", descriptor.name)
```
```text
lightsim2grid -> pandapower runpp via lightsim2grid (C++/Eigen KLU)
pandapower_native -> pandapower Newton-Raphson (native runpp)
```

## Verifying it

```bash
python3 -c "
from gridalyn.simulation.surrogates import default_surrogate_registry
r = default_surrogate_registry()
print(sorted(d.surrogate_id for d in r.list_descriptors()))"
```
```text
['network_impact_physics_lookup_v1', 'network_impact_tabular_v1']
```

Both blocks above were produced by running these exact commands against this
repository.

## Where this sits

`simulation` sits on [Assets](assets.md): it needs a feeder spec or a twin
snapshot plus the DER attached to it before there is anything to solve. What
builds on `simulation` is [Operations](operations.md): the layer that decides
what to do with the headroom (or lack of it) simulation reveals — clearing a
market, dispatching a DER, settling a transaction.

# Extension Roles

A role is a contract that a component can serve: a power-flow backend, a
surrogate, a semantic capability, and so on. gridalyn ships components for
every role, and an extension adds its own the same way. This page lists every
role, what a component must be to serve it, how it is registered and selected,
and where a run records which one served. The two tables are generated from the
code by `tools/generate_registry_reference.py`, and a test fails when they are
stale.

[Write An Extension](../guides/write-an-extension.md) is the recipe for
building and installing one.

## What serves each role

The component is what the role's registry stores. For a role whose registry
builds the component on demand, an extension registers a factory, usually the
class, and the registry calls it with the settings a caller passes. The
descriptor is what the registry records about an entry. A factory carries its
descriptor as a `DESCRIPTOR` attribute, and so does an observation producer,
except a network adapter's factory: it declares an `adapter_id` (or
`source_adapter`) attribute, from which the registry builds its descriptor. A
semantic capability is its own descriptor.

<!-- BEGIN GENERATED: extension-role-contracts by tools/generate_registry_reference.py; do not edit by hand -->

| Role | Component | Descriptor | Contract versions |
| --- | --- | --- | --- |
| `channel_model` | a factory returning `gridalyn.simulation.ChannelModel` | `gridalyn.simulation.ChannelModelDescriptor` | `1` |
| `network_adapter` | a factory returning `gridalyn.twin.NetworkSourceAdapter` | `gridalyn.twin.NetworkAdapterDescriptor` | `1` |
| `observation_producer` | `gridalyn.twin.observation.registry.ObservationProducer` | `gridalyn.twin.ObservationProducerDescriptor` | `1` |
| `policy` | a factory returning `gridalyn.simulation.policies.Policy` | `gridalyn.simulation.policies.PolicyDescriptor` | `1` |
| `powerflow_backend` | a factory returning `gridalyn.simulation.PowerFlowBackend` | `gridalyn.simulation.PowerFlowBackendDescriptor` | `1` |
| `semantic_capability` | `gridalyn.twin.semantic.vocabulary.SemanticCapability` | `gridalyn.twin.semantic.vocabulary.SemanticCapability` | none; the declaration is versioned instead |
| `surrogate` | a factory returning `gridalyn.simulation.Surrogate` | `gridalyn.simulation.SurrogateDescriptor` | `1` |

<!-- END GENERATED: extension-role-contracts -->

A registration whose descriptor declares a contract version outside the
role's supported set is refused with `UnsupportedContractVersionError`, naming
the supported versions. There is no fallback.

## How each role is wired

<!-- BEGIN GENERATED: extension-role-wiring by tools/generate_registry_reference.py; do not edit by hand -->

| Role | Registry | Host registration | Selected in `project.yaml` | Recorded as |
| --- | --- | --- | --- | --- |
| `channel_model` | `gridalyn.simulation.ChannelModelRegistry` | `gridalyn.simulation.register_channel_model_extension` | `spec.simulation.channelModel.id` | `provenance.channel_model` in the run manifest, with its parameters and seed, when a study declares `spec.simulation.channelModel` |
| `network_adapter` | `gridalyn.twin.NetworkAdapterRegistry` | `gridalyn.twin.register_network_adapter_extension` | none; a stage names the ID | `adapter_id` in the base's `metadata.json` |
| `observation_producer` | `gridalyn.twin.ObservationProducerRegistry` | `gridalyn.twin.register_observation_producer_extension` | none; a stage names the ID | not by ID; each observation's `NetworkObservation.provenance` states whether its values are `simulated` or `measured` |
| `policy` | `gridalyn.simulation.PolicyRegistry` | `gridalyn.simulation.register_policy_extension` | none; a stage names the ID | not recorded in the run manifest |
| `powerflow_backend` | `gridalyn.simulation.PowerFlowBackendRegistry` | `gridalyn.simulation.register_powerflow_backend_extension` | `spec.simulation.powerflowBackend`, per stage `spec.simulation.powerflowBackendByStage` | `provenance.powerflow_backend` in the run manifest |
| `semantic_capability` | `gridalyn.twin.semantic.registry.SemanticCapabilityRegistry` | `gridalyn.twin.register_semantic_capability_extension` | none; a stage names the ID | `capabilities` in the semantic graph's manifest |
| `surrogate` | `gridalyn.simulation.SurrogateRegistry` | `gridalyn.simulation.register_surrogate_extension` | `spec.simulation.surrogate` | `provenance.surrogate` in the run manifest |

<!-- END GENERATED: extension-role-wiring -->

A study reaches every role in this table the same way: it lists the extension's
ID in `spec.inputs.extensions`. The runner routes it to the role's registry
before any stage runs, and `project_script()` routes it again in each stage
process, so a stage resolves it by ID like a shipped component. Host code
reaches a role through its host registration function instead, and that
registration lives only in the process that makes it.

## What every role shares

Every registry on this page is a `RoleRegistry`
(`gridalyn/foundation/platform/role_registry.py`), so these rules hold for all
of them:

- **Explicit IDs only.** Nothing is discovered: no plugin scan, no environment
  variable. A component is resolvable only once something registered it, and an
  installed extension that the study does not declare is never loaded.
- **One check order.** Registration checks the contract version, then the
  role's own rule, then the source, then whether the ID is taken. A failed
  check leaves the registry unchanged.
- **Attributed.** Each registration records its source: `core` for what
  gridalyn ships, `host` for host code, `entry_point` for a declared
  extension. It also records the version the extension declared.
- **One ID, one declaration.** Registering a taken ID is refused unless the
  caller passes `replace=True`. Routing a declared extension twice is a no-op,
  and an ID already held by a different source or version is refused.
- **Located errors.** An unknown ID names every registered ID. A component the
  registry cannot identify is refused with a message that names what to add:
  a `TypeError` when it carries no `DESCRIPTOR`, a `ValueError` for a network
  adapter that declares no ID. Routing a declared extension reports either as a
  `TypeError` naming the extension and its role.

## Where roles differ

The differences in public methods (`create`, `resolve`, `get`) are declared in
`tests/test_registry_parity.py`, which fails if a registry gains a public
method that the others lack and that is not declared there. The other
differences are registration rules of one registry.

| Role | Difference | Why |
| --- | --- | --- |
| `surrogate` | A descriptor without an error bound is refused (`UnboundedSurrogateError`). | A decision taken on a surrogate's estimate has to be traceable to a known accuracy. |
| `surrogate` | `create` returns a wrapper that records, once, that the surrogate answered. | Provenance records a prediction, not a construction. |
| `observation_producer` | `resolve(id)` returns the registered callable itself, with no `create`. | A producer is a function, not something to instantiate. |
| `semantic_capability` | The capability is its own descriptor, it has no contract version, and gridalyn's own capabilities record a version too. | A capability's version is part of what a graph means. |
| `semantic_capability` | `resolve(ids)` takes a set of IDs and names every unknown one at once. | A graph build declares several capabilities together. |
| `semantic_capability` | An ID must match `^[a-z][a-z0-9_-]*$`; any other is refused with a located `ValueError`. | Not stated in the code. |

## Roles an extension cannot serve

- **`interaction_protocol`** is closed by design. A declaration that claims it
  is refused with a `ValueError`. The protocol set in
  `gridalyn/operations/interaction/conversations.py` decides which message may
  follow which, and a conversation's legality must not depend on what happens
  to be installed.
- **Any other role name** is loaded into the generic extension registry and
  recorded in `provenance.extensions`, but no role registry resolves it.

## Stability

The role names, the component and descriptor types, the host registration
functions and the `project.yaml` keys on this page are public contracts. Every
role that declares a contract version currently reads the same supported set,
`SUPPORTED_CONTRACT_VERSIONS` in `gridalyn/foundation/platform/extensions.py`,
so adding a version there applies to all of those roles at once.

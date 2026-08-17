# Extension Framework

Gridalyn is an analysis and integration framework: components from outside the
`gridalyn` codebase can be registered to serve a role contract without editing
the SDK. The governing principle is *discoverable but never silent* — an
extension that participates in a run is declared, versioned and recorded in
provenance.

This page documents the foundation (Milestone 8). The generic engine lives in
`gridalyn/foundation/platform/extensions.py`; the five per-role registries
(power-flow backend, surrogate, policy, observation producer, network adapter)
are open to external registration, each through a public
`register_<role>_extension` host API.

## What an extension is

An extension is a component that conforms to a role contract and carries an
`ExtensionDescriptor`:

- `extension_id` — stable ID the extension resolves by (explicit, never
  discovered ambiently).
- `role` — the contract the extension serves (e.g. `powerflow_backend`). The
  engine treats it as data; role semantics belong to the caller.
- `name`, `version` — human-readable identity, recorded in provenance.
- `contract_version` — the role-contract version the extension conforms to.
  The engine refuses a descriptor whose version it does not support; there is
  no silent fallback.
- `source` — where the registration came from: `core` (shipped in gridalyn),
  `host` (registered at runtime by the embedding application), or
  `entry_point` (discovered from a declared entry point / namespace walk).
- `entry_point_group`, `module_hash` — discovery and content pinning when
  known.

The generic `ExtensionRegistry` stores descriptors plus factories keyed by
`extension_id` and knows nothing about roles. It exposes `register`,
`get_descriptor`, `list_descriptors` and `resolve` with located, remediating
errors.

## Registration sources

| Source | How | Provenance |
|--------|-----|-----------|
| `core` | gridalyn's own shipped defaults (unchanged behaviour) | `source: "core"` |
| `host` | `register_extension(factory, descriptor=...)` from the embedding application's entry script or notebook | `source: "host"` |
| `entry_point` | declared `gridalyn.extensions` entry-point group / namespace walk, loaded on demand (Phase 15) | `source: "entry_point"`, `version`, `module_hash` |

`register_extension` is the public host API: a third-party component conforms
to a role contract, builds an `ExtensionDescriptor`, and registers it — no edit
to the gridalyn codebase required.

## Per-role host surface

Each shipped role has a registry, a role-specific descriptor, and a public
`register_<role>_extension` convenience that mirrors `register_extension` and
routes into the role's **default registry** (a cached singleton, so a
registration made through the host API stays resolvable through the default
path). Every role descriptor carries `contract_version` and every registry
rejects an unsupported version at registration with a located
`UnsupportedContractVersionError` naming the supported versions — there is no
silent fallback, so an extension that participates is declared, versioned and
never silent.

| Role | Registry | Descriptor | Host registration API | `contract_version` |
|------|----------|------------|------------------------|--------------------|
| Power-flow backend | `PowerFlowBackendRegistry` | `PowerFlowBackendDescriptor` | `register_powerflow_backend_extension` | `"1"` |
| Surrogate | `SurrogateRegistry` | `SurrogateDescriptor` | `register_surrogate_extension` | `"1"` |
| Voltage-control policy | `PolicyRegistry` | `PolicyDescriptor` | `register_policy_extension` | `"1"` |
| Observation producer | `ObservationProducerRegistry` | `ObservationProducerDescriptor` | `register_observation_producer_extension` | `"1"` |
| Network adapter | `NetworkAdapterRegistry` | `NetworkAdapterDescriptor` | `register_network_adapter_extension` | `"1"` |

The observation-producer convenience takes the producer callable itself rather
than a factory — producers are functions with nothing to instantiate. Each
convenience accepts an optional `registry=` argument to target a specific
registry instance (defaults to the role's shared default registry); all five
conveniences are exported from the layer facades (`gridalyn.simulation` for
backend/surrogate/policy, `gridalyn.twin` for producer/adapter).

The role descriptors that embed in run manifests expose `as_dict()` with a
JSON-native shape that includes `contract_version`; the twin descriptors
(producer, adapter) are metadata-only and have no `as_dict()`.

## Discovery & Capabilities

Since Phase 15 the `entry_point` source is wired: a package ships an extension
by declaring an entry point in the `gridalyn.extensions` group, and gridalyn
sees it **without loading it**. Awareness and resolution are deliberately
separate operations:

- **Awareness — `gridalyn extension list`.** Walks the entry-point group and
  reports every installed extension (`extension_id`, version, contract
  version, source) without importing any module. `list_entry_point_metadata`
  is the stdlib primitive behind it.
- **Resolution — declared-only.** `load_entry_point_extensions(group,
  declared_ids)` imports **only** the IDs a caller names. Ambient entries are
  never loaded. An extension module exposes a callable `factory` and an
  `ExtensionDescriptor` `descriptor`; the loader stamps `source="entry_point"`,
  the `entry_point_group`, and a content `module_hash`, and registers into the
  default registry. An undeclared ID is a located error naming what is
  installed; a module that does not follow the convention is a located
  `ImportError`.
- **`gridalyn extension validate ID...`** loads the declared IDs and reports
  their provenance facts, exiting non-zero on any failure. If an extension
  declares `REQUIRED_CAPABILITIES` that its environment cannot meet, it is
  surfaced as `MissingCapabilityError` — registered but not ready is never
  silent.

A project declares which extensions its runs resolve through
`spec.inputs.extensions` in `project.yaml` — bare IDs in the default
`gridalyn.extensions` group, or `{id, group}` mappings. `load_declared_extensions`
and `resolve_declared_extensions` (in `gridalyn.projects.model_inputs`) read
and resolve that declaration on demand. A project that declares nothing loads
nothing, so its governed behavior stays unchanged (R7); the only manifest
change any run sees is the always-present empty `extensions: []` entry
(a deliberate additive-key re-base — see the run-provenance docs).

**Extensible capabilities.** The core capability set (`geo`, `sim`, `ops` —
truly-optional modules in `OPTIONAL_CAPABILITY_MODULES`) stays fixed. An
external package may declare NEW capability keys through the
`gridalyn.capabilities` entry-point group: its module exposes
`CAPABILITY_MODULES`, a dict shaped like the core map. `require_capabilities`
merges those declarations additively — an extra may only add new capabilities,
never redefine the core set, and never an empty (always-green) one. The
capability contract test validates this external format.

## Provenance

`extension_provenance()` returns a JSON-native snapshot of the extensions in
the generic engine's `DEFAULT_REGISTRY` (id, role, name, version, contract
version, source, entry-point group, module hash), sorted by `extension_id`.
The five per-role host registrations surface through role-level provenance
instead — backends today via `provenance.powerflow_backend`; the rest when the
later `provenance.extensions` phase lands. A plugin may be discoverable, but it
is never silent.

## Compatibility

`SUPPORTED_CONTRACT_VERSIONS` is the guard: a descriptor whose
`contract_version` is not supported is rejected at registration with a located
error naming the supported versions. This keeps an incompatible extension from
changing results without appearing correctly in provenance.

## Design

The full architecture and the EMFlow-inspired discovery model live in the
internal design exploration (planning documents are not shipped with the
package). The engine itself is stdlib-only so `foundation` remains the bottom
layer with no upward imports.

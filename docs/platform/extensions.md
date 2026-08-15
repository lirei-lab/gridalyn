# Extension Framework

Gridalyn is an analysis and integration framework: components from outside the
`gridalyn` codebase can be registered to serve a role contract without editing
the SDK. The governing principle is *discoverable but never silent* — an
extension that participates in a run is declared, versioned and recorded in
provenance.

This page documents the foundation (Milestone 8). The generic engine lives in
`gridalyn/foundation/platform/extensions.py`; per-role registries (power-flow
backend, surrogate, policy, observation producer, network adapter) open to
external registration in later phases.

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
| `entry_point` | declared entry-point group / namespace walk, loaded on demand (later phase) | `source: "entry_point"`, `version`, `module_hash` |

`register_extension` is the public host API: a third-party component conforms
to a role contract, builds an `ExtensionDescriptor`, and registers it — no edit
to the gridalyn codebase required.

## Provenance

`extension_provenance()` returns a JSON-native snapshot of the registered
extensions (id, role, name, version, contract version, source, entry-point
group, module hash), sorted by `extension_id`. A later phase embeds it in the
run manifest as `provenance.extensions`, and role-level provenance records
which extension served each role. A plugin may be discoverable, but it is never
silent.

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

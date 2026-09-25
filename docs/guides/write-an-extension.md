# Write An Extension

An extension is a component that lives outside the `gridalyn` codebase and
serves a role contract, such as a semantic capability or a power-flow backend.
It never participates silently: it is declared, versioned, and recorded in the
run manifest's provenance.

A component reaches a role in one of two ways, and they do not reach the same
places:

- **Declared by a study.** The study lists an installed extension in
  `spec.inputs.extensions`. Only the `semantic_capability` role is routed from
  there into a role registry.
- **Registered by host code.** A script, notebook or embedding application
  calls `register_<role>_extension(...)`. That reaches the role registry of the
  process that makes the call, and no other.

## Try it

A complete extension and a study that declares it ship at
`examples/extensions/feeder_criticality/`. The extension adds one criticality
assessment per distribution transformer to the semantic graph. From the
repository root:

```bash
uv run python examples/extensions/feeder_criticality/run_example.py
```

The script exposes the extension's entry point the way an installation does,
runs the study in a temporary directory, and prints what the run recorded.
Stage progress goes to stderr; stdout carries only the summary:

```text
{
  "extensions": [
    {
      "extension_id": "feeder_criticality",
      "role": "semantic_capability",
      "source": "entry_point",
      "version": "0.1.0"
    }
  ],
  "graph": {
    "capabilities": [
      "feeder_criticality"
    ],
    "contributed_extensions": [
      "feeder_criticality"
    ],
    "criticality_assessments": 2,
    "edge_count": 16,
    "node_count": 16
  },
  "status": "completed",
  "valid": true
}
```

With `--without-declaration` the script removes the study's
`spec.inputs.extensions` entry but leaves the extension installed. The build
then fails with `UnknownSemanticCapabilityError`, because an extension that is
not declared is never loaded. `tests/test_extension_semantic_capability.py`
pins both runs.

## What a declaration reaches

Before any stage runs, the runner resolves the study's declared extensions and
hands each to the registry of the role it declares
(`gridalyn/projects/extension_roles.py`). A declaration that cannot be honoured
fails the run up front.

| Declared role | What happens |
| --- | --- |
| `semantic_capability` | The factory's `SemanticCapability` is registered in the default semantic capability registry, so a graph build resolves it by ID exactly as it resolves a shipped capability. |
| `interaction_protocol` | Refused with a `ValueError`. The protocol set in `gridalyn/operations/interaction/conversations.py` is closed: a conversation's legality must not depend on what is installed. |
| Any other role | Loaded into the generic extension registry and recorded in `provenance.extensions`. No role registry sees it. |

The last row matters for backends. A `powerflow_backend` extension declared in
`spec.inputs.extensions` is recorded, but the study cannot select it: the
runner resolves `spec.simulation.powerflowBackend` against the power-flow
backend registry, which holds only the shipped backends and host
registrations made in the same process. Naming such an ID fails before any
stage runs:

```text
ValueError: <project>/project.yaml: spec.simulation.powerflowBackend names an unregistered backend 'acme_backend' (registered: lightsim2grid, pandapower_native)
```

### Rules for a semantic capability

- **Registered where the build happens.** Each stage runs as its own process
  and inherits nothing the runner registered, so a stage that builds a graph
  calls `script.resolve_extensions()` first. The call is a no-op for a study
  that declares nothing.
- **One ID, one declaration.** Registering the same extension twice in one
  process is a no-op. A capability ID already held by a different source or
  version is refused.
- **Checked, not trusted.** A factory that returns anything but a
  `gridalyn.twin.semantic.vocabulary.SemanticCapability` is a located
  `TypeError`. The capability's emitter is held to the same profile as a
  shipped one: its types and predicates must be declared, and the semantic
  validator checks domain, range and cardinality.
- **Node ids are `<kind>:<id>`, never a term of a bound namespace.** Types and
  predicates use the capability's prefix; the ids of the nodes it emits use a
  kind of their own. The example below binds `crit:` for its terms and emits
  nodes as `criticality:<transformer>`. An id whose kind is a bound prefix
  (`crit:<transformer>`, or `efont:...`) reads as a term of that namespace and
  would expand to an IRI inside it, so the validator refuses it with a located
  error.
- **Declared-only.** An installed extension that the study does not declare is
  never loaded, so a build that asks for its capability fails, naming the
  capabilities that are registered.

The example shows each piece:

- `examples/extensions/feeder_criticality/feeder_criticality.py` declares the
  descriptor and returns the capability from `factory`;
- `examples/extensions/feeder_criticality/study/project.yaml` declares
  `spec.inputs.extensions: [feeder_criticality]`;
- `examples/extensions/feeder_criticality/study/scripts/build_semantic_graph.py`
  calls `script.resolve_extensions()` before it builds.

## Author an extension

`gridalyn extension new` scaffolds a package that follows the loader's module
convention:

```bash
uv run gridalyn extension new grid_labels --role semantic_capability --target my-extensions
```

```text
scaffolded extension 'grid_labels' at my-extensions/grid_labels
next: install the package, then run `gridalyn extension validate grid_labels`
```

It writes three files into `<target>/<name>/` (the target defaults to the
current directory):

- `<name>.py`, the extension module. It exposes the two attributes the loader
  reads: `descriptor`, an `ExtensionDescriptor` declaring `extension_id`,
  `role`, `name`, `version` and `contract_version`; and `factory`, a callable
  returning the role's component. The scaffolded factory returns `None`, a
  placeholder to replace: left as is, a declared `semantic_capability`
  extension fails routing with the `TypeError` above. An extension that needs
  an optional capability also declares `REQUIRED_CAPABILITIES`, a tuple of
  capability names such as `("sim",)`.
- `pyproject.toml`, which wires the entry point: under
  `[project.entry-points."gridalyn.extensions"]`, the line
  `<name> = "<module>"`. The value names a module; the loader finds `factory`
  and `descriptor` inside it.
- `test_<name>.py`, a smoke test that the descriptor's `contract_version` is
  supported and the factory is callable.

`--role` defaults to `powerflow_backend`, which a declaration does not route
(see the table above). `--force` overwrites an existing directory, and a name
containing path separators is refused with a located error.

`examples/extensions/hello_world/` is a committed, unmodified scaffold with
role `data_source`. No role registry serves that role, so the extension only
appears in `provenance.extensions`.

### What a descriptor carries

| Field | Meaning |
| --- | --- |
| `extension_id` | The stable ID the extension resolves by. It is explicit; nothing is discovered ambiently. |
| `role` | The contract the extension serves. The generic engine treats it as data; routing is the caller's job. |
| `name`, `version` | Human-readable identity, recorded in provenance. |
| `contract_version` | The role-contract version the extension conforms to. An unsupported version is refused at registration; there is no fallback. |
| `source` | `core` (shipped in gridalyn), `host` (registered at runtime by host code) or `entry_point` (loaded from a declared entry point). |
| `entry_point_group`, `module_hash` | Where an entry-point extension came from and a hash of its module, stamped by the loader. |

The generic `ExtensionRegistry` (`gridalyn/foundation/platform/extensions.py`)
stores descriptors and factories by `extension_id` and knows nothing about
roles. It exposes `register`, `get_descriptor`, `list_descriptors` and
`resolve`, each with located, remediating errors. The engine is stdlib-only,
so `foundation` stays the bottom layer.

## Install and validate

After installing the package so its entry point is visible to
`importlib.metadata`, check both sides of discovery:

- `gridalyn extension list` reports every installed extension
  (`extension_id`, version, contract version, source) **without importing
  it**. `list_entry_point_metadata` is the primitive behind it.
- `gridalyn extension validate <id>...` loads exactly the named IDs and
  reports their provenance facts. It exits non-zero when an ID is not
  installed, its module does not follow the convention, or its
  `REQUIRED_CAPABILITIES` cannot be met on this install (a
  `MissingCapabilityError`: registered but not ready is never silent).

Resolution is always declared-only: `load_entry_point_extensions(group,
declared_ids)` imports only the IDs a caller names and registers them in the
generic registry with `source="entry_point"`. A study declares its IDs in
`spec.inputs.extensions`, either as bare IDs in the default
`gridalyn.extensions` group or as `{id, group}` mappings;
`load_declared_extensions` and `resolve_declared_extensions` in
`gridalyn.projects.model_inputs` read and load that list.

## Register from host code

Every role registry has a public host API that registers into the role's
shared default registry, with `source="host"`:

| Role | Registry | Host registration API | Exported from |
| --- | --- | --- | --- |
| Power-flow backend | `PowerFlowBackendRegistry` | `register_powerflow_backend_extension` | `gridalyn.simulation` |
| Surrogate | `SurrogateRegistry` | `register_surrogate_extension` | `gridalyn.simulation` |
| Voltage-control policy | `PolicyRegistry` | `register_policy_extension` | `gridalyn.simulation` |
| Channel model | `ChannelModelRegistry` | `register_channel_model_extension` | `gridalyn.simulation` |
| Observation producer | `ObservationProducerRegistry` | `register_observation_producer_extension` | `gridalyn.twin` |
| Network adapter | `NetworkAdapterRegistry` | `register_network_adapter_extension` | `gridalyn.twin` |
| Semantic capability | `SemanticCapabilityRegistry` | `register_semantic_capability_extension` | `gridalyn.twin` |

The first six take a factory and a role descriptor (the observation-producer
API takes the producer callable itself, since a producer has nothing to
instantiate). Their descriptors carry `contract_version`, and each registry
rejects an unsupported version at registration with a located
`UnsupportedContractVersionError` naming the supported versions. The semantic
capability API takes the `SemanticCapability` itself and a required `version`.
Every API accepts an optional `registry=` to target a specific registry
instance.

A host registration lives in the process that made it. A workflow stage is a
separate process, so it sees a host-registered component only if the stage
registers it itself. `examples/extensions/pilot/run_pilot.py` shows the
pattern for the runner's own process: it registers an external backend
host-side, then calls `run_workflow` in the same process, so the run manifest
names that backend.

## Provenance

- `provenance.extensions` is a JSON-native snapshot of the generic registry,
  sorted by `extension_id`: every extension registered host-side or loaded from
  an entry point in the runner's process before the manifest is written, which
  includes every extension the study declares. A study that declares nothing
  records `extensions: []`.
- `provenance.powerflow_backend` carries `extension_id`, `extension_source` and,
  when one was registered, `extension_version` whenever the resolved backend is
  not a core one; a per-stage backend override records the same keys.
  `provenance.channel_model` carries them when a study's declared channel model
  is served by an extension.
- The other roles do not record extension identity in the manifest.

## Extensible capabilities

The core optional-capability set (`geo`, `sim`, `ops` in
`OPTIONAL_CAPABILITY_MODULES`) is fixed. An external package may add new
capability keys through the `gridalyn.capabilities` entry-point group: its
module exposes `CAPABILITY_MODULES`, a dict shaped like the core map.
`require_capabilities` merges those declarations additively. An external
declaration may not redefine a core key, declare an empty capability, or name
a base dependency. `tests/test_capability_contract.py` checks the format.

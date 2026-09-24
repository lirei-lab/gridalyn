# Foundation

## What problem this layer solves

Every other layer in Gridalyn produces something — a network snapshot, a
power-flow result, a cleared market, a finished study run — and every one of
those things needs to say, in a machine-checkable way, what it is, what it
depended on, and whether it can be trusted. `foundation` is where that
capability lives. It has no domain knowledge of grids, buildings or markets;
its whole job is governance: report shape, artifact provenance, capability
availability, and workspace paths. It is the only layer that depends on
nothing else in this repository — standard library only.

## The vocabulary

- **The report contract** — `ReportMetadata` (a frozen dataclass) plus
  `build_report` / `write_report`. Every artifact-producing run in every layer
  emits one JSON report through this path.
- **Uncertainty estimates** — `UncertaintyEstimate`, `estimate_from_samples`
  and `build_uncertainty` (`gridalyn/foundation/platform/uncertainty.py`): the
  interval a headline number was drawn from, carried in a report's optional
  `uncertainty` block and checked by `validate_uncertainty`.
- **Error bounds** — `ErrorBound` and `unmeasured_error_bound`
  (`gridalyn/foundation/platform/error_bounds.py`): how far a model's answer
  sits from the reference it stands in for, either `measured` (a value, its
  sample size and the protocol) or `unmeasured` (no value, a located reason).
  It lives here so a model in any layer can carry one: the surrogates in
  [Simulation](simulation.md) do, and so does the RC building agent in
  [Assets](assets.md).
- **Governance records** — `ModelVersion` and `StudyRun` (frozen dataclasses,
  built by `build_model_version` / `build_study_run`), each carrying a content
  digest and a UTC timestamp. The project runner attaches a `StudyRun` to the
  manifest of every run, whatever its final status.
- **`ArtifactLayout` / `GridalynWorkspace`** — the single source of truth for
  where artifacts live: `instances/<instance>/digital_twin/{cache,base,
  scenarios,timeseries,models,semantic,observations,reports,dashboard,
  flexibility,operations}`, the instance contract
  `instances/<instance>/twin.yaml`, plus `configs/`, `projects/`, and
  per-project `outputs/`. The instance is named, `"default"` unless chosen.
  Code asks the layout for a path; it does not construct one by hand.
- **`ArtifactPolicy` / `check_artifact_policy`** — the rules that keep
  generated blobs and caches out of git: forbidden and allowed file patterns,
  required `.gitignore` rules, and the minimal tutorial dataset.
- **`require_capabilities` / `MissingCapabilityError`** — the preflight for
  optional dependencies. `OPTIONAL_CAPABILITY_MODULES` names exactly three:
  `lightsim2grid` (`sim`), `cvxpy` (`ops`), `osmnx` (`geo`) — the only modules
  in the platform that are genuinely absent from the base install. Everything
  else, including `pandapower` and `lightgbm`, is a base dependency and always
  importable.

## The contract

**The report contract is the one every other layer must satisfy.** Every
artifact-producing run writes its account of itself as a platform report
through `build_report` / `write_report`, and `write_report` refuses a payload
that breaks the contract before it reaches disk. Its fields, the rules of its optional
`uncertainty` block and the run manifest beside it are specified in
[Report And Run-Manifest Schema](../reference/report-schema.md).

**The capability contract** is a promise about `import`: importing any
`gridalyn` sub-package must never place a truly-optional dependency
(`lightsim2grid`, `cvxpy`, `osmnx`) into `sys.modules`. Code that needs one of
them calls `require_capabilities("sim", context="...")` first, which raises
`MissingCapabilityError` naming the missing modules and the
`pip install "gridalyn[<extra>]"` that provides them, rather than letting a
bare `ImportError` surface deep in a call stack.
`tests/test_import_hygiene.py` proves the promise by importing every
sub-package in its own subprocess. An external package may declare further
capabilities through the `gridalyn.capabilities` entry-point group; those may
only add new keys, never redefine the core three, and never name a base
dependency.

**The artifact contract** is what `check_artifact_policy` enforces, without
modifying the repository. It records an error when:

- `.gitignore` lacks one of the `required_gitignore_patterns` as an active
  rule (a commented-out line does not count);
- a tracked file matches a forbidden pattern (build caches, editor and agent
  state, generated PDFs, per-instance parquet/pickle/NumPy data, HDF5) and no
  allowed pattern — the packaged macro-model weights are the one allowance;
- an untracked file that `.gitignore` does not exclude matches a forbidden
  pattern, since `git add -A` would commit it;
- the minimal tutorial dataset (`examples/tutorials/data/minimal`) is missing,
  lacks a required file or its manifest entry, or exceeds
  `max_demo_dataset_bytes` (10 MiB by default). That size limit bounds only
  this dataset.

What is and is not tracked is listed in
[Artifact Policy](../reference/artifact-policy.md).

## Using it

How a stage writes a report, records its artifacts with `file_reference` and
qualifies a headline number with `estimate_from_samples` / `build_uncertainty`
is in [Write Governed Reports And Figures](../guides/reports-and-figures.md).

Paths come from the layout, and optional dependencies from the capability
preflight:

```python
from gridalyn.foundation.platform import ArtifactLayout, find_workspace_root
from gridalyn.foundation.platform.capabilities import (
    MissingCapabilityError,
    require_capabilities,
)

layout = ArtifactLayout(find_workspace_root(), instance="default")
print(layout.base.relative_to(layout.root))
print(layout.observations.relative_to(layout.root))
print(layout.twin_contract.relative_to(layout.root))

try:
    require_capabilities("sim", context="the lightsim2grid backend")
except MissingCapabilityError as exc:  # raised without the `sim` extra
    print(exc)
```

```text
instances/default/digital_twin/base
instances/default/digital_twin/observations
instances/default/twin.yaml
```

A script run by `gridalyn twin` does not name its instance at all:
`layout_from_environment()` (and `workspace_from_environment()`) read
`GRIDALYN_WORKSPACE_ROOT` and `GRIDALYN_INSTANCE`, which the CLI sets before
dispatching, and fall back to the current directory and the `default` instance
when they are unset.

Study stage scripts reach all of this through `project_script()`; see
[Projects](projects.md).

### The rest of the public surface

`gridalyn.foundation.platform` also exports:

| Name | What it does |
|------|--------------|
| `validate_report(payload)` | Returns a report payload's contract errors, including those of its `uncertainty` block; empty when valid. |
| `read_json_report(path)` | Reads a report back into a dict. |
| `write_manifest(path, *, reports, root=None, report_paths=None)` | Writes a `report_manifest` indexing several reports by `report_id`, with their combined validation. |
| `validate_workspace(root=".", *, projects=None, ...)` | The composed workspace check behind `gridalyn validate` (and `gridalyn doctor` inside a workspace). Foundation holds only the entry point: the projects layer registers the implementation on import through `register_workspace_validator` (`gridalyn.foundation.platform.validation`), which keeps imports flowing downward. |
| `ExtensionRegistry`, `ExtensionDescriptor`, `register_extension` | The role-agnostic extension engine: factories registered by explicit ID, each with a descriptor stating its role, version, `contract_version` and source (`core`, `host` or `entry_point`). |
| `extension_provenance()` | A JSON-native snapshot of registered extensions, as recorded in a run's provenance. |
| `list_installed_extensions()`, `list_entry_point_metadata(group)`, `load_entry_point_extensions(group, declared_ids)` | Entry-point discovery (default group `gridalyn.extensions`) without importing, and loading of the declared extensions only. |
| `SUPPORTED_CONTRACT_VERSIONS`, `UnsupportedContractVersionError` | The extension contract versions the engine accepts; any other is rejected at registration. |
| `WorkspaceRoot`, `ProjectDir` | Distinct `NewType`s over `Path` for the workspace root and a study's directory, so mypy rejects one where the other is required. `BaseArtifactDir` (`gridalyn.foundation.platform.roots`) types `ArtifactLayout.base`. |

`gridalyn.foundation.data` resolves the bundled tutorial files:
`get_dataset_path(filename)` and `list_available_datasets()`. Production
studies declare their inputs in `project.yaml` instead.

## Verifying it

Run a fixture study and read what its stages actually wrote:

```bash
uv run gridalyn project run projects/minimal_grid_project
python3 -m json.tool projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
```

The report's `governance` ids are both `null`, because a stage script does not
know them; the run's identity, including the `study_run` record built by
`build_study_run`, is in the run manifest,
`outputs/manifests/project_run_manifest.json`.
[Reading The Outputs](../start/reading-the-outputs.md) walks through both files.

## Where this sits

Nothing sits below `foundation` — it is the floor of the stack, and every
layer above it depends on it directly or transitively. What builds on it first
is [Twin](twin.md): the network model that gives the report contract, the
capability gate and the workspace layout something concrete to describe.

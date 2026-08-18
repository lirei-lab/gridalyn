# Glossary

One entry per term that appears in project YAML, report JSON, CLI output, or a
public SDK signature — the vocabulary the [Components](../components/overview.md)
walk uses without redefining each time. Each entry links to the page that owns
the concept in full.

### apiVersion / kind

The two fields every Gridalyn YAML file opens with, e.g.
`apiVersion: gridalyn.io/v1alpha1`, `kind: StudyProject` or `kind: Workflow`.
`kind` names which of the two contracts the file is. See
[Projects](../components/projects.md).

### artifact

A file a governed run produces and records provenance for — path, byte count,
SHA-256 — via `file_reference(path, root)`. See [Foundation](../components/foundation.md).

### as_of

The instant a `NetworkObservation` describes. For a `measured` observation it
is stamped from the datum itself; naive timestamps are rejected, never
silently localized. See [Twin](../components/twin.md).

### backend

Which power-flow solver a simulation run used — `lightsim2grid` or
`pandapower_native` — resolved by explicit ID through `PowerFlowBackendRegistry`
and recorded in `provenance.powerflow_backend`. See [Simulation](../components/simulation.md).

### capability

An optional dependency (`lightsim2grid`, `cvxpy`, `osmnx`) gated by
`require_capabilities(...)` rather than assumed importable. See
[Foundation](../components/foundation.md).

### clearing

Deciding which flexibility providers relieve a network constraint, at what
price — `build_locational_clearing` in `operations/clearing/selection.py`.
See [Operations](../components/operations.md).

### DER

Distributed energy resource — a battery, PV installation, or other
grid-connected device declared via `BatteryAsset`, `PVAsset`, `DERDispatchAsset`.
See [Assets](../components/assets.md).

### extension

An externally-registered component (source `core | host | entry_point`) that
participates in a per-role registry without editing `gridalyn` itself. See
`gridalyn extension list|validate|new` and [Interfaces](../components/interfaces.md).

### manifest

The governed per-run record at `outputs/manifests/project_run_manifest.json`:
git commit, per-stage status and exit code, and an overall status of
`"completed"` only if every stage exited zero. See [Projects](../components/projects.md).

### model identity

`ModelIdentity` — the CGMES `FullModel`-style header (`id`, `created`,
`profile`) stamped on a canonical network model. See [Twin](../components/twin.md).

### policy

Which control policy decides an action, resolved through `PolicyRegistry`.
See [Simulation](../components/simulation.md).

### project

A `StudyProject` — the `project.yaml` + `workflow.yaml` pair that fully
describes one reproducible study. See [Projects](../components/projects.md).

### provenance

A required field distinguishing how a value was produced — `"simulated"` vs
`"measured"` on `NetworkObservation`, or the recorded `powerflow_backend` /
`macro_model` choice on a run. See [Twin](../components/twin.md) and
[Simulation](../components/simulation.md).

### report

The governed JSON envelope every artifact-producing run emits: eight required
fields (`report_id`, `schema_version`, `created_at`, `source_domain`, `inputs`,
`artifacts`, `summary`, `validation`) under `SCHEMA_VERSION = "1.0"`, built by
`build_report` and written by `write_report`. See [Foundation](../components/foundation.md).

### scenario

A named set of network, demand, or operational assumptions a study varies
between runs. See [Assets](../components/assets.md).

### sense check

An objective-specific plausibility check run by `project_sense_check`; a
project with no registered checker and no declarative rule set fails the
`project_has_registered_sense_checks` gate. See [Projects](../components/projects.md).

### settlement

Turning cleared flexibility selections into financial records via
`build_settlement_records`, then scoring the run with
`build_operational_kpi_report`. See [Operations](../components/operations.md).

### spec

The `spec:` block of a `project.yaml`, holding `simulation`, `inputs`,
`problem`, and other project-specific declarations read through the typed
loaders in `gridalyn/projects/model_inputs.py`. See [Projects](../components/projects.md).

### StudyRun / ModelVersion

Frozen governance records, each carrying a content digest and a UTC
timestamp, built by `build_study_run` / `build_model_version`. See
[Foundation](../components/foundation.md).

### surrogate

A model that stands in for a full power-flow solve, resolved through
`SurrogateRegistry` and required to declare a stated error bound. See
[Simulation](../components/simulation.md).

### twin (network model)

The canonical, identified, schema-declared digital model of the network —
five base tables, a `ModelIdentity`, and the observed-state contract. See
[Twin](../components/twin.md) for the precise class claim; this is not a full
digital twin, and never write that it is one unqualified.

### workflow

The `workflow.yaml` (`kind: Workflow`) DAG of stages a project's run executes,
topologically sorted by `plan_stages` and run as subprocesses by
`gridalyn/projects/runner.py`. See [Projects](../components/projects.md).

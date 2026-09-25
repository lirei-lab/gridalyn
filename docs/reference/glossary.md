# Glossary

One entry per term that appears in project YAML, report JSON, CLI output, a
public SDK signature or another reference page, defined once here and in full
on the page each entry links to. Where one word names several things, the entry
separates them.

### apiVersion / kind

The two fields every Gridalyn YAML file opens with, e.g.
`apiVersion: gridalyn.io/v1alpha1`, `kind: StudyProject` or `kind: Workflow`.
`kind` names which of the two contracts the file is. See
[Project And Workflow YAML](workflow-yaml.md).

### artifact

A file a run produces and records provenance for (path, byte count, SHA-256)
via `file_reference(path, root)`. Which artifacts may be committed is the
[Artifact Policy](artifact-policy.md). See
[Report And Run-Manifest Schema](report-schema.md#file-records).

### as_of

The instant a `NetworkObservation` describes. For a `measured` observation it
is stamped from the datum itself; naive timestamps are rejected, never
silently localized. See [Twin](../components/twin.md).

### backend

Which power-flow solver a simulation run used (`lightsim2grid` or
`pandapower_native`), resolved by explicit ID through `PowerFlowBackendRegistry`
and recorded in `provenance.powerflow_backend`. See
[Simulation](../components/simulation.md).

### canonical reports

The summary reports of a twin instance, under
`instances/<instance>/digital_twin/reports/canonical/`, indexed by
`digital_twin_report_manifest.json`. Each has the platform report shape; they
summarize the instance, not one study run. See
[Report And Run-Manifest Schema](report-schema.md).

### capability

Three distinct things share the word:

- **Optional-dependency capability** — a named group of truly-optional modules
  (`geo` → `osmnx`, `sim` → `lightsim2grid`, `ops` → `cvxpy`) in
  `OPTIONAL_CAPABILITY_MODULES`. `require_capabilities("sim", context=...)`
  takes group names and raises `MissingCapabilityError` naming the extra to
  install. See [Foundation](../components/foundation.md).
- **Semantic capability** — a registered, on-demand layer of the semantic
  graph (`flexibility`, `agent_interaction`, `metering`) declared with
  `gridalyn semantic build --semantic-capabilities`. See
  [Semantic Graph](semantic-graph.md#profile-and-capabilities).
- **Twin build capability** — a layer `gridalyn twin build --capabilities`
  includes: the build-only `ev-hosting` layer or any semantic capability. The
  default is `ev-hosting,flexibility`; an empty value builds the generic model
  only. See [CLI](cli.md).

### channel model

Whether, and at what simulated time, a message between two simulated agents
arrives (`ideal`, `fixed_latency`, `bernoulli_loss` or `fixed_outage`),
resolved by explicit ID through `ChannelModelRegistry`. Stochastic models draw
from their seed and the message's identity only, so the same seed reproduces
the same deliveries. See [Simulation](../components/simulation.md).

### CI fixture study

A study small enough that CI runs it end to end on every push and checks it
against its regression baseline. The CI fixture studies are what gate the
study contract. See [The Studies](../start/studies.md#the-two-tiers).

### clearing

Deciding which flexibility providers relieve a network constraint, at what
price: `build_locational_clearing` in `operations/clearing/selection.py`.
See [Operations](../components/operations.md).

### CLS

A prefix and name fragment left from an earlier curtailment model: the retired
`cls:` namespace, and the soft and hard curtailment targets
`apply_spatial_cls` spreads over per-load matrices. The acronym is not expanded
anywhere in the code. In the semantic graph the Soft/Hard distinction is the
`contract_mode` of a curtailment contract, and every `cls:` term resolves to
its `flexint:` replacement. See
[Flexint Vocabulary](./ontology/flexint.md).

### constraint zone

A `flexint:ConstraintZone`: the part of the network a flexibility offer
relieves, resolved to one CIM `PowerTransformer`, `ACLineSegment` or
`ConnectivityNode`. Providers are located in a zone and offers target one. See
[Semantic Graph](semantic-graph.md#flexibility).

### conversation

One run of an interaction protocol between concrete agents: a `Conversation`,
which accepts a message only when its protocol has a transition for it and
otherwise raises an error naming its state and what that state would accept.
See [Operations](../components/operations.md).

### curtailment contract

A `flexint:CurtailmentContract`: the agreement under which a provider's load
may be reduced. Its `contract_mode` property is `soft` or `hard`; a soft
contract also gets an EFOnt flexibility description in the graph. See
[Semantic Graph](semantic-graph.md#flexibility).

### DER

Distributed energy resource: a battery, PV installation, or other
grid-connected device declared via `BatteryAsset`, `PVAsset`, `DERDispatchAsset`.
See [Assets](../components/assets.md).

### digital shadow

What a *deployment* of the twin becomes when its operator feeds it real
measured data through the one-way ingest path. The SDK on its own is not one:
every producer it exercises in CI is simulated or a fixture. Use the term only
with that qualification. See [twin (network model)](#twin-network-model) and
[Feed Measured Data](../guides/feed-measured-data.md).

### extension

An externally registered component (source `core`, `host` or `entry_point`)
that participates in a per-role registry without editing `gridalyn` itself.
See `gridalyn extension list|validate|new` and
[Write An Extension](../guides/write-an-extension.md).

### instance

A named twin on disk, `instances/<instance>/digital_twin/`, holding its base
tables, scenarios, semantic graph, reports and dashboard data. `default` is
used when none is named; `gridalyn twin build --instance <name>` and the
`GRIDALYN_INSTANCE` environment variable select another. Paths inside an
instance come from `ArtifactLayout`, never from string joins. See
[Twin](../components/twin.md).

### layer facade

The public import surface of one of the seven layers (`gridalyn.foundation`
through `gridalyn.interfaces`), resolving its names lazily through
`_LAZY_EXPORTS`. See [Python API](python-api.md).

### manifest

Four JSON records use the word; name the one you mean:

- **run manifest** — `outputs/manifests/project_run_manifest.json`, one per
  study run (see [run manifest](#run-manifest));
- **graph manifest** — `semantic/graph_manifest.json`, recording what a
  semantic graph was built from, including its capabilities;
- **twin build manifest** — `reports/digital_twin_build_manifest.json`, the
  steps and results of a `gridalyn twin build`;
- **report manifest** — an index of platform reports by `report_id`:
  `write_manifest` writes one, and the canonical reports keep theirs in
  `digital_twin_report_manifest.json`.

### metering point

A row of a deployment's metering-point table, `usage_point_id` plus the twin
`load_id` it meters, emitted by the `metering` semantic capability as one IEC
61968-9 `cim:UsagePoint` with exactly one `METERS` edge to that load. See
[Semantic Graph](semantic-graph.md#metering).

### model identity

`ModelIdentity`: the header stamped on a canonical network model. `id`,
`created` and `profile` carry CGMES `FullModel` semantics; `scenario_time`,
`artifact_paths` and `governance_schema_version` complete it. See
[Twin](../components/twin.md).

### observation producer

A function that produces `NetworkObservation`s, resolved by explicit ID through
`ObservationProducerRegistry`. Two ship: `powerflow` (simulated, wraps
`observe_network`) and `measured-ingest` (measured, wraps
`read_measured_observations`). See [Twin](../components/twin.md).

### operational state

Which state a network snapshot represents: `base`, `normal`, `current`,
`planned` or `study_case`. Declared, never inferred from the tables;
`NetworkModelRepository` resolves exactly one per loaded model, preferring an
explicit `operational_state=` over the manifest's, over `base`. A model a
source adapter builds in memory carries `None`: nothing has declared its
state. See [Twin](../components/twin.md).

### operator-verified study

A study too long-running, or needing data too private, for CI. An operator
runs it locally and checks it against its pinned results; its reproduce-and-pin
tests skip when its outputs are absent. See
[The Studies](../start/studies.md#the-two-tiers) and
[Operator Verification](../contributing/verification.md).

### pathBase

`spec.pathBase` in `project.yaml`: `project` (the default) or `repo`. It sets
the directory stage commands run from, and nothing else: declared paths stay
relative to the project directory. See
[Project And Workflow YAML](workflow-yaml.md#path-rules).

### platform report

The governed JSON envelope every artifact-producing stage emits, written with
`script.write_report(...)`: what the stage read and wrote, its headline
numbers and its verdict. Not to be confused with the
[run manifest](#run-manifest). See
[Report And Run-Manifest Schema](report-schema.md#platform-report) and
[Write Governed Reports And Figures](../guides/reports-and-figures.md).

### policy

Which control policy decides an action, resolved through `PolicyRegistry`.
See [Simulation](../components/simulation.md).

### project

A study's on-disk contract: the `project.yaml` (`kind: StudyProject`) and the
`workflow.yaml` it names, plus the stage scripts, inputs and baseline beside
them. The research question is the [study](#study); the project is how it is
declared. See [Projects](../components/projects.md).

### protocol

A declared state machine of messages between roles — `flex_trading` (UFTP
3.1.0) or `dr_program` (OpenADR 3.1.0) — stating which message may follow
which, with which FIPA communicative act and payload fields. See
[Standards Alignment](standards-alignment.md).

### provenance

How a value was produced. On a `NetworkObservation` it is a required field,
`"simulated"` or `"measured"`. On a run it is the run manifest's `provenance`
block: the power-flow backend, surrogate, macro model, seeds, numeric-stack
versions, hashes of the pinned inputs and, when the study declares one, the
channel model. See [Twin](../components/twin.md) and
[Projects](../components/projects.md).

### receipt

A record in `docs/development/verification-receipts.json` of an operator
protocol that was run: what, at which commit, and with what result. A `claim`
receipt goes stale when a file it watches changes; a `measurement` receipt
cannot. See [Operator Verification](../contributing/verification.md#receipts).

### regression baseline

A study's committed `baselines/results_baseline.json`: metrics, each with a
`json_path` into an output file, an expected value and a tolerance.
`gridalyn project regression` compares a run against it. Moving it is a
deliberate re-base. See
[Report And Run-Manifest Schema](report-schema.md#regression-baseline) and
[Testing And Validation](../contributing/testing-and-validation.md#the-check-ladder).

### role

What an agent does in a protocol (`distribution_operator`, `aggregator`,
`program_administrator` or `active_customer`), kept apart from the party that
plays it, so one utility can request flexibility in one conversation and
publish a demand-response event in another. See
[Operations](../components/operations.md).

### run manifest

`outputs/manifests/project_run_manifest.json`, one per study run, written by
the runner: the git commit, the `provenance` block, and each stage's status
and exit code. It is not a platform report. See
[Report And Run-Manifest Schema](report-schema.md#run-manifest).

### scenario

A named set of network, demand, or operational assumptions a study varies
between runs. See [Assets](../components/assets.md).

### sense check

An objective-specific plausibility check run by `gridalyn project sense-check`;
a project with no registered checker and no declarative rule set fails the
`project_has_registered_sense_checks` check. See
[Testing And Validation](../contributing/testing-and-validation.md#sense-checks).

### settlement

Turning cleared flexibility selections into financial records via
`build_settlement_records`, then scoring the run with
`build_operational_kpi_report`. See [Operations](../components/operations.md).

### spec

The `spec:` block of a `project.yaml`, holding `simulation`, `inputs`,
`problem`, and other declarations read through the typed loaders in
`gridalyn/projects/model_inputs.py`. See [Project And Workflow YAML](workflow-yaml.md).

### stage

One node of a workflow: an `id`, a shell `command` (with `{python}` for the
interpreter), the stage ids it `needs`, and the `inputs` and `outputs` it
declares. Stages run one at a time, each as its own subprocess, in dependency
order. See [Project And Workflow YAML](workflow-yaml.md#workflow-fields).

### study

The research unit: a question, its inputs and its pinned results, declared on
disk as a [project](#project). Studies come in two tiers,
[CI fixture](#ci-fixture-study) and [operator-verified](#operator-verified-study).
See [The Studies](../start/studies.md).

### StudyRun / ModelVersion

Frozen governance records, each carrying a content digest and a UTC
timestamp, built by `build_study_run` / `build_model_version`. See
[Foundation](../components/foundation.md).

### surrogate

A model that stands in for a full power-flow solve, resolved through
`SurrogateRegistry`. Each declares an error bound, which states whether it was
measured and, when it was not, why. See
[Simulation](../components/simulation.md).

### twin (network model)

`gridalyn.twin`: a canonical, identified, schema-declared digital model of the
network (five base tables, a `ModelIdentity` and the observed-state contract),
with a one-way, automated measured-state ingest path. It is not a digital twin;
a deployment fed real measured data is a [digital shadow](#digital-shadow).
See [Twin](../components/twin.md).

### uncertainty

The optional block of a platform report that qualifies a `summary` number with
the interval it was drawn from; validated when present, and omitted rather
than left empty. See
[Report And Run-Manifest Schema](report-schema.md#uncertainty) and
[Write Governed Reports And Figures](../guides/reports-and-figures.md#uncertainty-optional-and-strict-when-present).

### workflow

The `workflow.yaml` (`kind: Workflow`) DAG of stages a project's run executes,
topologically sorted by `plan_stages` and run by `gridalyn/projects/runner.py`.
See [Project And Workflow YAML](workflow-yaml.md).

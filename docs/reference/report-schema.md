# Report And Run-Manifest Schema

A study run leaves three kinds of JSON behind, each with its own writer and
its own format:

| Document | Written by | Where | How many |
| --- | --- | --- | --- |
| [Platform report](#platform-report) | the stage script, through `write_report` | `outputs/reports/<report_id>.json` | one per artifact-producing stage |
| [Run manifest](#run-manifest) | the workflow runner | `outputs/manifests/project_run_manifest.json` | one per run |
| [Regression report](#regression-report) | `gridalyn project regression` | `outputs/reports/regression_report.json` | one per regression check |

Paths are relative to the study directory. The twin's
[canonical reports](#canonical-reports-of-the-twin) are platform reports
written by the twin build rather than by a study. This page is the contract;
[Write Governed Reports And Figures](../guides/reports-and-figures.md) is the
recipe for writing one from a stage.

## Platform Report

A platform report is the stage's own account of its run: what it read, what it
wrote, its headline numbers and its verdict. The contract is version `1.0`
(`SCHEMA_VERSION` in `gridalyn/foundation/platform/reports.py`).

### Fields

**Required** fields are the ones `validate_report` insists on
(`REQUIRED_REPORT_FIELDS`). **Always emitted** fields are written by
`build_report` on every report but are not checked. The one **optional** field
appears only when the stage supplies it.

| Field | Status | Type | Set from |
| --- | --- | --- | --- |
| `report_id` | required | string | `ReportMetadata.report_id`; in a stage, the first argument of `script.write_report` |
| `schema_version` | required | string, must equal `"1.0"` | `ReportMetadata.schema_version`, defaulting to `SCHEMA_VERSION` |
| `created_at` | required | ISO 8601 UTC timestamp | the clock, when the report is built |
| `source_domain` | required | string | `ReportMetadata.source_domain`; in a stage, the study name |
| `inputs` | required | list of [file records](#file-records) | the `inputs=` argument, default `[]` |
| `artifacts` | required | list of [file records](#file-records) | the `artifacts=` argument, default `[]` |
| `summary` | required | object | the `summary=` argument, default `{}` |
| `validation` | required | object | the `validation=` argument, default `{"valid": true, "errors": [], "warnings": []}` |
| `project` | always emitted | object | `ReportMetadata.project`, default `{}`; in a stage, `{"name": <study>}` |
| `governance` | always emitted | object: `model_version_id`, `study_run_id`, each a string or `null` | `ReportMetadata`; both `null` when written by `script.write_report` |
| `uncertainty` | optional | object keyed by `summary` metric | the `uncertainty=` argument; see [Uncertainty](#uncertainty) |

`validate_report` returns one message per violation, and `write_report` raises
`ValueError` with all of them before anything reaches disk. It checks that:

- every required field is present;
- `report_id` is a string;
- `schema_version` equals `"1.0"`;
- `inputs` and `artifacts` are lists;
- `summary` and `validation` are objects;
- `uncertainty`, when present, passes every [uncertainty rule](#rules).

It does not type-check `created_at` or `source_domain`, look inside
`validation`, or reject extra top-level fields. `summary` is free-form: its
keys are the stage's own, and a [regression baseline](#regression-baseline)
pins them by path. `validation` follows the `valid` / `errors` / `warnings`
convention of the default. `gridalyn project status` re-validates every report
a project lists under `spec.validation.requiredReports`.

Keep a report small. Time series, power-flow traces and sample arrays belong
in Parquet or JSON files under `outputs/data/`, listed in `artifacts`.

### File Records

`file_reference(path, root)` builds the entries of `inputs` and `artifacts`:

- `path`: relative to `root` when the file lies inside it, otherwise as
  given;
- `bytes` and `sha256`: when the file exists;
- `exists: false` in place of both when it does not, so a missing input is
  recorded rather than raising.

`script.file_reference(path)` and `script.write_json(relative, payload)` return
the same record with the study directory as root. The contract does not
constrain the keys of list entries; the canonical reports add a `name` to each
artifact.

### Uncertainty

`uncertainty` qualifies headline numbers in `summary` with the interval they
were drawn from. It is keyed by the `summary` metric it qualifies; each entry
has these fields:

| Key | Type | Meaning |
| --- | --- | --- |
| `method` | string | how the interval was obtained: `monte_carlo`, `bootstrap`, `empirical_quantile` or `analytic` |
| `n` | integer | the number of draws, realizations or samples behind the interval |
| `point` | number | the headline value, as `summary` carries it |
| `interval` | `[low, high]` | the interval bounds |
| `level` | number | the coverage, such as `0.9` for a 90% interval |
| `seed` | integer, optional | the seed the draws came from, when the study fixes one |
| `note` | string, optional | free text, such as which axis the draws vary |

#### Rules

`validate_uncertainty` (in `gridalyn/foundation/platform/uncertainty.py`)
rejects a block unless:

- it is an object, and not empty: a stage with nothing to report omits the
  field;
- each entry is an object;
- `method` is one of the four methods above (`METHODS`);
- `n` is an integer, not a boolean, of at least 2 (`MIN_DRAWS`);
- `level` is a number strictly between 0 and 1;
- `interval` is a two-element list of finite numbers with `low <= high`;
- `point` is a number with `low <= point <= high`;
- the metric is a key of `summary`, and `point` equals the value under that
  key (to a relative and absolute tolerance of `1e-9`).

`seed` and `note` are not validated. A payload that breaks several rules gets
one message each:

```python
from gridalyn.foundation import validate_report

payload = {
    "report_id": "peak_report",
    "schema_version": "1.0",
    "created_at": "2026-01-01T00:00:00+00:00",
    "source_domain": "my_case",
    "inputs": [],
    "artifacts": [],
    "summary": {"peak_kw": 41.0},
    "validation": {"valid": True, "errors": [], "warnings": []},
    "uncertainty": {
        "peak_kw": {"method": "guess", "n": 1, "point": 42.0,
                    "interval": [36.9, 46.3], "level": 90},
    },
}
for error in validate_report(payload):
    print(error)
```

```text
uncertainty.peak_kw.method is 'guess' (known: monte_carlo, bootstrap, empirical_quantile, analytic)
uncertainty.peak_kw.n must be an integer >= 2, got 1
uncertainty.peak_kw.level must be within (0, 1), got 90
uncertainty.peak_kw.point 42.0 disagrees with summary.peak_kw 41.0 -- the interval must qualify the number the report actually carries
```

Build the block rather than writing it by hand: `estimate_from_samples` turns a
study's draws into an `UncertaintyEstimate`, and `build_uncertainty` assembles
estimates into the block, refusing an empty list or a repeated metric. Import
them, and `validate_uncertainty`, from the `gridalyn.foundation` facade. The
[guide](../guides/reports-and-figures.md#uncertainty-optional-and-strict-when-present)
shows them in a stage.

### Writing One

In a stage script, `script.write_report` fills the metadata from the study and
writes to `outputs/reports/<report_id>.json` unless `path=` is given. It takes
the same `inputs`, `artifacts`, `summary`, `validation` and `uncertainty`
arguments:

```python
from gridalyn.projects.scripting import project_script

script = project_script()
script.write_report(
    "powerflow_report",
    artifacts=[script.file_reference(script.figures_dir / "voltage_profile.png")],
    summary={"min_voltage_pu": 0.95},
)
```

Code outside a study calls the foundation function with its own
`ReportMetadata` and destination:

```python
from gridalyn.foundation import ReportMetadata, file_reference, write_report

write_report(
    "reports/feeder_summary_report.json",
    metadata=ReportMetadata(report_id="feeder_summary_report", source_domain="my_tool"),
    inputs=[file_reference("network.geojson")],
    summary={"feeder_count": 0},
)
```

Run in a directory holding `network.geojson`, it writes:

```json
{
  "artifacts": [],
  "created_at": "2026-09-23T15:11:39.787700+00:00",
  "governance": {
    "model_version_id": null,
    "study_run_id": null
  },
  "inputs": [
    {
      "bytes": 46,
      "path": "network.geojson",
      "sha256": "40731612d393519f9ce8894e0a22139bce972cb36b00166016106230d200d110"
    }
  ],
  "project": {},
  "report_id": "feeder_summary_report",
  "schema_version": "1.0",
  "source_domain": "my_tool",
  "summary": {
    "feeder_count": 0
  },
  "validation": {
    "errors": [],
    "valid": true,
    "warnings": []
  }
}
```

Reports are written with sorted keys and a two-space indent. `build_report`
returns the payload without writing it, and `read_json_report` reads one back.
`write_manifest(path, reports=..., report_paths=..., root=...)` writes an index
of several reports: `manifest_id`, `schema_version`, `created_at`,
`report_count`, `reports` (report id to path), `report_ids`, and a
`validation` object whose `errors` map each invalid report id to its messages.

Never assemble a report dictionary and dump it yourself:
`tests/test_report_contract.py` fails on a hand-written `*_report.json` that
describes its run's own inputs and artifacts.

### Canonical Reports Of The Twin

The canonical reports under
`instances/<name>/digital_twin/reports/canonical/` are platform reports with
`source_domain: "digital_twin"`. Their `project` carries `name`, `title` and
`stage`, and each artifact entry carries a `name`. Beside them,
`digital_twin_report_manifest.json` maps each report id to its path; it is an
index with `report_id`, `schema_version`, `created_at`, `source_domain` and
`reports`, not a platform report. When a report was not built, the index also
carries `skipped`, mapping its id to the inputs that were absent.

They are written by the `generate_canonical_reports` step of
`gridalyn twin build`, from the artifacts the earlier steps of the same build
produced; see [Build A Twin](../guides/build-a-twin.md). A report is written
only from complete inputs, the JSON summaries it reads and the Parquet
artifacts it records a digest for:

- every input present: the report is written;
- every input absent and no report at its destination: the layer that produces
  it was not built for this instance, as in a build without `ev-hosting`, so
  it is skipped and listed under `skipped` in the index;
- anything else: the step refuses before writing any report, naming each
  missing file and the command that produces it.

A fresh checkout tracks the JSON inputs but not the Parquet artifacts, so
running the step's module there,
`python -m gridalyn.interfaces.reporting.digital_twin`, is refused rather than
rewriting the tracked reports with the digests missing.

!!! warning "Regenerating them rewrites tracked files"
    The canonical reports of the `default` instance are tracked. A twin build
    run from the repository root, or the module above run after one, rewrites
    them, timestamps included. Build under a scratch `--root`, or restore them
    with `git checkout -- instances/default/digital_twin/reports/canonical/`.

## Run Manifest

`gridalyn project run` writes the run manifest to
`outputs/manifests/project_run_manifest.json`. It is on disk before the first
stage starts and rewritten after every stage, so a run killed mid-way still
leaves the status of every stage it finished. Only the runner writes it.

### Top-Level Keys

| Key | Type | Content |
| --- | --- | --- |
| `project` | object | `name`, `version` and `path` of `project.yaml` |
| `workflow` | object | `name` and `path` of `workflow.yaml` |
| `dry_run` | boolean | whether the run was `--dry-run` |
| `git_commit` | string or `null` | `HEAD` of the checkout; `null` outside a git repository |
| `started_at`, `ended_at` | ISO 8601 UTC timestamp | `ended_at` is `null` while the run is going |
| `status` | string | `running`, then `completed`, `failed`, or `planned` for a dry run |
| `stages` | list | one record per stage, in execution order (below) |
| `provenance` | object | what the run ran with ([Provenance](#provenance)) |
| `artifacts` | object | project-relative path to [file record](#file-records) for every file under `outputs/{json,reports,data,cache,figures,operations,flexibility}` at close; absent on a dry run |
| `study_run` | object | the governance record of the run ([below](#study-run-record)) |
| `stage_filter` | list of stage ids | only on a `--stage` run: the selected stages and their dependencies |
| `primary_manifest` | string | only on a `--stage` run that preserved a full run's record: that record's path |
| `partial_runs_since` | list | only on a full run's record: one entry per later `--stage` run, with its `manifest`, `started_at`, `git_commit` and `stages` |
| `provenance_error`, `artifacts_error`, `study_run_error` | string | only when that block could not be built: the exception, so the manifest is still written |

Each record in `stages` has `id`, `command` (verbatim from `workflow.yaml`,
before `{python}` is resolved), `status` (`planned`, `running`, `completed` or
`failed`), `started_at`, `ended_at` and `exit_code`. A stage that exits 0
without producing a declared output is `failed` with
`error: "declared output missing"`.

A `--stage` run that follows a completed full run does not overwrite it: it
writes `project_run_manifest.partial.json` beside it and appends itself to the
full record's `partial_runs_since`.

### Provenance

| Key | Content |
| --- | --- |
| `python_version` | the interpreter version |
| `pythonhashseed` | the `PYTHONHASHSEED` environment variable, or `null` |
| `seeds` | `base` (the declared `spec.simulation.seed`), `streams` (the declared `spec.simulation.seeds`), `declared`, and `stage_count`; the runner records what the study declares and derives nothing |
| `macro_model` | `expected` (`lgbm` or `analytical`), `lightgbm_runtime`, and `packaged_weights` (whether each weight file exists): which macro model the load generator uses |
| `powerflow_backend` | the resolved backend's descriptor (`backend_id`, `name`, `capability`, `settings`, `contract_version`), `by_stage` overrides, `declared_source`, `registered` ids and per-backend `available` flags |
| `surrogate` | `status` (`none reached` until a stage really uses a surrogate, then `reached`), `reached_by` (one entry per stage and code path that used one), `surrogate_id` with its stated `error_bound` and `contract_version` (filled only when exactly one surrogate answered, otherwise `null`), `declared_source`, and `registered` ids |
| `clearing_engine` | `name` (the declared `spec.simulation.clearingEngine`, or `null`), `declared`, and `version` of numpy, scipy and pandapower |
| `topology_stack` | the scikit-learn version, which decides the synthetic network's topology |
| `input_hashes` | file records of the pinned inputs that exist: `tmy_csv` (`inputs/tmy_trois_rivieres.csv`) and `regression_baseline` (`baselines/results_baseline.json`) |
| `extensions` | one record per registered extension (`extension_id`, `role`, `name`, `version`, `contract_version`, `source`, `entry_point_group`, `module_hash`); `[]` when none is registered |
| `channel_model` | only when the study declares `spec.simulation.channelModel`: its descriptor, `parameters` with the seed resolved, `seed_stream`, `declared_source` and `registered` ids |

`declared_source` says whether a value was declared in `project.yaml` or taken
from the registry default. A backend, surrogate or channel model served by an
extension also records `extension_id`, `extension_source` and, when known,
`extension_version`.

### Study-Run Record

`study_run` carries `run_id`, `schema_version`, `project_id`,
`project_version`, `workflow_id`, `dry_run`, `status`, `started_at`,
`ended_at`, `git_commit`, `stage_count`, the `completed_stage_count`,
`planned_stage_count` and `failed_stage_count`, and a `lineage` object with the
absolute `project_path`, `project_root` and `workflow_path`.

## Regression Baseline

`baselines/results_baseline.json` pins the numbers a study must keep. Its
shape, with two of `minimal_grid_project`'s metrics and every optional key
filled in:

```json
{
  "metric_tolerance": {
    "absolute": 1e-06,
    "note": "Why the tolerances are what they are."
  },
  "metrics": [
    {
      "expected": true,
      "id": "summary.powerflow_converged",
      "json_path": ["summary", "powerflow_converged"],
      "source": "outputs/reports/minimal_grid_report.json",
      "tolerance": 0
    },
    {
      "expected": 1.0097973462536918,
      "id": "summary.min_voltage_pu",
      "json_path": ["summary", "min_voltage_pu"],
      "source": "outputs/reports/minimal_grid_report.json",
      "tolerance": 0.001
    }
  ],
  "project": "minimal_grid_project"
}
```

| Key | Content |
| --- | --- |
| `metrics` | the pinned values; each has an `id`, a `source` file relative to the study directory, a `json_path` of keys and list indices into it, the `expected` value and an optional `tolerance` |
| `metric_tolerance.absolute` | the tolerance for a metric that declares none; `1e-6` when absent |
| `project` | optional; names the regression report's `report_id` (`<project>_regression`), defaulting to the study directory's name |

Other keys, such as `metric_tolerance.note`, are free text for the reader.

A metric compares by the type of `expected`: a boolean must be the identical
boolean, a number must lie within `tolerance` of the actual number, and
anything else must be equal. A missing `source` file or a `json_path` that does
not resolve fails the metric rather than skipping it, and a baseline with no
`metrics` fails as a whole.

## Regression Report

`gridalyn project regression <project>` compares the outputs against the
baseline and writes `outputs/reports/regression_report.json`. It is a
comparison record, not a platform report: it has no `inputs`, `artifacts` or
`validation` object. Abridged, from `minimal_grid_project` right after a full
run:

```json
{
  "artifact_drift": {
    "changed": [],
    "checked_against": "outputs/manifests/project_run_manifest.json",
    "full_run_git_commit": "89ea72c96487f200ecb64771f1dd84d880d36ba2",
    "missing": [],
    "partial_runs_since_full": 0,
    "recorded": 5,
    "run_git_commit": "89ea72c96487f200ecb64771f1dd84d880d36ba2",
    "run_started_at": "2026-09-23T15:09:43.860811+00:00"
  },
  "baseline": "baselines/results_baseline.json",
  "checked_count": 3,
  "checks": [
    {
      "actual": 1.0097973462536918,
      "expected": 1.0097973462536918,
      "id": "summary.min_voltage_pu",
      "json_path": [
        "summary",
        "min_voltage_pu"
      ],
      "source": "outputs/reports/minimal_grid_report.json",
      "tolerance": 0.001,
      "valid": true
    }
  ],
  "created_at": "2026-09-23T15:09:57.193091+00:00",
  "errors": [],
  "project": "minimal_grid_project",
  "report_id": "minimal_grid_project_regression",
  "schema_version": "1.0",
  "valid": true,
  "valid_count": 3,
  "warnings": []
}
```

| Key | Content |
| --- | --- |
| `report_id`, `schema_version`, `created_at`, `project` | identity, as for a platform report |
| `baseline` | the baseline path, relative to the study directory |
| `checked_count`, `valid_count` | how many metrics were checked and how many held |
| `checks` | one record per metric: its baseline fields plus `valid`; `actual` and the applied `tolerance` when the source resolved; `error` when the metric did not hold |
| `valid`, `errors` | whether every metric held, and why not |
| `warnings` | whether the outputs checked come from one run; they never decide `valid` |
| `artifact_drift` | `null` without a run manifest; otherwise `checked_against` (the latest run record), its `run_git_commit` and `run_started_at`, the `full_run_git_commit`, `partial_runs_since_full` (how many `--stage` runs followed the full run), and how many artifacts were `recorded` and which have `changed` or gone `missing` since |

`artifact_drift` compares the files on disk with the fingerprints in the
latest run manifest's `artifacts`, skipping this report and
`project_sense_check_report.json`, which post-run commands rewrite by design.
The other checks of a study, and when to run each, are in
[Testing And Validation](../contributing/testing-and-validation.md).

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
- **Governance records** — `ModelVersion` and `StudyRun` (frozen dataclasses,
  built by `build_model_version` / `build_study_run`), each carrying a content
  digest and a UTC timestamp. The runner attaches a `StudyRun` to the manifest
  of every completed project run.
- **`ArtifactLayout` / `GridalynWorkspace`** — the single source of truth for
  where artifacts live (`instances/default/digital_twin/{cache,base,scenarios,
  timeseries,models,semantic,reports,dashboard,flexibility,operations}`, plus
  `configs/`, `projects/`, and per-project `outputs/`). Code asks the layout
  for a path; it does not construct one by hand.
- **`ArtifactPolicy` / `check_artifact_policy`** — the rules that keep
  generated blobs and caches out of git, expressed as forbidden/allowed
  tracked-file patterns and required `.gitignore` entries.
- **`require_capabilities` / `MissingCapabilityError`** — the preflight for
  optional dependencies. `OPTIONAL_CAPABILITY_MODULES` names exactly three:
  `lightsim2grid` (`sim`), `cvxpy` (`ops`), `osmnx` (`geo`) — the only modules
  in the platform that are genuinely absent from the base install. Everything
  else, including `pandapower` and `lightgbm`, is a base dependency and always
  importable.

## The contract

**The report contract is the one every other layer must satisfy.** A report is
a JSON object with exactly eight required top-level fields —
`report_id`, `schema_version`, `created_at`, `source_domain`, `inputs`,
`artifacts`, `summary`, `validation` — under `SCHEMA_VERSION = "1.0"`. Nothing
downstream hand-assembles this shape: `build_report(*, metadata, inputs=None,
artifacts=None, summary=None, validation=None)` is the only constructor, and
`write_report` is the only way one reaches disk. `file_reference(path, root)`
is the sanctioned way to record an artifact's provenance — path plus a SHA-256
digest — inside that report, rather than a hand-rolled hash loop.

**The capability contract** is a promise about `import`: importing any
`gridalyn` sub-package must never place a truly-optional dependency
(`lightsim2grid`, `cvxpy`, `osmnx`) into `sys.modules`. Code that needs one of
them calls `require_capabilities("sim", context="...")` first, which raises the
located `MissingCapabilityError` rather than letting a bare `ImportError`
surface deep in a call stack. `tests/test_import_hygiene.py` proves the promise
by importing every sub-package in its own subprocess.

**The artifact contract** is what `check_artifact_policy` enforces: no
generated dataset over `ArtifactPolicy.max_demo_dataset_bytes` gets tracked in
git, every forbidden pattern (build caches, editor state, generated PDFs,
per-instance parquet/pickle/HDF5 data) is actually gitignored, and the minimal
tutorial dataset stays present and small.

## Using it

A stage script obtains everything it needs through `project_script()`, never
by re-deriving workspace paths or hand-assembling report JSON:

```python
from gridalyn.projects.scripting import project_script

script = project_script(root="projects/minimal_grid_project")
figure = script.figures_dir / "voltage_profile.png"
# ... produce the figure ...
script.write_report(
    "powerflow_report",
    summary={"min_voltage_pu": 0.95},
)
```

(`project_script()` with no `root` argument discovers the project by walking
up from the current working directory; a stage script run by the workflow
runner is always invoked from inside a project's own directory, so it never
passes `root` explicitly. This example names it so the snippet runs from
anywhere.)

`script.write_report` fills a `ReportMetadata` from the project (`report_id`,
`source_domain=script.name`, `project={"name": script.name}`) and routes
through `build_report` / `write_report`, so every field the contract requires
is present without the script naming a single one of them by hand.

## Verifying it

Run a governed stage and read what it actually wrote — this is not a
hypothetical shape, it is the exact file a real run produces:

```bash
uv run gridalyn project run projects/minimal_grid_project
python3 -m json.tool projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
```

The output has all eight required fields, plus `governance` (the attached
`ModelVersion`/`StudyRun` records) and `project` (name/version identity). The
same run also writes `outputs/manifests/project_run_manifest.json`, which
records `git_commit`, one entry per stage with `status`/`started_at`/
`ended_at`/`exit_code`, and closes with `status: "completed"` only if every
stage exited zero.

## Where this sits

Nothing sits below `foundation` — it is the floor of the stack, and every
layer above it depends on it directly or transitively. What builds on it first
is [Twin](twin.md): the network model that gives the report contract, the
capability gate and the workspace layout something concrete to describe.

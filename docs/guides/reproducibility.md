# Reproduce A Published Result

A study's published result is its committed baseline,
`projects/<study>/baselines/results_baseline.json`. You have reproduced it when
a run in the declared environment is followed by a regression comparison that
reports `"valid": true`. This page is that recipe: pin the environment, check
its capabilities, run, compare, and read the provenance the run recorded.

Every command runs from the repository root. For the full operator protocol,
which also regenerates the operator-verified studies' outputs and runs the test
suite against them, see [Operator Verification](../contributing/verification.md).

## 1. Install The Declared Environment

Two pins define the environment a baseline was produced in:

- **The interpreter.** The repository commits `.python-version` (`3.12`), which
  `uv` reads to select CPython 3.12.
- **The lock.** `uv sync --frozen` installs exactly what `uv.lock` records and
  never re-resolves; a stale lock is an error, not a silent upgrade. The sync is
  exact, so packages the lock does not list are removed from `.venv`.

Install with the `sim` and `ops` extras, which carry the optional capabilities
(`lightsim2grid`, `cvxpy`) that studies declare; `dev` adds `pytest`:

```bash
uv sync --frozen --extra sim --extra ops --extra dev
uv run python --version
uv run gridalyn doctor
```

`python --version` must print `Python 3.12.x`. In the `doctor` summary, every
capability your study needs must read `ok` (`gridalyn doctor --json` gives the
same facts as JSON, under `optional_capabilities`):

```text
Optional extras (not needed for the Start path):
  ok       geo  osmnx
  ok       ops  cvxpy
  ok       sim  lightsim2grid
```

A missing capability does not degrade a run quietly: a stage whose declared
backend needs an absent extra stops with a `MissingCapabilityError` naming it.

## 2. Run, Then Compare

Every study with a baseline takes the same two commands. The CI fixture studies
reproduce in seconds, so start with one to confirm the environment:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project regression projects/minimal_grid_project
```

The regression prints its report as JSON and writes it to
`outputs/reports/regression_report.json`. Its closing lines:

```text
  "valid": true,
  "valid_count": 3,
  "warnings": []
}
```

`valid_count` must equal `checked_count`, with an empty `errors` list. A metric
whose source file is missing counts as invalid, not skipped.

The operator-verified studies take the same commands, with one prerequisite:
their outputs are gitignored, so on a fresh checkout the regression has nothing
to compare and exits 1 until the run has completed. `ev_hosting_flex` runs for
hours cold:

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project regression projects/ev_hosting_flex
```

Stage commands declare `{python}`, which the runner replaces with its own
`sys.executable` (`gridalyn/projects/runner.py`), so every stage runs under the
interpreter that started the workflow and none re-resolves the environment
mid-run.

The studies and their tiers are listed in
[The Studies](../start/studies.md).

## 3. Read The Provenance

The run manifest, `outputs/manifests/project_run_manifest.json`, records the
`git_commit` the run started from and, under `provenance`, the environment the
numbers came from:

| Key | What it records |
| --- | --- |
| `python_version` | the interpreter that ran the workflow |
| `pythonhashseed` | `PYTHONHASHSEED`, or `null` when unset |
| `seeds` | the declared base seed and its resolution per stage |
| `macro_model` | whether the LightGBM runtime and packaged weights were available to the load generator |
| `powerflow_backend`, `surrogate` | the resolved solver and surrogate, and where each was declared |
| `clearing_engine` | the clearing engine, or `null` when the study clears nothing |
| `topology_stack` | versions of the packages the twin topology depends on |
| `input_hashes` | `sha256` and size of each pinned input, including the baseline |
| `extensions` | the extensions registered for the run |

When a result does not reproduce, compare these fields first.

## When It Does Not Reproduce

A difference on an unchanged tree is a pinning defect: tighten the pin that let
the environment differ (`.python-version`, `uv.lock`, a missing extra) until the
baseline matches. Do not edit `results_baseline.json` or widen a tolerance to
absorb it. A deliberate re-base is a separate, recorded decision; see
[Operator Verification](../contributing/verification.md).

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `uv sync --frozen` fails | `uv.lock` does not match `pyproject.toml` | use the lock committed with the result; do not re-lock to reproduce |
| A stage stops with `MissingCapabilityError` | the extra it names is not installed | re-run the section 1 sync with that extra |
| Regression exits 1 with missing sources | the study has not been run in this checkout | run the study first |
| Regression fails on values | numerical behavior changed | inspect `outputs/reports/regression_report.json`, then compare `provenance` with the environment the baseline was produced in |
| Regression passes with an `unrecorded drift` warning | outputs were rewritten outside the runner, typically by a stage module run directly with `python -m`, so the manifest no longer describes them | re-run through the runner (`gridalyn project run <project>`, `--stage <id>` for a subset); the rewritten files are listed under `artifact_drift` in the regression report |
| Regression passes with a `recorded mixture` warning | `--stage` runs followed the last full run, so the outputs combine runs, each on record under `partial_runs_since` in the run manifest | nothing is wrong; run the full workflow when a single-run set is needed, for example before quoting a result |

## Next Reading

- [Testing And Validation](../contributing/testing-and-validation.md): the
  validate, sense-check, regression and verify checks
- [Projects](../components/projects.md): the workflow runner and the run manifest
- [Operator Verification](../contributing/verification.md)

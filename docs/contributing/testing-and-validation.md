# Testing And Validation

Two kinds of evidence say a change is sound: the `pytest` suite, which tests
the SDK, and the check ladder, which asks a study whether its contract, its
outputs and its numbers still hold. This page owns both. Which of them CI runs
on a pull request is on
[Development Workflow](developer-workflow.md#what-ci-checks-on-your-pull-request);
what CI leaves to you is on [Operator Verification](verification.md).

## The check ladder

Each rung answers a different question. Do not read one as another: a study
can validate cleanly and still have moved every number.

| Command | Answers | Needs outputs on disk | Writes |
| --- | --- | --- | --- |
| `gridalyn validate` | Does the workspace hold together? Checks the artifact policy and every project contract under `projects/`. | No | Nothing |
| `gridalyn project validate <project>` | Are `project.yaml` and `workflow.yaml` well formed, with unique stage ids and every `needs:` naming a known stage? `--check-artifacts` adds the declared reports and figures. | Only with `--check-artifacts` | Nothing |
| `gridalyn project status <project>` | Which stages ran, and when? `--check-artifacts` adds the declared artifacts. | No; it reports what is missing | Nothing |
| `gridalyn project sense-check <project>` | Are the numbers plausible for what the study is for? | Yes | `outputs/reports/project_sense_check_report.json` (skip with `--no-write`) |
| `gridalyn project regression <project>` | Did a pinned number move? Compares each metric in `baselines/results_baseline.json` with the value at its `json_path`, and reports whether the outputs changed since the recorded run. | Yes | `outputs/reports/regression_report.json` |
| `gridalyn project verify <project>` | All of the above but regression, as one JSON payload with one `valid`: contract, status, required artifacts and sense checks. | Yes | The sense-check report (skip with `--no-write`) |
| `gridalyn project verify-all` | `verify` for every project under `projects/`. | Yes, for every study | Nothing, unless `--write` |

The whole ladder on a CI fixture study, from its own run:

```bash
gridalyn project run projects/minimal_grid_project
gridalyn project validate projects/minimal_grid_project --check-artifacts
gridalyn project sense-check projects/minimal_grid_project
gridalyn project regression projects/minimal_grid_project
gridalyn project verify projects/minimal_grid_project
```

Each check prints a JSON payload with a top-level `valid`.

`gridalyn validate` also takes `--project <path>` (repeatable),
`--check-project-artifacts` and `--regression`, to run the per-project rungs
from the workspace command.

### Sense checks

Validation proves that a workflow is runnable and that its declared artifacts
exist. Sense checks go further and ask whether the numbers make sense for the
study's objective. Each study declares a `validation.senseChecker` and its
`objectiveArtifacts` in `project.yaml`; the checker adds objective checks to
the common artifact checks. For example, `minimal_grid_project` checks for five
buses, four lines, a converged power flow and a near-nominal voltage, and
`rl_voltage_control_lightsim` checks that the LightSim2Grid backend ran, the
reward improved and control reduced the voltage deviation. A study with
neither a registered checker nor declarative checks fails
`project_has_registered_sense_checks`, so no study passes vacuously. Only
checks of severity `error` make the report invalid; warnings do not.

### Reading `verify-all`

**Expect a non-zero exit on a clean checkout.** Study outputs are gitignored,
so every study whose workflow has not run fails `project_manifest_exists` and
its required-artifact checks. `verify-all` reports `"valid": true` only once
every study has produced its outputs, including the operator-verified ones.
Read the per-project entries rather than the top-level `valid`: a study you
have run that still fails is the real signal.

## The test suite

```bash
python -m pytest -q
```

Run the narrowest file that covers a change first, for example:

```bash
python -m pytest -q tests/test_project_hygiene.py
```

Four markers, declared in `pyproject.toml`, change what a run includes:

| Marker | Meaning | Deselect with |
| --- | --- | --- |
| `governed_study_run` | Runs a CI fixture study end to end in place under `projects/`. | `-m "not governed_study_run"` |
| `governed_study_outputs` | Reads the outputs a `governed_study_run` test produced, so it must run after one. | `-m "not governed_study_outputs"` |
| `mutates_repository` | Writes into the working tree while it runs and restores it. CI runs these alone, after the parallel suite, so no other worker sees the transient file. | `-m "not mutates_repository"` |
| `slow` | A multi-minute test. | `-m "not slow"`, or `GRIDALYN_SKIP_SLOW=1` to skip it visibly |

### A skip is not a pass

A skipped test is verification that did not happen, and in a summary count it
looks the same as a pass. `tests/conftest.py` prints every skipped test with
its reason at the end of a plain `pytest -q` run, without `-rs`, grouped by
reason, because one absent artifact usually skips many tests. Without the
gitignored Hydro-Québec dataset, the building-diversity tests print:

```text
================= 7 test(s) SKIPPED - verification did not run =================
[7] datasets/hq is gitignored; provide it locally to run this validation
      tests/test_building_diversity_vs_hq.py::test_diversity_curve_tracks_hq[12]
      tests/test_building_diversity_vs_hq.py::test_diversity_curve_tracks_hq[1]
      tests/test_building_diversity_vs_hq.py::test_diversity_curve_tracks_hq[2]
      tests/test_building_diversity_vs_hq.py::test_diversity_curve_tracks_hq[6]
      tests/test_building_diversity_vs_hq.py::test_hysteresis_is_energy_neutral_against_the_proportional_base
      tests/test_building_diversity_vs_hq.py::test_hysteresis_reproduces_measured_heating_cycling
      tests/test_building_diversity_vs_hq.py::test_windows_are_temperature_matched
7 skipped in 0.12s
```

Read that block before the summary line, and for each reason ask whether you
meant that verification not to run. `tests/test_skip_visibility.py` requires
every skip site to carry a reason specific enough to act on. On a clean
checkout the operator-verified studies' reproduce-and-pin tests skip this way;
[Operator Verification](verification.md) is how to make them run.

## When to run which check

| Change | Run |
| --- | --- |
| Any change, before you push | `python tools/verify_local.py`: CI's fast gate on the tests your change reaches, in the locked environment. `--all` runs the whole suite as CI does. |
| Documentation only | `mkdocs build --strict -f docs/mkdocs.yml` and `python tools/check_doc_instructions.py` |
| A study's workflow or scripts | That study's run, then `project verify` and `project regression` |
| Core Python package | The affected test files, then `pytest -q`, then the regression of every study that uses the changed code |
| A generator or simulation kernel | All of the above, plus [Operator Verification](verification.md) |
| Artifact policy or generated outputs | `gridalyn validate`, then `project status --check-artifacts` for the affected studies |
| Dashboard source | `npm ci`, `npm test` and `npm run build` in `dashboard/` |
| A module boundary | `tests/test_layer_direction.py`, `tests/test_import_hygiene.py` and `tests/test_project_hygiene.py` |

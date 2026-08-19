# Operator Verification

CI proves most of this repository on every push. It cannot prove all of it. This
page is the one place that says which part is yours, gives a single command that
covers it, and explains how to tell a real pass from a green summary that
verified nothing.

Run it after touching a generator, a simulation kernel, the workflow runner, or
anything a governed baseline depends on. For everyday work,
[Testing And Validation](testing-and-validation.md) is the shorter path.

## 1. What CI Already Covers

Three jobs in `.github/workflows/ci.yml` run on every push to `main` and every
pull request. What they cover is **not** your job to repeat.

| Job | What it proves |
| --- | --- |
| `test` | The whole `pytest` suite on Python 3.12 with the `dev` extra installed. |
| `projects` (Governed project contracts) | Six fixture studies run end to end — `minimal_grid_project`, `synthetic_geojson_feeder`, `ieee_33_bus_demo`, `der_voltage_optimization`, `prosumer_battery_market`, `rl_voltage_control_lightsim` — each followed by a regression comparison against its committed baseline. This is what actually gates the StudyProject → Workflow → report → baseline contract. |
| `typecheck` (Type check ratchet) | `tools/mypy_ratchet.py`, run twice: `--target gridalyn` against `.mypy-baseline` (133 errors — a real, tracked backlog, never silently raised) and, since 2026-08-18, `--target projects --baseline-file .mypy-baseline-projects` (868 errors across 72 files — a second, independent tracked backlog; study scripts were never held to the SDK's bar). Both report rather than block: a job fails only when its own count *rises*. The same script backs both pre-push hooks, so local and CI cannot disagree. The second target exists because a shared helper's signature changed and 9 of 10 `ev_hosting_flex` call sites kept the old type — invisible to CI, since the study's own tests `skipif` on its gitignored outputs, and invisible to mypy until `projects/` had a gate at all. |

The `lint` job runs pre-commit on pull-request-changed files only. The full tree
does not pass `flake8`, so do not read a green `lint` as a clean tree.

## 2. What CI Cannot Cover, And Why

**The two research studies are structurally invisible to CI.**

`projects/ev_hosting_flex/outputs/` and `projects/admm_thermal_consensus/outputs/`
are gitignored. Their reproduce-and-pin tests — the ones that assert the study's
governed numbers are still the numbers — are all guarded by `skipif` on the
presence of those artifacts, for example in
`tests/test_ev_hosting_flex_annual.py`:

```python
@pytest.mark.skipif(not (_DATA / "base_annual.npy").is_file(), reason=_SKIP_REASON)
```

A fresh CI checkout has no such file. **35 test functions across 17 files** are
guarded this way; every one of them is skipped in CI, and the job reports green.
**CI is not failing to verify the heavy studies; it is silently declining to.**
That is the gap this page exists to close, and it is why the studies are
described as *operator-verified only*.

CI cannot close it itself. `ev_hosting_flex` last took **5 h 59 m** of wall clock
to regenerate (23 stages; `analyze_congestion_risk` alone is 76 min), against a
`projects` job budgeted 25 minutes. The cost is real, not incidental.

Two smaller gaps belong to the operator as well:

- **The fixture studies' baselines** are compared in CI, but if you changed a
  generator or kernel you want that comparison in front of you before you push,
  not after.
- **Coverage** is measured but not enforced. There is no threshold, by design —
  see section 4.

## 3. The Command

Copy the whole block. It regenerates the caches CI never has, runs the suite with
coverage, runs the fixture studies, and checks that no baseline moved.

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Use the project venv explicitly. A bare `python` may be a 3.10 that cannot
# even import this package.
PY=.venv/bin/python

# --- 1. Regenerate the gitignored heavy-study caches that CI never has. -----
# Budget honestly: ev_hosting_flex is ~6 hours, admm_thermal_consensus ~10 min.
# Both studies' stages invoke `uv run python`, so `uv` must be on PATH.
for study in admm_thermal_consensus ev_hosting_flex; do
  "$PY" -m gridalyn.interfaces.cli.project run        "projects/${study}"
  "$PY" -m gridalyn.interfaces.cli.project regression "projects/${study}"
done

# --- 2. Full suite, with coverage. --------------------------------------
# Now that step 1 has produced the artifacts, the reproduce-and-pin tests
# RUN instead of skipping. Read the SKIPPED block at the end, not just the
# summary counts.
"$PY" -m pytest -q --durations=15 \
  --cov=gridalyn --cov-report=term-missing --cov-report=xml

# --- 3. Fixture studies end to end (mirrors the CI `projects` job). --------
for study in minimal_grid_project synthetic_geojson_feeder ieee_33_bus_demo \
             der_voltage_optimization prosumer_battery_market \
             rl_voltage_control_lightsim; do
  "$PY" -m gridalyn.interfaces.cli.project run        "projects/${study}"
  "$PY" -m gridalyn.interfaces.cli.project regression "projects/${study}"
done

# --- 4. The invariant that protects reproducibility: no baseline moved. ----
git diff --name-only -- 'projects/*/baselines'
```

Step 4 must print **nothing**. If it prints a path, a governed result changed.
That is either a defect or a deliberate re-base, and a deliberate re-base is
recorded in the study's `CALIBRATION.md` with its rationale — never left as an
unexplained diff.

If you cannot afford step 1's six hours, run `admm_thermal_consensus` only and
say so. A partial run recorded honestly is worth more than a full run claimed.

## 4. How To Read The Result

**A skip is not a pass.** It is verification that did not happen. This is the
single most important line on this page, because a skipped reproduce-and-pin
test looks identical to a passing one in a summary count.

`tests/conftest.py` prints every skipped test with its reason at the end of a
plain `pytest -q` run, without needing `-rs`. Reasons are grouped, because one
absent artifact usually skips many tests at once:

```text
================= 2 test(s) SKIPPED - verification did not run =================
[1] datasets/hq is gitignored; provide it locally
      tests/test_zz_skip_demo.py::test_demo_skips_for_a_second_reason
```

Read that block first, then the summary line. For each reason ask: *did I intend
that verification not to run?* If the answer is no, obtain the artifact and run
again. `tests/test_skip_visibility.py` enforces that every skip site in the suite
carries a reason specific enough to act on, so "I could not tell why" is not an
acceptable outcome.

Then read the rest in this order:

- **Failures** — record them before you fix them. Do not iterate to green and
  report only the green run.
- **The regression comparisons** — each prints a checked/valid count. `valid`
  must equal `checked` for every study, with an empty `errors` list.
- **Coverage** — a percentage over the `gridalyn` package. **There is no
  threshold and none should be added casually.** The number exists to be read and
  compared with the previous run, not to be defended.

Two limits on the coverage figure are worth knowing before you quote it:

- **Scope is `gridalyn/` only.** The 77 study stage scripts under the repo-root
  `projects/*/scripts/` are not measured at all. (The `gridalyn/projects/` layer
  that appears in the report is the SDK's project-contract layer, a different
  thing with a similar name.)
- **Subprocess work is not counted.** Workflow stages run as separate
  subprocesses via `subprocess.run(shell=True)`, and there is no
  `[tool.coverage]` configuration enabling subprocess tracing. Library code
  exercised only inside a stage script therefore reads as uncovered even though
  the end-to-end tests do execute it. The number understates real exercise.

## 5. Known Environmental Requirements

| Requirement | Why | Symptom if missing |
| --- | --- | --- |
| `.venv` on Python 3.12 with `pip install -e ".[dev]"` | System `python3` may be older and cannot import the package. | Import errors, or a suite that will not collect. |
| `uv` on `PATH` | 32 stages across the two heavy studies invoke `uv run python`. The `{python}` placeholder resolution in the runner does not apply to them — their leading token is `uv`. | `/bin/sh: 1: uv: not found`, stage exit 127. |
| Network access | `tests/test_packaging_contract.py` builds a real wheel with pip build isolation, which resolves `setuptools>=77.0` from an index. | Packaging test fails on `no matching distribution`. |
| `setuptools>=77.0` in the build environment | `pyproject.toml` uses the PEP 639 SPDX `license = "MIT"` form, which setuptools accepts only from 77.0. An older setuptools rejects the metadata. | `invalid pyproject.toml config: 'project.license'`. |
| `datasets/hq/consumption.h5` | The Hydro-Québec validation set is gitignored; the building-diversity tests compare against it. | Those tests skip, with a reason naming the dataset. |
| `mypy==1.9.0` | In the `typing` extra, and in `dev`. Pinned exactly rather than floored, because the baseline is a *count* and a different analyser returns a different count for an unchanged tree. | The pre-push ratchet names the fix: `pip install -e ".[typing]"`. |

### If `uv run` dirties `uv.lock`

`uv.lock` is **current**, and the routine case is that verification never touches
it. Measured 2026-08-06 on `uv 0.11.7`: `uv lock --check` resolves cleanly
(`Resolved 268 packages`), and `lightgbm` — a base dependency at
`pyproject.toml:32` — is recorded as a base dependency in the lockfile too, at
`uv.lock:1099` inside the `gridalyn` package's `dependencies` list and at
`uv.lock:1275` with no `extra ==` marker (unlike its `lightsim2grid` neighbours,
which do carry one). Six consecutive `uv run` invocations left the file
byte-identical.

An earlier revision of this page claimed the lockfile was stale — that `lightgbm`
was recorded "only under the `ops` / `all` / `dev` extras" — and that *any*
`uv run` therefore re-resolved and rewrote it. Neither reproduces; treat a
rewrite as the exception below, not the rule.

It can still happen: a different `uv` version, or a `pyproject.toml` edit that
forces re-resolution, will rewrite the lockfile and leave a tracked file
modified:

```
 M uv.lock
```

If you see that, it is a re-lock, not a product of verification. Check
`git status` and revert it path-scoped unless you intend to land the re-lock as
its own change:

```bash
git checkout -- uv.lock
```

Never `git stash` here — the working tree usually holds regenerated study outputs
you do not want moved.

An offline build is possible with `PIP_NO_INDEX=1 --no-build-isolation` **if** the
environment already carries `setuptools>=77.0`; with build isolation it cannot
be, because isolation always reaches for an index.

## 6. Staged Regeneration And Per-Stage Receipts

The flagship `ev_hosting_flex` study is verified **by protocol** rather than by
a single opaque run: a shape-covering subset (`python tools/flagship_verify.py`)
executes the pipeline's non-heavy stages end to end against the study workspace,
skips the hours-long heavy stages with a recorded reason, and reports the
baseline check. Per-stage records — name, status, duration, and a reason when a
stage is skipped — are captured so a partial regeneration is auditable, and the
verification-receipt ledger accepts an optional per-stage record list on any
receipt (each stage must carry a `name` and a `status` — `ok`, `skipped` or
`failed` — and any per-stage `commit` must exist in this history and lead to
HEAD).

Two operator commands:

- `python tools/flagship_verify.py` — the shape-covering subset, the fast
  source-proven proof used on generator/kernel changes. Its stage execution is
  quick (the recorded run executed 2 stages in ~4 s; the heavy annual-MC stage
  and its dependents are skipped with recorded reasons), so its wall time is
  dominated by environment/toolchain setup rather than stage work.
- `python tools/flagship_verify.py --include-heavy` — the full regeneration
  (roughly six hours), operator-scheduled at milestones; the resulting receipt is
  recorded at the commit it ran at.

The full six-hour regeneration remains operator-scheduled; the subset is what
keeps the study source-proven between those runs.

### Executed run (2026-08-06, recorded at 6ea8a92a)

The shape-covering subset was executed and its receipts recorded: 22 stages,
2 ran OK (`prepare_workspace` 0.4 s, `prepare_topology_cache` 3.1 s, topology
cache 4320 buses), 20 skipped (the heavy `generate_annual_mc` plus its
downstream dependents), and the baseline check returned **PASS — baselines
byte-identical**. Per-stage records are embedded on the `flagship-subset`
receipt; the `flagship-reproduce` receipt is now `recorded` (source-proven by
protocol). The full ~6 h regeneration remains operator-scheduled.

## 7. Twin Consumer Identity

`r7-twin-consumer-identity` is the second operator protocol in the receipt
ledger. It answers a question the flagship subset cannot: **did restructuring
`gridalyn/twin` change what a consumer of the twin sees?** No study reads the
twin, so no baseline can move and the usual baseline guardrail has nothing to
grip.
This protocol supplies the missing evidence directly.

Run it with `python tools/r7_twin_consumer_identity.py <before-ref> <after-ref>`
— for the 2026-08-12 record, `python tools/r7_twin_consumer_identity.py d6aa606e
6ed179c0`. It takes about 40 seconds.

**What it does.** It checks out each ref into its own git worktree, and from
each one captures `NetworkModelRepository.load_model()`,
`.validate_integrity()` and `build_dashboard_catalog()` over the **same** base
directory. It hashes each capture and classifies the difference as `identical`,
`additive` or `regressed`. Comparing two code revisions over one set of
artifacts is the point: a regenerated base would change the digest by itself,
and the comparison would measure the regeneration instead of the code.

**What the digest covers**, and only this: `load_model()`'s six counts,
`source_adapter`, `source_standard`, `provenance_status`, every `ModelIdentity`
field, and a content SHA-256 of each of the five canonical tables (columns,
dtypes, rows); `validate_integrity()`'s `valid`/`errors`/`warnings`/`summary`;
and the whole `build_dashboard_catalog()` mapping minus `created_at`. Stating
the field set is not a formality — two earlier hand-rolled comparisons
disagreed purely because they hashed different fields.

**Two controls make a green result mean something.** A *determinism* control
captures the same ref twice in two independent worktrees and requires an
identical digest. A *vacuity* control has each child report the directory it
imported `gridalyn` from, and the parent asserts that directory lies inside
that ref's worktree — so a capture that silently read the main checkout fails
loudly instead of reporting a perfect match against itself.

**Two disclosed weaknesses.** `created_at` is stripped, because
`build_dashboard_catalog` derives it from `datetime.now()` — a pre-existing
non-determinism, disclosed rather than hidden. `identity.created` is **not**
stripped: it is read from the base manifest, so it is constant for a fixed base,
and code that stopped propagating it is a real difference.

**Why CI cannot run it.** The base parquet files are git-ignored, so a runner
has no base to capture over; the protocol also needs full git history and two
working trees. Re-run it whenever anything under the receipt's `watched` list
moves — `gridalyn/twin/network`, `gridalyn/projects/dashboard_catalog.py`,
`instances/default/digital_twin/base`, or the tool itself. The receipt gate
reporting the entry `STALE` after such a change is the intended signal, not a
failure.

## Related Pages

- [Testing And Validation](testing-and-validation.md) — the per-change checklist.
- [Contribution Workflow](developer-workflow.md) — commands, generated files, commit hygiene.
- [Artifact Policy](../reference/artifact-policy.md) — what may and may not be committed.

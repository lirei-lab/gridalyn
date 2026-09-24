# Operator Verification

CI proves most of this repository on every push; the gates it runs are listed
on [Development Workflow](developer-workflow.md#what-ci-checks-on-your-pull-request).
This page covers the rest: the protocols an operator runs by hand, the command
that runs them, and how to tell a real pass from a green summary that verified
nothing.

Run it after touching a generator, a simulation kernel, the workflow runner, or
anything a study's baseline depends on. For everyday work,
[Testing And Validation](testing-and-validation.md) is the shorter path.

## What CI cannot cover

**The operator-verified studies are invisible to CI.**
`projects/ev_hosting_flex/outputs/` and
`projects/admm_thermal_consensus/outputs/` are gitignored. Their
reproduce-and-pin tests — the ones asserting that the study's pinned numbers
are still the numbers — are guarded by `skipif` on the presence of those
outputs, for example in `tests/test_ev_hosting_flex_annual.py`:

```python
@pytest.mark.skipif(not (_DATA / "base_annual.npy").is_file(), reason=_SKIP_REASON)
```

A fresh CI checkout has no such file, so every test guarded this way skips and
the job reports green. **CI is not failing to verify these studies; it is
declining to.** CI cannot close the gap itself: a cold regeneration of
`ev_hosting_flex` takes hours (the `flagship-reproduce` receipt records the
last measured run), against a `projects` job whose timeout is measured in
minutes.

Two smaller gaps are yours as well:

- **The CI fixture studies' baselines** are compared in CI, but after changing a
  generator or kernel you want that comparison before you push, not after.
- **Coverage** is measured but not enforced; there is no threshold, by design.

## The command

Copy the whole block. It builds the declared environment, regenerates the
outputs CI never has, runs the suite with coverage, runs the CI fixture
studies, and checks that no baseline moved.

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# --- 0. The declared environment, with the capabilities the studies need. ---
# `--frozen` fails on a stale uv.lock instead of re-resolving it. Without the
# `sim` and `ops` extras ev_hosting_flex falls back to other code paths, still
# exits 0, and moves its pinned numbers.
uv sync --frozen --extra sim --extra ops --extra dev
PY=.venv/bin/python
"$PY" --version                            # must print Python 3.12.x
"$PY" -m gridalyn.interfaces.cli.gridalyn doctor   # ops and sim must read ok

# --- 1. Regenerate the operator-verified studies' gitignored outputs. -------
# ev_hosting_flex takes hours cold, admm_thermal_consensus minutes. Stages run
# under this same interpreter through the `{python}` placeholder.
for study in admm_thermal_consensus ev_hosting_flex; do
  "$PY" -m gridalyn.interfaces.cli.project run        "projects/${study}"
  "$PY" -m gridalyn.interfaces.cli.project regression "projects/${study}"
done

# --- 2. Full suite, with coverage. --------------------------------------
# With step 1's outputs on disk the reproduce-and-pin tests RUN instead of
# skipping. Read the SKIPPED block at the end, not just the summary counts.
"$PY" -m pytest -q --durations=15 \
  --cov=gridalyn --cov-report=term-missing --cov-report=xml

# --- 3. CI fixture studies end to end (the list the CI `projects` job runs). -
for study in minimal_grid_project synthetic_geojson_feeder ieee_33_bus_demo \
             der_voltage_optimization prosumer_battery_market \
             rl_voltage_control_lightsim dr_agent_interaction \
             flex_trading_congestion cold_load_pickup_feeder; do
  "$PY" -m gridalyn.interfaces.cli.project run        "projects/${study}"
  "$PY" -m gridalyn.interfaces.cli.project regression "projects/${study}"
done

# --- 4. The invariant that protects reproducibility: no baseline moved. ----
git diff --name-only -- 'projects/*/baselines'
```

Step 4 must print **nothing**. A printed path means a pinned result changed:
either a defect or a deliberate re-base, recorded as the next section says.

If you cannot afford step 1's hours, run `admm_thermal_consensus` only and say
so. A partial run recorded honestly is worth more than a full run claimed.

### Two further legs for `ev_hosting_flex`

- **Determinism.** The study's tests must pass under two different hash seeds:
  `PYTHONHASHSEED=0 python -m pytest -q tests/ -k ev_hosting_flex`, then the
  same with `PYTHONHASHSEED=1`. On an operator machine that command
  regenerates the study's outputs in place, so run it only as part of this
  protocol. The seed a run used is recorded in the run manifest as
  `provenance.pythonhashseed`.
- **No network.** The study reads its weather only from the committed
  `projects/ev_hosting_flex/inputs/tmy_trois_rivieres.csv` and never fetches
  from PVGIS. Confirm that no fetch appears in the stage output and that the
  run manifest's `provenance.python_version` reads 3.12.x.

## Recording a re-base

A deliberate re-base is recorded in the study's own files, never left as an
unexplained diff.

- **Every study** records the sha256 of its `results_baseline.json` in
  `baselines/REBASE_LOG.md`, newest entry last, and
  `tests/test_baseline_rebase_declared.py` recomputes it. A re-base therefore
  costs one extra step — append an entry saying what moved and why, with the
  new digest — and that step is the point: the rule forbids silence, not
  change. The log does not verify the new numbers (that needs the outputs CI
  does not have), and nothing stops an author updating the digest without
  thinking; what it removes is a pin moving with nobody noticing.
- **`ev_hosting_flex`** also keeps a `CALIBRATION.md`, a chronological record:
  append a dated section rather than revising earlier ones; update the gated
  tables at the top, which `tools/check_calibration_claims.py` checks against
  the pins and the declared `studyConfig`; and when a change retires code an
  earlier section documents, banner that section as retired. The gate covers
  the first two. It cannot see the third: a retired section can stay
  internally consistent while describing code that no longer exists.

Know what that gate covers. `tools/check_calibration_claims.py` reads one
table, "Current headline figures", so it gates the pins that table cites and
no others. In a clean checkout a moved pin the table cites fails the gate; a
moved pin it does not cite passes, and the reproduce-and-pin tests that would
catch it skip.

## Reading the result

- **Skips first.** A skip is verification that did not happen; read the
  SKIPPED block as [Testing And Validation](testing-and-validation.md#a-skip-is-not-a-pass)
  describes, and for each reason decide whether you meant it.
- **Failures** — record them before you fix them. Do not iterate to green and
  report only the green run.
- **Regression comparisons** — each report carries `checked_count` and `valid_count`;
  they must be equal for every study, with an empty `errors` list.
- **Coverage** — a percentage over the `gridalyn` package, to be read and
  compared with the previous run, not defended. Do not add a threshold
  casually. Two limits: the study scripts under `projects/*/scripts/` are not
  measured at all (the `gridalyn/projects/` in the report is the SDK's
  project-contract layer); and work done inside workflow stages, which run as
  subprocesses, is not counted unless you enable the opt-in
  `COVERAGE_PROCESS_START` + `sitecustomize` hook documented beside
  `[tool.coverage.run]` in `pyproject.toml`. Without it, library code exercised
  only inside a stage reads as uncovered, and the figure understates real
  exercise.

## Receipts

What an operator ran is recorded in `docs/development/verification-receipts.json`:
what was run, at which commit, and what came out. CI checks that every receipt
is declared, complete, and pinned to a commit in this history.
`python tools/verification_receipt.py --check` prints every receipt, the
commit it was recorded at, and whether it is current; for a stale one it lists
the watched files that moved.

**STALE is not drift.** A receipt goes stale when a path it watches changes
after its commit. That says which protocols are unverified against the current
tree, not whether a number moved; only a re-run says that.

A receipt has a **role**. A `claim` (the default) asserts something about the
current tree — the flagship reproduces its pins — and goes stale when a file it
watches moves. A `measurement` records a dated observation kept for its
provenance, such as a coverage figure on a given day; it asserts nothing about
the current tree and so cannot go stale. `docs-instruction-sweep` is a claim:
it vouches that every documented instruction works, so its staleness is a real
gap. For each stale claim the report says how far behind it is, in watched
files and in commits, and lists the furthest-behind first.

For `ev_hosting_flex` and `admm_thermal_consensus` the `watched` list is **derived, not
written**: exactly the files a full regeneration loads — the stage modules the
study's `workflow.yaml` names, imported in a clean interpreter — plus the
project, the workflow DAG, the committed inputs and the pins the run is judged
by. `tests/test_heavy_study_receipts.py` requires equality and prints the
replacement list when they drift. `ev_hosting_flex` is receipted as
`flagship-subset` and `flagship-reproduce`, `admm_thermal_consensus` as
`admm-reproduce`.

## Staged regeneration of `ev_hosting_flex`

The study is verified by protocol rather than by one opaque run:

- `python tools/flagship_verify.py` runs a shape-covering subset: every stage
  except those in `HEAVY_STAGES` (`analyze_congestion_risk`,
  `analyze_credibility`, `analyze_cold_insurance`,
  `analyze_voltage_risk_network`) and, by dependency, every stage that needs
  one of them, then checks the baseline. It is the fast proof used on
  generator and kernel changes, recorded on the `flagship-subset` receipt.
- `python tools/flagship_verify.py --include-heavy` is the full regeneration,
  hours cold, recorded on the `flagship-reproduce` receipt at the commit it ran
  at.

Each run records per-stage entries — name, status, duration, and a reason when
a stage is skipped — so a partial regeneration is auditable. A receipt may
carry such a list; each stage must have a `name` and a `status` (`ok`,
`skipped` or `failed`), and any per-stage `commit` must exist in this history
and lead to HEAD.

Read a subset PASS with its boundary. The baseline check walks every pin,
including pins in outputs owned by stages that were not re-run; for those, a
PASS reads intact files rather than showing that their stages would reproduce
them. The reproduction claim rests on the stages actually executed.

## Twin consumer identity

`r7-twin-consumer-identity` answers a question no study can: **did a change to
`gridalyn/twin` change what a consumer of the twin sees?** No study reads the
twin, so no baseline can move; this protocol supplies the evidence directly.

Run it with `python tools/r7_twin_consumer_identity.py <before-ref> <after-ref>`.

**What it does.** It checks out each ref into its own git worktree and, from
each, captures `NetworkModelRepository.load_model()`,
`.validate_integrity()` and `build_dashboard_catalog()` over the **same** base
directory. It hashes each capture and classifies the difference as
`identical`, `additive` or `regressed`. Comparing two code revisions over one
set of artifacts is the point: a regenerated base would change the digest by
itself, and the comparison would measure the regeneration instead of the code.

**What the digest covers**, and only this: `load_model()`'s six counts,
`source_adapter`, `source_standard`, `provenance_status`, every
`ModelIdentity` field, and a content SHA-256 of each of the five canonical
tables (columns, dtypes, rows); `validate_integrity()`'s `valid`, `errors`,
`warnings` and `summary`; and the whole `build_dashboard_catalog()` mapping
minus `created_at`. The field set is stated because two comparisons that hash
different fields disagree without any difference in the code.

**Two controls make a green result mean something.** A *determinism* control
captures the same ref twice in two independent worktrees and requires an
identical digest. A *vacuity* control has each capture report the directory it
imported `gridalyn` from, and fails unless that directory lies inside the
ref's worktree, so a capture that silently read the main checkout fails
instead of matching itself.

**Two disclosed weaknesses.** `created_at` is stripped, because
`build_dashboard_catalog` derives it from `datetime.now()`. `identity.created`
is **not** stripped: it is read from the base manifest, so it is constant for a
fixed base, and code that stopped propagating it is a real difference.

**Why CI cannot run it.** The base parquet files are gitignored, so a runner
has no base to capture over, and the protocol needs full git history and two
working trees. Re-run it whenever a file on the receipt's `watched` list moves.
That list is exactly the code the capture loads — the `gridalyn` modules its
imports pull in, plus the tool itself — pinned by
`tests/test_r7_twin_consumer_identity.py`, which prints the replacement list
when the two drift apart. The receipt reading `STALE` after such a change is
the intended signal.

**The base is deliberately not watched.** R7 judges code over one fixed base.
Whether the published base is what the code builds is a different question,
answered on every push by `tools/check_instance_reproducible.py`. Watching it
could not work anyway: its parquets are gitignored, so the only file git sees
there is `metadata.json`, whose `created_at` moves on every export.

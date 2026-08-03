# Reproducibility Guide

This guide defines the shortest unambiguous path from a checkout to a verified
Gridalyn workspace. It covers source setup, artifact policy, demo project
checks, documentation, and dashboard readiness.

## Reproducibility Contract

A reproducible run must have:

| Requirement | Contract | Verification |
| --- | --- | --- |
| Source environment | dependencies installed through `uv` | `uv run gridalyn --help` |
| Clean artifact policy | generated data and caches are not accidentally tracked | `uv run gridalyn platform check-artifacts --summary-only` |
| Valid project contract | `project.yaml` and `workflow.yaml` are readable and complete | `uv run gridalyn project validate projects/minimal_grid_project` |
| Stable results | key numerical outputs match the baseline for larger workflows | `uv run gridalyn project regression projects/ev_hosting_flex` |
| Healthy code | tests pass | `uv run --with pytest python -m pytest -q` |
| Published docs | MkDocs builds strictly | `uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml` |

## 0. The Canonical Reproducible Install (Pinned 3.12, Frozen Lock)

A citable `ev_hosting_flex` result must be rebuildable bit-for-bit on a stranger's
machine. Two pins make that possible and are non-negotiable:

- **Interpreter pin** — the repo commits `.python-version` (`3.12`) at the root.
  `uv` and `pyenv` read it to select CPython 3.12, closing the divergence where a
  host's system interpreter (e.g. 3.10) or a stray `.pyc` (e.g. cpython-313) would
  otherwise resolve a different numeric stack and silently move the numbers.
- **Frozen dependency resolution** — install against the committed `uv.lock`
  **without re-resolving**, and **with the capabilities the citable result
  needs**:

```bash
uv sync --frozen --extra sim --extra ops --extra dev
uv run gridalyn --help
```

`uv sync --frozen` fails loudly if `uv.lock` is stale rather than silently
upgrading a transitive dependency. This — pinned 3.12 + `uv sync --frozen
--extra sim --extra ops --extra dev` — is **the** reproducible install. Plain
`uv sync` (used in the convenience steps below) is for day-to-day work, not for
reproducing a published result.

> **The extras are not optional for the citable numbers.** A bare
> `uv sync --frozen` installs **base deps only**, leaving the optional `sim`
> (`lightsim2grid`) and `ops` (`cvxpy`, `lightgbm`) capabilities uninstalled —
> `gridalyn doctor` then reports `cvxpy=false`, `lightgbm=false`,
> `lightsim2grid=false`. The `ev_hosting_flex` study **silently degrades** onto
> fallback code paths (still exit 0) and **moves 51/74 regression metrics**
> (only 23/74 valid). The `sim` + `ops` extras are required to reproduce the
> committed baseline; `dev` provides `pytest` for the determinism leg. This is a
> D-07 pinning/recipe correction (the install recipe was the defect) — **not** a
> re-baseline and **not** a tolerance change.

### Stage `uv run` invocation (no mid-run re-resolve)

The `ev_hosting_flex` workflow runs each stage as a separate `uv run python ...`
subprocess. To stop any of those 25 stage commands from re-resolving the
environment mid-run, run the whole workflow inside the already-frozen
environment so each stage `uv run` no-ops against the same interpreter and lock:

```bash
# Activate the frozen environment once, then run the workflow.
uv sync --frozen --extra sim --extra ops --extra dev
source .venv/bin/activate           # stage `uv run`s now reuse this env
gridalyn project run projects/ev_hosting_flex
```

Equivalently, pass `--frozen` / `--no-sync` to the stage invocations
(`uv run --frozen ...`) so no stage can silently re-resolve the lock.

### Fresh-venv Definition-of-Done recipe

The Phase-5 DoD (REPRO-05) is a clean-room rebuild from a fresh virtual
environment that a stranger can copy-paste verbatim from the repo root. Run the
whole block top-to-bottom; every step must be green and the committed baseline
must reproduce bit-for-bit.

```bash
# 1. Build a clean, frozen environment on pinned 3.12 WITH the required extras.
#    The citable ev_hosting_flex numbers depend on the optional `sim`
#    (lightsim2grid) and `ops` (cvxpy, lightgbm) capabilities; `dev` provides
#    pytest for the determinism leg below. A bare `uv sync --frozen` installs
#    base deps only — the study then silently degrades and moves 51/74 metrics
#    (see the D-07 note above and the doctor check on the next line).
rm -rf .venv
uv sync --frozen --extra sim --extra ops --extra dev
# Tripwire (Pitfall 1): this MUST print Python 3.12.x — not 3.10 / 3.13.
# uv selects 3.12 from the committed .python-version; a different version here
# means the pin is not being honoured and the numbers will move.
uv run python --version
# Capability tripwire: cvxpy, lightgbm, and lightsim2grid MUST all be true here.
# If any reads false, the extras above did not install and the regression will
# go red on degraded fallback paths — that is a recipe defect (D-07), not a
# baseline change.
uv run gridalyn doctor

# 2. Activate the frozen environment ONCE so every stage `uv run python ...`
#    subprocess (25 of them) reuses this exact interpreter+lock and cannot
#    re-resolve the environment mid-run (Pitfall 2). Then run the study.
source .venv/bin/activate
gridalyn project run projects/ev_hosting_flex            # expect exit 0
#    Equivalent without activating: prefix each stage with `uv run --frozen`
#    (or `--no-sync`) so no stage can silently re-resolve the lock.

# 3. Regression gate — this is the DoD. The committed baseline must reproduce.
gridalyn project regression projects/ev_hosting_flex     # expect "valid": true (81/81)

# 4. Determinism leg — the baseline must be byte-identical under two
#    PYTHONHASHSEED values (independent hash randomization, same numbers).
PYTHONHASHSEED=0 python -m pytest -q tests/test_repro_dod.py   # expect 0 exit
PYTHONHASHSEED=1 python -m pytest -q tests/test_repro_dod.py   # expect 0 exit

# 5. Network-free leg — the run must NOT depend on a live PVGIS fetch: the
#    committed TMY CSV (inputs/tmy_trois_rivieres.csv) is the only weather
#    source, `download_tmy` is never called, and an "auto" source is guarded.
#    tests/test_repro_dod.py::test_run_is_network_free asserts this; you can
#    also confirm no PVGIS fetch appears in the stage logs and that the run
#    manifest `provenance.python_version` records 3.12.x.
```

`PYTHONHASHSEED`, the interpreter version, the clearing-engine versions, the run
seeds, and the input file hashes are all recorded in the run manifest's
`provenance` block, so a divergence is an auditable **pinning defect**, not a
mystery.

> **D-07 — divergence is a pinning defect, never a re-baseline.** If the
> fresh-venv re-run does not reproduce the committed baseline bit-for-bit,
> **tighten the pin** (`.python-version`, the frozen `uv.lock`, a transitive
> dependency) until it matches. **Never** edit `results_baseline.json` and never
> loosen a tolerance to absorb the drift. A deliberate re-baseline is a separate,
> explicit, user-gated decision with a written rationale — it is never the
> automatic response to a red gate.

## 1. Start From The Repository Root

All commands in this guide run from the repository root unless a command says
otherwise.

```bash
uv sync --extra dev
uv run gridalyn --help
```

## 2. Check Artifact Hygiene

```bash
uv run gridalyn platform check-artifacts --summary-only
```

Expected result:

```text
"valid": true
```

If the command reports generated files under `projects/*/outputs`,
`instances/default/digital_twin/**/*.parquet`, `examples/generated/*`, `dashboard/public`, or
compiled document outputs, remove those files from the source change before
committing.

## 3. Validate A Demo Project

```bash
uv run gridalyn project validate projects/minimal_grid_project
uv run gridalyn project plan projects/minimal_grid_project
```

The validation command checks the project contract. The plan command prints the
stage order without executing the workflow.

## 4. Run Or Reuse The Workflow

Run the minimal demo when generated outputs need to be refreshed:

```bash
uv run gridalyn project run projects/minimal_grid_project
```

For larger workflows with a regression baseline, run:

```bash
uv run gridalyn project regression projects/ev_hosting_flex
```

Expected regression result:

```text
"valid": true
```

## 5. Verify Reports And Figures

```bash
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project verify projects/minimal_grid_project
```

The status command verifies required reports and figures declared in
`project.yaml`. The verify command runs the project status and sense-check
ladder for the selected project.

## 6. Validate Code And Documentation

```bash
uv run --with pytest python -m pytest -q
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

The test suite checks package boundaries, artifact policy, digital-twin
contracts, reports, semantics, project behavior, and regression helpers. The
MkDocs build verifies that the published documentation has no broken internal
links or invalid navigation entries.

## 7. Dashboard Readiness

Build the dashboard only after the data contracts are valid:

```bash
npm install --prefix dashboard
npm --prefix dashboard run build
docker compose -f dashboard/docker-compose.yml up -d --build dashboard
```

The dashboard should consume canonical catalog and report artifacts. It should
not depend on project-specific scripts unless those scripts are declared as a
project workflow stage.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Artifact policy fails | generated outputs are present in Git-tracked paths | remove generated files from the source change and rerun the policy check |
| Project validation fails | `project.yaml` or `workflow.yaml` references a missing path | update the manifest or generate the missing artifact |
| Regression fails | numerical behavior changed | inspect `outputs/reports/regression_report.json` and decide whether the baseline should change |
| MkDocs strict build fails | navigation points to a missing page or a link is broken | fix `docs/mkdocs.yml` or the referenced Markdown link |
| Dashboard build passes but data is stale | catalog/report artifacts were not regenerated | rerun the relevant `gridalyn twin`, project, or report command |

## Next Reading

- [Run Demo Projects](run-demo-projects.md)
- [Projects and Workflows](../platform/projects-and-workflows.md)
- [Artifact Policy](../development/artifact-policy.md)

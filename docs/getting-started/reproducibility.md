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
| Stable results | key numerical outputs match the baseline for larger workflows | `uv run gridalyn project regression projects/flexibility_cls` |
| Healthy code | tests pass | `uv run --with pytest python -m pytest -q` |
| Published docs | MkDocs builds strictly | `uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml` |

## 0. The Canonical Reproducible Install (Pinned 3.12, Frozen Lock)

A citable `flexibility_cls` result must be rebuildable bit-for-bit on a stranger's
machine. Two pins make that possible and are non-negotiable:

- **Interpreter pin** — the repo commits `.python-version` (`3.12`) at the root.
  `uv` and `pyenv` read it to select CPython 3.12, closing the divergence where a
  host's system interpreter (e.g. 3.10) or a stray `.pyc` (e.g. cpython-313) would
  otherwise resolve a different numeric stack and silently move the numbers.
- **Frozen dependency resolution** — install against the committed `uv.lock`
  **without re-resolving**:

```bash
uv sync --frozen
uv run gridalyn --help
```

`uv sync --frozen` fails loudly if `uv.lock` is stale rather than silently
upgrading a transitive dependency. This — pinned 3.12 + `uv sync --frozen` — is
**the** reproducible install. Plain `uv sync` (used in the convenience steps
below) is for day-to-day work, not for reproducing a published result.

### Stage `uv run` invocation (no mid-run re-resolve)

The `flexibility_cls` workflow runs each stage as a separate `uv run python ...`
subprocess. To stop any of those 25 stage commands from re-resolving the
environment mid-run, run the whole workflow inside the already-frozen
environment so each stage `uv run` no-ops against the same interpreter and lock:

```bash
# Activate the frozen environment once, then run the workflow.
uv sync --frozen
source .venv/bin/activate           # stage `uv run`s now reuse this env
gridalyn project run projects/flexibility_cls
```

Equivalently, pass `--frozen` / `--no-sync` to the stage invocations
(`uv run --frozen ...`) so no stage can silently re-resolve the lock.

### Fresh-venv Definition-of-Done recipe

The Phase-5 DoD is a clean-room rebuild from a fresh virtual environment:

```bash
# 1. Build a clean, frozen environment on pinned 3.12.
rm -rf .venv
uv sync --frozen

# 2. Run the study and confirm the regression baseline is byte-identical.
uv run gridalyn project run projects/flexibility_cls
uv run gridalyn project regression projects/flexibility_cls   # expect "valid": true (74/74)

# 3. Determinism leg — the run must be identical under two PYTHONHASHSEED values.
PYTHONHASHSEED=0 uv run gridalyn project regression projects/flexibility_cls
PYTHONHASHSEED=1 uv run gridalyn project regression projects/flexibility_cls

# 4. Network-free leg — the run must not depend on a live PVGIS fetch (the
#    committed TMY CSV is pinned; "auto" weather is guarded, never used).
```

`PYTHONHASHSEED`, the interpreter version, the clearing-engine versions, the run
seeds, and the input file hashes are all recorded in the run manifest's
`provenance` block, so a divergence is an auditable **pinning defect**, not a
mystery.

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
uv run gridalyn project regression projects/flexibility_cls
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

# Artifact Policy

Git holds source, contracts, tests, documentation, committed regression
baselines and one minimal demo dataset. It does not hold what a run generates:
study outputs, twin parquet, caches, compiled documents or publication
workspaces. The rule is code, not convention: `ArtifactPolicy` in
`gridalyn/foundation/platform/artifacts.py` declares it, and
`gridalyn platform check-artifacts` applies it.

## Run the check

```bash
uv run gridalyn platform check-artifacts --summary-only
```

A healthy working tree prints `"valid": true` and exits 0. Any error makes it
print `"valid": false` and exit 1; drop `--summary-only` to see each error.

## What the check enforces

- **No forbidden path is tracked.** A tracked file matching a forbidden
  pattern is an error, unless a shipped exception also matches it.
- **No forbidden path is waiting to be committed.** The same patterns apply to
  files Git sees but neither tracks nor ignores (the ones `git add -A` would
  commit). Other untracked files are not reported.
- **`.gitignore` carries every required rule** as an active line. A rule that
  is only mentioned in a comment does not count.
- **The minimal demo dataset is intact:** the directory exists, stays under the
  size limit, holds every required file, and its `manifest.json` declares each
  of the other required files under `files[].path`.

Patterns are shell-style (`fnmatch`) and matched against repository-relative
paths, so `*` also matches across `/`: `projects/*/outputs/*` covers every
depth under a study's `outputs/`.

## The policy

The lists below are generated from `ArtifactPolicy`'s defaults by
`tools/generate_artifact_policy_reference.py`;
`tests/test_artifact_policy_reference.py` fails when they drift from the code.

<!-- BEGIN GENERATED: tools/generate_artifact_policy_reference.py from ArtifactPolicy; do not edit by hand -->

### Forbidden paths

40 patterns (`forbidden_tracked_patterns`):

```text
*.h5
*.hdf5
*.npy
*.npz
*.pkl
.agents/*
.claude/*
.codex/*
.cursor/*
.roo/*
.windsurf/*
_build/*
cache/*
dashboard/public/*
examples/generated/cache/*
examples/generated/outputs/*
instances/*/digital_twin/**/*.npy
instances/*/digital_twin/**/*.npz
instances/*/digital_twin/**/*.parquet
instances/*/digital_twin/**/*.pkl
instances/*/digital_twin/models/**/*.parquet
instances/*/digital_twin/semantic/*.parquet
instances/*/digital_twin/timeseries/*
manuscripts/*
manuscripts/**/*.aux
manuscripts/**/*.bbl
manuscripts/**/*.bcf
manuscripts/**/*.blg
manuscripts/**/*.fdb_latexmk
manuscripts/**/*.fls
manuscripts/**/*.lof
manuscripts/**/*.log
manuscripts/**/*.lot
manuscripts/**/*.out
manuscripts/**/*.pdf
manuscripts/**/*.run.xml
manuscripts/**/*.synctex.gz
manuscripts/**/*.toc
projects/*/outputs/*
site/*
```

### Shipped exceptions

Tracked even though a forbidden pattern matches them (`allowed_tracked_patterns`):

- `gridalyn/assets/datagen/models/weights/*.pkl`

### Required `.gitignore` rules

20 rules, each an active line (`required_gitignore_patterns`):

```text
.agents/
.claude/
.codex/
.cursor/
.roo/
.windsurf/
/site
_build/
cache/
dashboard/public/
examples/generated/cache/
examples/generated/outputs/
instances/*/digital_twin/**/*.parquet
instances/*/digital_twin/timeseries/
manuscripts/
manuscripts/**/*.aux
manuscripts/**/*.fdb_latexmk
manuscripts/**/*.pdf
manuscripts/**/*.synctex.gz
projects/**/outputs/
```

### Minimal demo dataset

- Directory: `examples/tutorials/data/minimal/`
- Size limit: 10485760 bytes (10 MiB)
- Required files (`required_minimal_dataset_files`):
    - `buildings.geojson`
    - `expected_summary.json`
    - `grid_edges.geojson`
    - `grid_nodes.geojson`
    - `manifest.json`
    - `scenarios.json`

<!-- END GENERATED -->

The weights exception exists because the trained macro weights are package
data, not run output: without them the load generator falls back to a
different model and the CI fixture studies stop matching their baselines.

## Where generated artifacts live

Regenerate them; do not commit them.

- A study's outputs are written under `projects/<study>/outputs/` by its
  workflow (`gridalyn project run projects/<study>`).
- A twin's artifacts live under `instances/<instance>/digital_twin/`, written
  by `gridalyn twin build --instance <instance>` (default instance `default`).
  The instance's JSON manifests and reports are tracked; the policy forbids its
  parquet, pickled and array files and its time series.

Tutorial inputs outside the minimal dataset stay small, documented and tied to
a runnable example; a new tutorial either uses the minimal dataset or declares
its input under `projects/<study>/inputs/`.

## Regression baselines

A study's `baselines/results_baseline.json` is tracked on purpose: it is what
the regression check compares against. Moving it is a deliberate re-base,
recorded as [Recording a re-base](../contributing/verification.md#recording-a-re-base)
describes.

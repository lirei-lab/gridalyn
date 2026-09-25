# Development Workflow

The path from a fresh clone to a green pull request: set up, keep generated
files out of the change, check locally, and know which CI gate will judge what.

## Set up

```bash
git clone https://github.com/lirei-lab/gridalyn-dev.git gridalyn
cd gridalyn
pip install -e ".[dev]"
pre-commit install
```

The `dev` extra carries every runtime extra plus the test, lint, type-check
and docs tools. `pre-commit install` sets up both hook stages the repository
declares, `pre-commit` and `pre-push`. `uv.lock` is committed; CI builds its
locked environment with `uv sync --locked`, and a `.venv` built that way is
what `tools/mypy_ratchet.py` prefers when it exists. For the user-facing
install, see [Installation](../start/installation.md).

| Requirement | Why | Symptom if missing |
| --- | --- | --- |
| Python 3.12 in a `.venv` | An older system `python3` cannot import the package. | Import errors, or a suite that will not collect. |
| `mypy==1.9.0` (in the `dev` and `typing` extras) | The ratchet compares an error *count*, and a different mypy version returns a different count for the same tree. | The pre-push ratchet names the fix: `pip install -e ".[typing]"`. |
| Network access | `tests/test_packaging_contract.py` builds a real wheel with pip build isolation, which resolves `setuptools>=77.0` from an index. | That test fails on `no matching distribution`. |
| `setuptools>=77.0` in the build environment | `pyproject.toml` uses the SPDX `license = "MIT"` form (PEP 639), which older setuptools rejects. | `invalid pyproject.toml config: 'project.license'`. |
| `datasets/hq/consumption.h5` | The Hydro-Québec validation set is gitignored; the building-diversity tests compare against it. | Those tests skip, with a reason naming the dataset. |

An offline wheel build works with `PIP_NO_INDEX=1 --no-build-isolation` only if
the environment already has `setuptools>=77.0`.

If a `uv` command leaves `uv.lock` modified, that is a re-lock (a different
`uv` version, or a `pyproject.toml` edit that forces re-resolution), not a
product of anything you ran. Unless you mean to land the re-lock as its own
change, restore it path-scoped:

```bash
git checkout -- uv.lock
```

## Where files belong

| Path | Holds | Keep out |
| --- | --- | --- |
| `gridalyn/` | The reusable SDK. | Study-specific orchestration, local outputs, generated reports. |
| `projects/<name>/project.yaml` | The study's identity, problem, inputs, outputs and validation expectations. | Runtime state or implementation logic. |
| `projects/<name>/workflow.yaml` | Ordered workflow stages and their commands. | Reusable modeling, solver or market algorithms. |
| `projects/<name>/scripts/` | Thin stage scripts. | Shared behaviour that belongs in `gridalyn/`. |
| `projects/<name>/outputs/` | Generated study artifacts (gitignored). | Hand-edited files. |
| `instances/<name>/digital_twin/` | A materialized twin instance consumed by the dashboard, reports and the semantic graph. | Notebooks, drafts, scratch files. |
| `configs/` | Shared grid and geography configuration. | Tutorial output. |
| `examples/` | Tutorials and small learning scripts. | Anything a study depends on at run time. |
| `docs/` | This site's source. | The built site (`site/`, gitignored). |

An artifact that proves one study's workflow goes under that study's
`outputs/`; one that belongs to a twin instance the dashboard, semantic graph
or reports read goes under `instances/<name>/digital_twin/`. The directory
layout of both is owned by `ArtifactLayout`, described in
[Foundation](../components/foundation.md); what may be committed at all is the
[Artifact Policy](../reference/artifact-policy.md). Dashboard-facing state
flows through those contracts (the catalog at
`instances/<name>/digital_twin/dashboard/catalog.json`, the semantic
artifacts, the canonical reports under
`instances/<name>/digital_twin/reports/canonical/`, and each study's platform
reports), never through a script writing into the dashboard directly.

Running studies and twin commands regenerates files, and a few commands
rewrite **tracked** files by design: `gridalyn twin build` rewrites files under
`instances/default/`, as do `gridalyn dashboard catalog` and `python -m
gridalyn.interfaces.reporting.digital_twin`. `gridalyn twin build --dry-run`
writes nothing, and the dashboard catalog and the canonical-report module
refuse to run, naming the missing files, when the generated twin artifacts
they read are absent rather than overwriting the tracked files with degraded
ones. Check `git status
--short` after running any of them, and commit regenerated artifacts only when
the change is meant to update them.

## Check locally

Run the narrowest check that covers your change first, then widen. Which
checks a given change needs, and how to read their results, is in
[Testing And Validation](testing-and-validation.md). Formatting, linting and
type checking run as git hooks:

| Tool | Hook stage | Role |
|---|---|---|
| `black` | pre-commit | formatter, line length 88 |
| `isort` | pre-commit | import ordering, `--profile black` |
| `flake8` | pre-commit | PEP 8, complexity, `flake8-bugbear`, `flake8-docstrings` |
| `mypy` | pre-push | static types, `--disallow-untyped-defs`, as three ratchets |

Run the commit-stage hooks over the whole tree:

```bash
pre-commit run --all-files
```

Add `--hook-stage pre-push` to run the mypy ratchets instead. Three notes on
these hooks:

- The tree passes `flake8` with both plugins. CI lints only the files a pull
  request changes, so a clean tree is a state to hold, not one the gate
  restores. Check that `flake8 --version` lists both plugins before trusting a
  clean local result.
- `black` is not clean across the tree. Touching an unformatted file pulls its
  reformatting into your diff, and `--all-files` reformats every such file.
- A mypy ratchet fails only when its error count rises above its baseline, not
  when the count is non-zero.

## What CI checks on your pull request

`.github/workflows/ci.yml` runs on every pull request and every push to
`main`. On a pull request, a `changes` job first classifies the diff: the
`projects` job is skipped when nothing under `gridalyn/`, `projects/`,
`tests/`, `tools/`, packaging or workflows changed, and the `dashboard` job
when nothing under `dashboard/` or workflows did. On `main` everything runs.

To run the `lint`, ratchet, receipt and test gates before you push, use
`python tools/verify_local.py`. It executes these jobs' own steps from
`ci.yml` on the tests your change reaches; `--all` runs the whole suite.

| Gate | Job | What trips it | Run it locally |
| --- | --- | --- | --- |
| Test suite | `test` | Any failing test, excluding the tests marked `governed_study_run`, `governed_study_outputs` or `mutates_repository`. Hypothesis runs its reduced `ci` profile here. The architecture and convention gates on [Architecture Rules](module-boundaries.md) and [Conventions](conventions.md) are part of this suite. | `HYPOTHESIS_PROFILE=ci python -m pytest -q -n 4 --dist loadfile -m "not governed_study_run and not governed_study_outputs and not mutates_repository"` |
| Repository-writing tests | `test` | A failing test marked `mutates_repository`. They run in one process after the parallel suite, because each writes into the working tree while it runs. | `python -m pytest -q -m mutates_repository` |
| mypy ratchet, SDK | `test` | Errors in `gridalyn/` above `.mypy-baseline` (114). | `python tools/mypy_ratchet.py` |
| mypy ratchet, studies | `test` | Errors in `projects/` above `.mypy-baseline-projects` (62). | `python tools/mypy_ratchet.py --target projects --baseline-file .mypy-baseline-projects` |
| mypy ratchet, twin | `test` | Errors in `gridalyn/twin/` above `.mypy-baseline-twin` (11). | `python tools/mypy_ratchet.py --target gridalyn/twin --baseline-file .mypy-baseline-twin` |
| Baseline citations | `test` | A number quoted beside a `.mypy-baseline*` file name in `docs/` that is not that file's count; a baseline file above its measured count is reported as slack. | `python -m pytest -q tests/test_mypy_ratchet.py` |
| Instruction ledger | `test` | A fenced code block in `docs/**/*.md` or `README.md` that is new, edited, or gone without its entry in `docs/development/instruction-ledger.json` being added, re-reviewed or removed. | `python tools/check_doc_instructions.py`; `--suggest` drafts entries for new blocks, which you then review |
| Doc path references | `test` | A repository path in the docs that should resolve and does not, or one the classifier cannot place. | `python -m pytest -q tests/test_doc_path_references.py`; `python tools/check_doc_paths.py --list UNCLASSIFIED` for detail |
| CLI reference | `test` | A command, option or default in the `gridalyn` parsers or the workflow scripts they pass arguments to that the generated tables in `docs/reference/cli.md` do not match. | `python tools/generate_cli_reference.py --check`; without `--check` it rewrites the tables |
| Project And Workflow YAML reference | `test` | `docs/reference/workflow-yaml.md` differing from what `tools/generate_yaml_reference.py` generates from `gridalyn/projects/schemas/` and `projects/ev_hosting_flex/workflow.yaml`, or the page's example project failing validation. | `python tools/generate_yaml_reference.py --check`; without `--check` it rewrites the page |
| Artifact policy reference | `test` | The generated lists on [Artifact Policy](../reference/artifact-policy.md) no longer matching `ArtifactPolicy` in `gridalyn/foundation/platform/artifacts.py`. | `python tools/generate_artifact_policy_reference.py --check`; drop `--check` to rewrite the lists |
| Study inventory | `test` | The generated table on [The Studies](../start/studies.md) no longer matching `projects/*/project.yaml`, the study loop of the `projects` job in `ci.yml`, or the extras each study's code needs. | `python tools/generate_studies_reference.py --check`; drop `--check` to rewrite the table |
| Registry tables | `test` | The generated registry tables on [Simulation](../components/simulation.md) and [Twin](../components/twin.md) no longer matching the IDs the default registries hold. | `python tools/generate_registry_reference.py --check`; drop `--check` to rewrite the tables |
| Verification receipts | `test` | A receipt for an operator protocol that is undeclared, incomplete, or pinned to a commit not in this history. A stale receipt is reported, not failed. | `python tools/verification_receipt.py --check` |
| Documented command smoke run | `projects` | A documented command that fails, or that leaves tracked files modified. | The command list is in the job's first step. |
| Fixture study runs | `projects` | A failing test marked `governed_study_run` (runs a fixture study in place) or `governed_study_outputs` (reads what those runs wrote). | `python -m pytest -q -m governed_study_run`, then `python -m pytest -q -m governed_study_outputs` |
| Fixture study baselines | `projects` | A fixture study whose regression against `baselines/results_baseline.json` has an invalid metric. | `gridalyn project run projects/<name>`, then `gridalyn project regression projects/<name>` |
| Twin instance reproduces | `projects` | `gridalyn twin build` not completing its full chain, or producing an instance that differs from the committed `instances/default/` beyond timestamps and a `1e-6` relative float tolerance. | `gridalyn twin build`, then `python tools/check_instance_reproducible.py`, then `git checkout -- instances/` to restore the tracked files the build rewrote |
| Dashboard | `dashboard` | A failing unit test or build in `dashboard/`. | `npm ci && npm test && npm run build` in `dashboard/` |
| Lint on changed files | `lint` (pull requests only) | `black`, `isort` or `flake8` findings in the files the pull request changes. The mypy ratchets are `pre-push` hooks, so this `pre-commit`-stage run does not include them; the `test` job runs them. | `pre-commit run --from-ref origin/main --to-ref HEAD` |
| Strict docs build | `docs` | A broken link, missing nav target or any other MkDocs warning. | `mkdocs build --strict -f docs/mkdocs.yml` |
| Mermaid diagrams | `docs` | A mermaid diagram in the docs that does not compile. `mkdocs build` cannot see this; the diagram is parsed in the reader's browser. | `npm install --no-save mermaid@11 jsdom && node tools/check_mermaid_diagrams.mjs` |

The `test` and `projects` jobs measure in a `.venv` synced `--locked` from
`uv.lock`, so a result is a claim about the declared environment. The
fixture-study list the `projects` job loops over is in `ci.yml`; the two
operator-verified studies are not in it, and what that leaves to you is on
[Operator Verification](verification.md).

Every night the same workflow runs on `main` at full strength: the
Hypothesis property test runs its full example count instead of the `ci`
profile. A red nightly run opens its own tracker issue, separate from the one
for pushes to `main`, and only a green nightly run closes it, because a green push
runs the lighter gate and cannot vouch for what the full-strength run checks.

## Commit

```bash
git status --short
git add <intentional files>
git diff --cached --stat
git commit -m "Concise message"
```

Avoid a broad `git add .` after running studies: the working tree usually
holds regenerated artifacts that are not part of the change. For the same
reason, never `git stash` in a working tree with study outputs you want to
keep.

## Documentation changes

Documentation source lives under `docs/`; the built site goes to `site/`,
which is ignored. When a change moves the reader's path or a contract, update
the page that owns the topic rather than restating it elsewhere:

| Change | Owner page |
| --- | --- |
| A page added, moved or removed | the `nav` in `docs/mkdocs.yml`, plus a `redirects` entry for the old path |
| Layer placement | [The Platform, In One Pass](../components/overview.md) |
| Twin data layout | [Twin](../components/twin.md) |
| Project contract behaviour | [Projects](../components/projects.md) |
| The report or run-manifest contract | [Report And Run-Manifest Schema](../reference/report-schema.md) |
| Ontology or semantic graph | [Semantic Graph](../reference/semantic-graph.md) |
| Visualization and catalogs | [Interfaces](../components/interfaces.md) |
| Git, data and generated-output policy | [Artifact Policy](../reference/artifact-policy.md) |
| Verification commands | [Testing And Validation](testing-and-validation.md) |

Every fenced block you add or edit needs its instruction-ledger entry updated
in the same change; the gate above says how.

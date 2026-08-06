# Documentation Instruction Verification

This page is the protocol behind `docs/development/instruction-ledger.json`. It
records how the documentation's runnable instructions were verified, what the
gate enforces afterwards, what runs in CI, and — just as importantly — which
instructions were deliberately **not** run and why.

The sibling page `development/verification.md` covers verification of the *code*.
This one covers verification of the *documentation's instructions*: the commands
a reader is told to type.

## Why a ledger rather than "run the docs"

The corpus is **78 documents carrying 354 fenced blocks** — including this page,
which is classified in the ledger like any other. Executing all of them is
neither possible nor meaningful. Only 162 are runnable at all:

| Class | Count | What verification means |
| --- | ---: | --- |
| `RUNNABLE-INDEPENDENT` | 88 | Run it alone in a prepared environment |
| `RUNNABLE-SEQUENCE` | 74 | Run the whole chain in one shared workspace |
| `ILLUSTRATIVE` | 150 | Read it — output samples, YAML, diagrams, sketches |
| `LONG-RUNNING` | 24 | Over ten minutes; documented, with the decision recorded |
| `DESTRUCTIVE` | 4 | Deletes state or mutates a remote; never executed |
| `ENV-DEPENDENT` | 14 | Needs a runtime beyond Python — npm, docker, network |

A gate that tried to run all 354 would be red forever. A gate that ran none of
them would prove nothing. So each block is classified once, by reading it, and
the classification is pinned in a tracked ledger keyed by
`<path>#<ordinal>` with the block's `sha1`. Edit a classified block and the hash
stops matching: the entry is reported stale, because its verdict was evidence
about text that no longer exists.

## The verdicts

| Verdict | Meaning |
| --- | --- |
| `PASS-AS-WRITTEN` | Executed verbatim; it worked |
| `FIXED-DOC` | Executed; it failed; the **documentation** was wrong and was corrected |
| `FIXED-CODE` | Executed; it failed; the **code** was wrong and was fixed |
| `DOCUMENTED` | Deliberately not executed, with the reason recorded |
| `UNVERIFIED` | Nobody has answered for it yet — the state the gate now forbids |

As of the 2026-08-06 close-out the corpus carries **zero `UNVERIFIED`
instructions**. Resolved per runnable instruction, the distribution is
95 `PASS-AS-WRITTEN`, 63 `FIXED-DOC`, 3 `DOCUMENTED` and 1 `FIXED-CODE`.

## Reading the ledger

Start with the harness. It extracts the corpus, checks the ledger against it,
and prints the distributions:

```bash
uv run python tools/check_doc_instructions.py --report
```

Exit status is 0 when the ledger covers the corpus exactly, and 1 with one
located finding per problem — an unclassified block, a stale hash, an orphaned
entry, a schema violation.

## Two details that trip people up

**A `RUNNABLE-SEQUENCE` member leaves `verdict` null on purpose.** Running
member 5 of a tutorial chain alone is meaningless — it consumes the project
member 3 created — so the chain, not the block, is the unit that can be
verified. The `sequences` entry owns the single verdict and the member points at
it. This is not a hole: the gate resolves every member *through* its sequence,
so flipping a sequence to `UNVERIFIED` turns all of its members red by name. A
null is a pointer here, never a hiding place.

**`date: null` is not always "pending".** It is the date a verdict was evidenced
*by execution*. An entry whose verdict is the classification decision itself — a
`DOCUMENTED` illustrative block, say — legitimately carries no execution date.
Its non-empty `rationale` is the decision. What the gate forbids is a
`DOCUMENTED` verdict with **no** rationale, which would be an opt-out from
verification wearing a verdict's clothes.

## The protocol

The sweep that produced the current verdicts ran in three waves.

1. **Classify.** Read every block; record `class`, `family`, `sha1` and a
   rationale for anything not runnable. The tool offers a structural suggestion
   from the fence language and command names, but it is advice only — 124 of the
   354 entries override it, which is what distinguishes a reviewed ledger from a
   generated one.
2. **Execute, by family.** Split the runnable population three ways —
   `getting-started`, `platform`, `development` — and run each family's blocks in
   a scratch workspace. Record what actually happened in `evidence`, including
   exit codes and timings. When a block fails, fix the **cause**: correct the
   document (`FIXED-DOC`) or the code (`FIXED-CODE`), then re-run it.
3. **Merge and close.** Fold the fragments into the tracked ledger, refresh the
   `sha1` of any block an edit changed, re-derive `line`, and turn on the
   assertions that keep the result true.

Two rules govern step 2, both learned the hard way:

- **Never add or remove a fenced block in an existing document.** Ordinals are
  ledger keys, so an insertion silently renumbers every later block in the file
  and invalidates their hashes. Corrections that would need a new block are
  written as prose instead.
- **Never let a documented command write a tracked file.** Redirect output to a
  scratch directory, or to an in-repo but git-ignored path. Finding #40 began as
  a documented command quietly regenerating a committed artifact.

## Running the full sweep

There is no "execute the whole corpus" script, and there should not be: the
runnable population needs a clean workspace per chain, several path
substitutions, and a human deciding what a failure means. What the tooling gives
you is the worklist.

```bash
uv run python tools/check_doc_instructions.py --report
uv run python tools/check_doc_instructions.py --list RUNNABLE-INDEPENDENT
uv run python tools/check_doc_instructions.py --dump /tmp/doc-blocks.json
```

`--dump` writes every block's full content to JSON so a reviewer can read them
without opening 78 files. Work through one family at a time, in a scratch
workspace, and record evidence per block. Budget roughly five minutes per
runnable block including the fixes; the measured runtimes of the blocks
themselves sum to about 320 seconds, so the cost is the reading and the
diagnosis, not the running.

## The gate

`tests/test_doc_instructions.py` runs in the `test` CI job in under a second. It
enforces:

- **Coverage, both ways.** Every fenced block has an entry; no entry names a
  block the corpus no longer has.
- **Hash freshness.** A classified block whose content changed goes stale rather
  than silently keeping a verdict about text that no longer exists.
- **Zero `UNVERIFIED`.** Every runnable instruction resolves to an answered
  verdict — directly, or through its sequence.
- **Justified deferrals.** Any entry, block or sequence, whose verdict is
  `DOCUMENTED` must say why it was not executed.
- **Ownership.** No document carrying commands may sit outside every
  verification family.
- **The flagship deferral.** The `ev_hosting_flex` decision below stays recorded.

Each of the last three has a mutation test that watches it go red first, so no
assertion is trusted green without having been seen to fail.

```bash
uv run python -m pytest tests/test_doc_instructions.py -q
```

## The CI smoke subset

The gate above proves the ledger still *describes* the documentation. It never
runs a documented command, so a CLI rename would leave every verdict green while
the docs rotted. The `projects` job therefore carries a
`Smoke-run the documented instruction subset` step that executes a
representative slice.

**Measured 2026-08-06, three runs: 13.82 / 13.74 / 14.16 s**, against a 90 s
budget. It covers 14 instructions chosen for breadth of command surface —
`--help`, `validate`, `doctor`, `platform check-artifacts`, `project validate`,
`project init`, the `first-hour.md#3` run/status/verify chain, and `quickstart`
from a clean directory — and it finishes by asserting that none of them dirtied
the working tree, because a documented command regressing into writing a
committed artifact lands as a dirty index rather than a non-zero exit.

Two deliberate choices:

- **It rides the existing `projects` job** rather than getting its own. A fourth
  job would pay a second checkout and a second `pip install -e ".[all,test]"` —
  minutes of duplication to host fourteen seconds of work.
- **It runs before the study loop.** `doctor` and `check-artifacts` are exactly
  the commands that used to fail on a fresh checkout. Run them after six studies
  have produced outputs and the regression they guard could not reproduce.

**What a green smoke does not prove.** It covers 14 of 162 runnable
instructions. It cannot catch a document that gives the right commands in the
wrong order — the dominant defect of the 2026-08-06 sweep, 8 of 13
documentation fixes — because that needs a clean workspace per chain, which does
not fit any CI budget. The full sweep stays an operator protocol.

## Recorded decisions

### The flagship study run is documented, not run

`ev_hosting_flex` takes roughly six hours end to end. **15 `LONG-RUNNING` blocks
instruct it** — including the operator command below — and none was executed; all carry `DOCUMENTED` with a rationale, and
the decision is pinned in the ledger's `deferrals` section so that dropping it,
or letting one of those blocks quietly leave the `LONG-RUNNING` class, fails the
gate. The pin is derived from the corpus, so a new block instructing the study
is red until the decision is extended to cover it.

What was verified instead is every instruction that reads the study's contract
without running it — `docs/sdk/public-contract.md#0` loads its YAML and passes.
The operator command that would close the gap is:

```bash
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project regression projects/ev_hosting_flex
```

Re-running that, and re-evidencing the 14 blocks against it, is the standing
follow-up.

### Three documents are owned by ruling, not by prefix

The family split is by directory prefix, and four documents fall outside every
prefix. The `platform` family was ruled their owner and executed what there was
to execute; the ledger's `verification_owners` records the ruling:

| Document | Verified by |
| --- | --- |
| `docs/index.md` | platform |
| `docs/semantic-layer/falkordb.md` | platform |
| `docs/semantic-layer/semantic-graph.md` | platform |

Only two of those three actually carry commands: `docs/index.md` and
`semantic-graph.md`, whose 3 runnable blocks the platform family ran.
`falkordb.md` carries four illustrative cypher blocks and nothing to execute,
and the fourth unowned document, `docs/applications/reports.md`, carries no
fenced block at all — so neither needs an owner for the gate's rule to hold.

This lives in the ledger rather than in each entry's `family` field on purpose.
`family` is a **derived** field: the harness recomputes it from `FAMILY_PREFIXES`
and reports any entry that disagrees, so it cannot carry an ownership ruling the
prefix table does not encode. Folding these three into `FAMILY_PREFIXES` is the
cleaner long-term fix and would let the override map be deleted.

## Open findings

Two defects found by the sweep were reported rather than fixed, and are carried
forward:

- **`market_dispatch_timeseries.parquet` has no producer.** Four sites read it;
  nothing has written it since `flexibility_cls` was retired. Nine documented
  commands fail because of it, and `docs/platform/dashboard.md#9` cannot be
  verified green anywhere in the repository as a result.
- **`gridalyn twin build --include-network-impact` exits 0 with 5 of 22 steps
  failed.** A non-zero exit is what a caller would expect, and what CI would
  need.

Three other defects the sweep found *were* fixed, and their blocks now carry
`FIXED-CODE`: `gridalyn doctor` no longer inherits an artifact check that failed
on every fresh checkout; `npm run lint` exits 0; and the dashboard catalog no
longer drops the served path prefix when regenerated.

### Finding #40, resolved

The dashboard catalog and four canonical reports under `instances/` kept
reappearing as modified tracked files. The standing hypothesis was that some
test regenerated them. **That was wrong.** The full suite was instrumented with a
per-nodeid watcher over the mtime and sha1 of all 29 tracked files under
`instances/`: `1068 passed, 1 xfailed`, and **not one of those files changed
during any test**.

The writer is a documented CLI command — `gridalyn twin build`, whose final
orchestrator step generates the catalog, reachable as `gridalyn dashboard
catalog` too. And the diff was not timestamp churn but a real content
regression: every regeneration wrote scenario paths as `/digital_twin/...` where
the served dashboard needs `/instances/default/digital_twin/...`. The fix is in
`gridalyn/projects/dashboard_catalog.py`, with three regression tests seen red
first.

The lesson worth keeping: timing alone would have produced a false positive. A
candidate test run happened to land in the same second as the real writer, and
only per-file bisection ruled it out.

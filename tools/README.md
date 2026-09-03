# `tools/`

Eleven scripts at this level. Ten Python, one Node (`check_mermaid_diagrams.mjs`
— the mermaid parser this repo needs isn't available in Python, so it stands
alone as the one non-Python tool here). Plus one directory,
[`ochre_calibration/`](#ochre_calibration), which is a harness rather than a
check and so gets its own section instead of ten near-identical table rows.
Each script carries a substantial module docstring explaining *why* it exists;
this file is the index that says *when to run it* and *what actually calls
it*, which the docstrings alone don't convey.

## How a tool reaches the tree

Three ways, and they are not equivalent:

- **CI-wired** — a `.github/workflows/ci.yml` or `.pre-commit-config.yaml`
  step invokes it directly. Every push is covered.
- **pytest-gated** — a test in `tests/` imports it as a module or invokes it
  as a subprocess and asserts on the result. Also covered on every push,
  just indirectly: `pytest -q` is what actually runs it.
- **Operator-only** — nothing in CI or the test suite calls it. It runs by
  hand, and for the ones that back a claim this repo makes, the result is
  recorded as a receipt in `docs/development/verification-receipts.json`
  rather than re-proven on every push. See
  [Operator Verification](../docs/development/verification.md) for why some
  verification is deliberately operator-side rather than CI-side (the
  flagship study's ~6 h regen and the measured-ingest proof's real
  `datasets/hq` dependency are the two recorded reasons).

## Index

| Tool | Reached by | What it checks |
|---|---|---|
| `check_doc_instructions.py` (1,098 lines) | pytest-gated (`tests/test_doc_instructions.py`) | Classifies every fenced code block in the docs into six verification classes and pins each one's content hash; a changed block or a new unclassified one fails the gate. |
| `check_doc_paths.py` (771 lines) | pytest-gated (`tests/test_doc_path_references.py`) | Classifies every path reference in the docs (SOURCE / SHORTHAND / RUNTIME / UNCLASSIFIED); a stale SOURCE reference fails unless individually allowlisted with a reason. |
| `check_mermaid_diagrams.mjs` (144 lines) | CI-wired (`Documentation build` job) | Parses every ` ```mermaid ` fence with the real Mermaid parser Material loads from its CDN. `mkdocs build --strict` cannot see a broken diagram — this is the gate that can. |
| `mypy_ratchet.py` (148 lines) | CI-wired (`test` job) + pre-commit | Runs mypy over `gridalyn/` and fails only if the error count *rose* from the committed baseline — a ratchet, not a zero-errors gate, because the tree does not pass mypy clean today. |
| `verification_receipt.py` (443 lines) | CI-wired (`test` job) + pytest-gated (`tests/test_verification_receipts.py`) | Accounts for the operator-only verification protocols below: every required protocol must be declared, every declared receipt must be complete, and every receipt's pinned commit must really exist and lead to `HEAD`. Reports staleness (a receipt whose watched paths changed since) without failing on it. |
| `flagship_verify.py` (337 lines) | pytest-gated (`tests/test_flagship_verify.py`) | A shape-covering representative subset of the flagship `ev_hosting_flex` study's reproduce-and-pin protocol — the fast check; the full ~6 h regen is operator-only, receipted separately. |
| `r7_twin_consumer_identity.py` (535 lines) | Operator-only, receipted | Two-ref verdict tool for the R7 guardrail (studies untouched by a twin-layer change): `tool.py <ref1> <ref2>` diffs the twin's real consumers' output. The no-arg form only snapshots — it is not a verdict. |
| `measured_ingest_proof.py` (391 lines) | Operator-only, receipted | At-scale proof of the measured-state ingest path against `datasets/hq`'s real 35,041×1000 axis. Needs that dataset on disk (544 MB, gitignored, undistributable) — CI genuinely cannot run this one. |
| `render_hero_network.py` (206 lines) | Operator-only, no receipt | Regenerates the documentation homepage's hero image from the digital twin's real Trois-Rivières feeder. Run it after a change to the twin's geometry or styling; nothing else depends on its output being fresh. |
| `stage_profile.py` (490 lines) | Operator-only, no receipt | Reads a study's run manifest — which already records `started_at`/`ended_at` per stage — and reports where its wall time actually goes: per-stage share, the wave each stage sits in, and the speedup a concurrent runner could reach on the *measured* costs rather than on the DAG's shape. Flags a manifest that is partial (`--stage` filter) or stale (workflow gained stages since the run) instead of folding it into the totals. Recorded output: `docs/development/stage-profiles.md`. |

## `ochre_calibration/`

**Operator-only, no receipt.** Ten Python scripts that build a Québec
all-electric dwelling fleet from the open NRCan archetypes, simulate it in
EnergyPlus at 15 minutes per end use, and measure gridalyn's RC building model
against it. Nothing in CI or the test suite calls any of them, and nothing
can: the harness downloads roughly 1.6 GB of vendor toolchain into a
gitignored workdir and takes ~20 minutes for a 74-dwelling fleet.

It is a *harness*, not a gate — the one exception is `check_fleet_gate.py`,
which is a gate over the harness's own output rather than over the repository.

EnergyPlus never enters gridalyn's environment. `ochre-nrel` pins
`numpy==1.26.4` and `h2k-hpxml` pins `numpy==1.26.2`; the two are mutually
incompatible and both sit below this repo's floor of 2.1.3, so the harness
runs them in their own virtualenvs behind a process boundary.

| Script | Role |
|---|---|
| `build_fleet.py` | Stratified sample of the NRCan Québec all-electric pool into a manifest carrying every row's source hash and the sampling seed. Allocation is largest-remainder with **no** per-stratum floor — an earlier floor put pre-1900 dwellings at 21 % of the fleet against 1.8 % of the stock. |
| `run_fleet.py` | Retimes the translated HPXML to 15 minutes, draws a per-dwelling occupancy seed and thermostat schedule, optionally replays a flexibility decision, and simulates. |
| `plot_fleet.py` | Individual traces, aggregate by end use, and the diversity curve. |
| `validate_scaling.py` | Coincidence factor against pool size, convergence at the pool's edge, what replication to feeder size does, and the implied feeder MW. |
| `check_fleet_gate.py` | Gates a fleet against thresholds taken from the **measured** `datasets/hq` subset, not from prose. Its own header records the four figures it replaced and why each was wrong. |
| `compare_diversity.py` | Uniform versus per-dwelling thermostat schedules, on one axis. |
| `measure_flex_bound.py` | What a flexibility decision actually delivers — relief, pre-heat cost, rebound, comfort drift — on dwellings the bound was not fitted on. |
| `rc_dispatch.py` | What the RC surrogate *promises* for that same decision. The gap between this and the previous row is the surrogate's error bound. |
| `run_feasibility_gate.py`, `ochre_driver.py` | The original OCHRE feasibility gate. Kept because it is what established that OCHRE's envelope model cannot represent the conditioned basement 92.6 % of the Québec stock has — a negative result worth not repeating. |

Needs `datasets/hq` on disk for anything that compares against measurement,
the same 544 MB gitignored dataset `measured_ingest_proof.py` depends on.

## Adding a new tool

Follow the pattern above, not the path of least resistance: decide which of
the three reach-classes it belongs to *before* writing it, because that
decision determines whether it needs a pytest wrapper, a `verification-
receipts.json` protocol entry, or neither. A tool that backs a claim in the
docs or in `CLAUDE.md` and has no CI/pytest coverage should almost always
gain a receipt — see `verification_receipt.py`'s own module docstring for
what a receipt is and, as importantly, what it is not a substitute for.

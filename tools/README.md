# `tools/`

Ten scripts. Nine Python, one Node (`check_mermaid_diagrams.mjs` — the
mermaid parser this repo needs isn't available in Python, so it stands alone
as the one non-Python tool here). Each carries a substantial module docstring
explaining *why* it exists; this file is the index that says *when to run it*
and *what actually calls it*, which the docstrings alone don't convey.

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
| `check_congestion_retarget_contract.py` (77 lines) | Operator-only, no receipt | Static source-contract check for one historical `ev_hosting_flex` stage retarget (Phase 14). Narrow and dated by design — re-run it if that stage's source changes, not on a schedule. |
| `render_hero_network.py` (206 lines) | Operator-only, no receipt | Regenerates the documentation homepage's hero image from the digital twin's real Trois-Rivières feeder. Run it after a change to the twin's geometry or styling; nothing else depends on its output being fresh. |

## Adding a new tool

Follow the pattern above, not the path of least resistance: decide which of
the three reach-classes it belongs to *before* writing it, because that
decision determines whether it needs a pytest wrapper, a `verification-
receipts.json` protocol entry, or neither. A tool that backs a claim in the
docs or in `CLAUDE.md` and has no CI/pytest coverage should almost always
gain a receipt — see `verification_receipt.py`'s own module docstring for
what a receipt is and, as importantly, what it is not a substitute for.

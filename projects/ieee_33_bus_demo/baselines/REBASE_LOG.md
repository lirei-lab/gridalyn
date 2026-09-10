# Re-base log — `ieee_33_bus_demo`

Every change to `results_baseline.json` is recorded here, newest last, with the
sha256 of the file **after** the change. `tests/test_baseline_rebase_declared.py`
recomputes that digest and fails when it does not match, so a pin cannot move
without somebody writing down what moved and why.

This log does **not** verify the new numbers are right — that needs the study's
outputs, which CI does not have. It removes the case where nobody notices at all
(bd qgr.6).

## 2026-09-10 — bootstrap, not a re-base

Adopting the ledger. This entry records the digest as the pins already stood; it
asserts nothing about how they got there. The commits that last moved them:

- `0a23fba9` 2026-08-28 — fix(regression): replace a baseline metric that could not fail
- `ab34d18e` 2026-08-04 — fix(ci): pin fixture metrics by physical significance, not solver precision
- `12852c88` 2026-08-04 — fix(ci): make the suite and the fixture pins survive a clean machine


sha256: 68c53bde9c179a9cac4f07a1ed7beab65e9e48777df05216145dbe51963242f1

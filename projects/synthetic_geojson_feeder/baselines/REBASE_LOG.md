# Re-base log — `synthetic_geojson_feeder`

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

- `ab34d18e` 2026-08-04 — fix(ci): pin fixture metrics by physical significance, not solver precision
- `12852c88` 2026-08-04 — fix(ci): make the suite and the fixture pins survive a clean machine
- `1512dfa7` 2026-06-11 — feat(simulation): per-building load overrides for synthetic networks


sha256: 7430079c62b8c0284a56085f4f48a377f1c45e8566c89c3ec575ff436d240ddc

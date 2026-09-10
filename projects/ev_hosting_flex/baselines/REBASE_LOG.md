# Re-base log — `ev_hosting_flex`

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

- `b249392d` 2026-09-07 — chore(ev_hosting_flex): re-base the three fleet pins on the third clean run, and record the attestation
- `2b8e979f` 2026-09-04 — chore(ev_hosting_flex): re-base the four nonwires pins on the second clean run
- `88c225f6` 2026-09-04 — chore(ev_hosting_flex): re-base 27 pins on the first coherent run, and record why they moved


sha256: 96019e2bf0e7bcac37a86d46975d189193ae3f5721eee3d1487a56d2ffbd2e42

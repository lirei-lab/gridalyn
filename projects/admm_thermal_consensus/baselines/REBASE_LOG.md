# Re-base log — `admm_thermal_consensus`

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

- `97e209ff` 2026-08-04 — docs: pin what can be pinned, withdraw what cannot be reproduced
- `45d68903` 2026-08-04 — fix(admm): Québec calibration + report the metric that actually discriminates
- `ef2754cf` 2026-08-03 — fix(projects): a baseline with no metrics must fail, not pass vacuously


sha256: 5f4c46aaf21ad5071b8b728659d3095c1b01b593442bdeb9fdb7b94b1f5f4fbf

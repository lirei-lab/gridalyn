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

## 2026-09-15 — topology re-base: capacity-limited partition, street siting, declared slack

42 of 94 pins moved, on one cold full run from committed code (25 stages, no
stage filter, manifest `completed`, `git_commit` 6de591bd, 19:02-22:26Z). The
rationale, the evidence for the 10-home limit and the measured limits are the
dated section in `CALIBRATION.md`; `bd 4os.7` and `bd 4os.14` carry the
measurements behind it.

What moved, by family: cluster 6, congestion 3, fleet 8, netchar 5, nonwires 4, perf 2, pf 6, phase 2, voltage 2, voltage_net 4. The hosting headlines did not: `annual.*`,
`cred.*`, `insurance.*`, `coldcoupling.*` and `flexincentive.*` are
value-identical, because the worked example is still a 6-home 71.25 kW unit.

The two numbers a reader should carry: network undervoltage risk at 1 EV/home
`voltage_net.p_undervolt_at_ref` 0.0 -> 0.11273, and the fleet screen
`fleet.n_at_risk_at_1ev_static` 500 -> 506.


sha256: 97a5947214083e403db07a8c06ccb619c41258416c8a8c4b96cc5370b0370ec3

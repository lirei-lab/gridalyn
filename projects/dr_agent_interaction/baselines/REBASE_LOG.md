# Re-base log — `dr_agent_interaction`

Every change to `results_baseline.json` is recorded here, newest last, with the
sha256 of the file **after** the change. `tests/test_baseline_rebase_declared.py`
recomputes that digest and fails when it does not match, so a pin cannot move
without somebody writing down what moved and why.

## 2026-09-11 — first baseline

The study is new (bd 4ky.9). The pins are the first run's summary on the
declared seeds (agents 11, channel 29) and the bernoulli_loss channel (loss
0.15, latency 1 min), produced by `gridalyn project run projects/dr_agent_interaction`.

sha256: 5988d4537e81bbcb4d0b5db11e621ad4a5b5163945eeb8f4aacb7bc1646e9e34

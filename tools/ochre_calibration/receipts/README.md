# EnergyPlus validation receipts

The published results of `tools/ochre_calibration/`, the external white-box
reference for the RC building model in `gridalyn/assets/datagen/agents/buildings.py`.

**Why these files are tracked when the harness is not.** The harness cannot run
in CI: its toolchain is roughly 1.6 GB and its dependencies pin numpy below this
repository's floor, so it runs out of process and `.ochre-calibration/` is
gitignored. That is right for a working tree and wrong for the evidence — while
the results lived only in an ignored directory, nobody outside one machine could
see that the validation had happened. These six files are a few kilobytes.
Regenerate them with `python tools/ochre_calibration/publish_receipts.py`; read
them in Python through `tools/ochre_calibration/receipts.py`, which returns the
error bound as the platform's own `ErrorBound` and so validates the file against
that contract.

`tests/test_ochre_receipts.py` asserts they stay present and self-consistent. It
is **not** a validation test — it is a test that the validation stays legible.

## The toolchain, pinned

From `feasibility_report.json`: EnergyPlus 24.x via OpenStudio `3.9.0+c77fbb9569`,
OpenStudio-HPXML `v1.9.1`, `ochre-nrel==0.9.2`, over real NRCan Québec H2K
archetypes at a pinned archetype-repo commit.

## What each receipt says

### `flexbound.json` — the citable flexibility result

The decision: pre-heat +1.5 °C over 13:00–16:00, curtail −2.0 °C over 16:00–19:00,
expressed relative to each household's own setpoint so the dispatch does not
erase the diversity it is measured against. Two EnergyPlus arms differing in
exactly that one thing.

| | dwellings | mean relief kW/home | rebound kW/home | net energy kWh/home | worst comfort drift |
|---|---|---|---|---|---|
| fit | 14 | 4.381 | 1.255 | −1.32 | −2.0 °C |
| **holdout** | **15** | **3.777** | 1.081 | −0.79 | **−2.0 °C** |

The holdout is disjoint from the fit. **3.777 kW/home of relief at a worst-case
comfort cost of 2.0 °C, on dwellings the decision was not fitted on** — this is
the number to quote, and the comfort cost belongs beside it.

### `rc_error_bound.json` — how far the RC model's promise sits from delivery

A *different, harsher* experiment: **full** heating curtailment 16:00–19:00 over
the coldest week, replayed identically on both models. Do not confuse it with the
bounded setback above.

| | |
|---|---|
| metric | `mae_curtailment_relief_kw_per_home` |
| value | **5.3 kW per dwelling** |
| promised (RC) | 3.137 kW/home |
| delivered (EnergyPlus) | 8.437 kW/home |
| sample | 15-dwelling holdout, disjoint from the 14 used to fit |
| worst comfort drift | −16.4 °C |

The scalar is *promised minus delivered*, so the RC model **understates** the
relief it will actually get — the conservative direction, but a large bound: the
model is conservative rather than accurate. The −16.4 °C drift is the physical
cost of *full* curtailment, and is why the shipped decision uses a bounded
setback instead.

**Explicit scope limit, quoted from the receipt itself:** it covers shifted
energy, rebound and thermal inertia. It does **not** cover instantaneous
coincidence — EnergyPlus steps >2 kW in 22.1 % of 15-minute intervals against
45.1 % measured — so `datasets/hq` is the arbiter for that axis, not this
reference. Partial power caps are out of scope.

### `hq_split_targets.json` / `scaling_validation.json` — coincidence

Coincidence factor by group size, on calibration and validation halves of the
dwelling pool. Measured against the metered arbiter (`datasets/hq`,
all-electric subset, n=215, 15-minute, window 2019-02-08…14):

| homes | EnergyPlus | HQ measured | relative |
|---|---|---|---|
| 2 | 0.821 | 0.840 | −2.2 % |
| 3 | 0.742 | 0.772 | −4.0 % |
| 6 | 0.656 | 0.677 | −3.2 % |
| 12 | 0.597 | 0.619 | −3.6 % |
| 18 | 0.572 | 0.604 | −5.3 % |
| 24 | 0.562 | 0.581 | −3.3 % |
| 32 | 0.549 | 0.578 | −5.0 % |

EnergyPlus tracks the metered curve within 2–5 % across the whole range, always
slightly low, consistent with it under-representing cycling. It is a
**corroborating second reference**, not the arbiter.

Read together with `docs/components/assets.md`, which sets out which model is
authoritative on which axis: the RC model for coincidence, cycling and
small-group peaks; EnergyPlus for annual energy, per-end-use split and envelope
response; `datasets/hq` when the two disagree.

### `fleet_summary.json`, `feasibility_report.json`

The 73-dwelling fleet with per-archetype annual kWh and the simulated window,
and the stage-by-stage feasibility gate with its environment and toolchain pins.

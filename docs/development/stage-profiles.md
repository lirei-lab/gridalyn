# Per-stage wall-time profiles

Where a governed study's time actually goes, read from its own run manifest.

`gridalyn/projects/runner.py` already records `started_at`, `ended_at` and
`exit_code` for every stage it runs, so a completed run carries its own
profile — no instrumentation, no second execution. `tools/stage_profile.py`
reads that record, joins it to the `needs:` edges in the study's
`workflow.yaml`, and reports what a concurrent runner could actually reach.

Regenerate with:

```bash
python tools/stage_profile.py --workers 4 --json docs/development/stage-profiles.json
```

`stage-profiles.json` alongside this file is that output, and is the machine
-readable record. The numbers below were measured on 2026-09-02 from the
manifests then on disk; they are wall times on one developer machine, not a
portable benchmark. What they are used for is *shape*, and shape survives the
machine.

## The measured picture

| Study | Stages timed | Sequential | Critical path | Real ceiling | Uniform-cost estimate |
|---|---|---|---|---|---|
| `admm_thermal_consensus` | 13/14 | 10m35s | 6m46s | **1.56x** | 2.00x |
| `rl_voltage_control_lightsim` | 5/5 | 1m19s | 1m16s | **1.04x** | 1.67x |
| `ieee_33_bus_demo` | 5/5 | 16.7s | 11.2s | **1.49x** | 1.25x |
| `prosumer_battery_market` | 5/5 | 15.0s | 11.7s | **1.28x** | 1.67x |
| `der_voltage_optimization` | 5/5 | 14.4s | 11.0s | **1.31x** | 1.67x |
| `synthetic_geojson_feeder` | 5/5 | 8.8s | 5.6s | **1.59x** | 1.25x |
| `minimal_grid_project` | 3/3 | 5.0s | 5.0s | **1.00x** | 1.00x |
| `ev_hosting_flex` | 23/23 † | 4.51 h | 1.78 h | **2.53x** | 3.29x |

† From two runs, read from the run log rather than a manifest — see
"The flagship, measured" below, including one stage whose cost was not
reproducible between them.

*Critical path* is the longest dependency chain weighted by measured time: the
wall time a perfect scheduler with unlimited workers would reach, and therefore
the ceiling on any concurrency the runner could add. *Uniform-cost estimate* is
`stages / waves` — what the DAG's shape alone suggests if every stage cost the
same.

## What the profiles say

**The DAG's shape does not predict the speedup, in either direction.** The
uniform-cost estimate is wrong for seven of the seven measured studies, and it
is not conservatively wrong: it *overstates* the reachable speedup for
`rl_voltage_control_lightsim` (1.67x estimated, 1.04x real) and *understates*
it for `synthetic_geojson_feeder` (1.25x estimated, 1.59x real). Any decision
about parallelising the runner that is argued from wave widths alone is
arguing from a number the measurements contradict.

**Every study's time is concentrated, not spread.** In each case one or two
stages hold the run:

- `admm_thermal_consensus` — `uncertainty_sweep` 61.9% + `imputer_comparison`
  28.5% = **90.4%** in two stages of fourteen.
- `rl_voltage_control_lightsim` — `train_rl_voltage_agent` **90.0%**.
- `prosumer_battery_market` — `run_realtime_prosumer_market` 49.4%.
- `minimal_grid_project` — `run_minimal_powerflow` 83.6%.

**Concentration does not by itself rule concurrency out.** `admm`'s two
dominant stages are mutually independent — both declare
`needs: [run_admm, build_network]` — so running them together removes the
smaller one from the wall clock entirely: 1.56x on a study that is 90%
concentrated. Conversely `rl_voltage_control_lightsim` is equally concentrated
but in a *single* stage, so concurrency buys 4%. The distinction that matters
is not "concentrated vs spread" but **whether the dominant stages are
independent of each other**.

## What these profiles cannot tell you

**Six of the seven are seconds long.** `minimal_grid_project` through
`rl_voltage_control_lightsim` run 5–79 s. Only `admm_thermal_consensus` (10m35s)
is even within two orders of magnitude of the flagship's ~6 hours, and it is the
one that most resembles it in kind: a heavy study, with heavy stages, sharing the
Québec calibration. A pattern that holds across the fast six is a prior about
this repository's stage-cost distribution, not a proof about a workload a
thousand times larger.

**Concentration alone does not select the remedy, and reading it that way
inverts the answer.** It is tempting to read "every study is concentrated" as
"therefore the work belongs inside the heavy stage". The measurements say
otherwise, and `admm_thermal_consensus` is the case that shows it: 90.4%
concentrated *and* 1.56x from wave parallelism alone, because its two dominant
stages are siblings. The pair of questions that actually decides is:

1. How much of the run sits in the dominant stages?
2. **Are those dominant stages independent of each other?**

A study concentrated in one stage (`rl_voltage_control_lightsim`, 90.0%, 1.04x)
and a study concentrated in two independent stages (`admm_thermal_consensus`,
90.4%, 1.56x) carry the same answer to the first question and opposite answers
overall. Only the second question separates them.

The flagship has since answered both, and it answers them differently from every
fast study: its four dominant stages span three different waves, so two of them
overlap and two do not. See "The flagship, measured".

## The flagship, measured

A full cold run on 2026-09-03 (01:19–05:38 UTC) executed 20 of the 23 stages and
then failed in stage 21; a recovery run (11:38–15:36) completed the remaining
three plus their dependencies. Together they give the first complete per-stage
profile of `ev_hosting_flex`.

**The profile is not in a manifest.** The failing run's manifest was overwritten
by the recovery run's, which records 13 stages behind a `stage_filter`. The
20-stage timings survive only in the run log, because the runner writes the
manifest once, in its `finally` block, rather than per stage. `stage_profile.py`
reads manifests and so cannot produce this profile today; the figures below were
read from the log.

| Stage | Wave | Time | Share |
|---|---|---|---|
| `analyze_nonwires_value` | 4 | 76.3 min | 28.2% |
| `analyze_credibility` | 5 | 51.6 min | 19.1% |
| `analyze_cold_insurance` | 6 | 50.2 min | 18.6% |
| `analyze_fleet_triage` | 4 | 40.7 min | 15.1% |
| `analyze_voltage_risk_network` | 3 | 18.0 min | 6.7% |
| `analyze_locational_contracts` | 5 | 8.5 min | 3.2% |
| `analyze_clustered_adoption` | 3 | 6.9 min | 2.5% |
| `validate_powerflow` | 5 | 6.6 min | 2.4% |
| `generate_annual_mc` | 2 | 5.2 min | 1.9% |
| *(the other 14 stages)* | | < 3 min each | 1.3% |

**Four stages hold 81% of the run.** The remaining nineteen hold 19% between
them.

### What it says about parallelising the runner

```text
sequential                        4.51 h
wave-barrier schedule, 2 workers  3.36 h    1.34x
wave-barrier schedule, 10 workers 3.36 h    1.34x
true DAG schedule, unlimited      1.78 h    2.53x
```

Three results, and the second and third are the ones that should change the
design.

**The worker cap is not the constraint.** Two workers reach exactly what ten
reach. Every wave is dominated by a single stage, so capacity beyond the second
worker has nothing to do. This substantially defuses the oversubscription hazard
— the runner never needs to run ten stages at once, and a cap of 2–3 costs
nothing against a cap of 10.

**The wave barrier is the constraint.** A scheduler that runs each wave
concurrently and waits for it to drain reaches 1.34x. One that starts each stage
as soon as its own declared dependencies are satisfied reaches 2.53x — nearly
double, on identical hardware and identical stage costs. The whole difference is
stages waiting on a barrier rather than on their actual `needs:`. A wave-barrier
implementation would deliver about a third of the available gain and look like it
had succeeded.

**The dominant stages are only partly independent.** `analyze_nonwires_value`
and `analyze_fleet_triage` are both in wave 4 and mutually independent, so
concurrency removes the smaller from the clock: 40.8 minutes saved, the single
largest win available. But `analyze_credibility` (wave 5) and
`analyze_cold_insurance` (wave 6) sit on the critical path one after the other,
and no amount of concurrency touches them. That is why the ceiling is 2.53x
rather than the 3.29x the DAG's shape suggests.

### One stage's cost is not reproducible between runs

`analyze_congestion_risk` measured **24.5s** in the full run and **4612.8s** in
the recovery run four hours later — a factor of 188, on the same machine and the
same commit. Every other stage measured in both runs agreed within 11%.

The cause was not investigated. The plausible one is caching: the full run met
artifacts accreted from months of partial runs, while the recovery run met
artifacts its own upstream stages had just regenerated. Whichever way round it
is, it means a single run's profile is not automatically a stable description of
the workload, and the table above should be read with that caveat on that row.
Taking the larger figure instead moves the sequential total to 5.78 h and the
ceiling to 2.19x; it does not change any conclusion above, because the
wave-barrier result stays at 1.33x and the barrier remains the binding
constraint.

## The annual Monte-Carlo is not the bottleneck

`generate_annual_mc` is treated as the flagship's hours-long stage —
`tools/flagship_verify.py` names it in `HEAVY_STAGES` and skips it by default,
describing it as "the hours-long heavy stage (the annual Monte-Carlo base)".

Measured directly on 2026-09-02, by timing the stage's kernels in-process:

| Work | Count | Each | Total |
|---|---|---|---|
| `annual_base_realization` (base) | 1 | 69.5s | 69.5s |
| `annual_base_realization` (forecast, per `FC_SIGMAS`) | 4 | 65.1s | ~4m20s |
| `ev_fleet_annual` | 1 | 0.13s | 0.13s |
| `load_annual_tmy` | 1 | 0.04s | 0.04s |
| | | | **330.1s ≈ 5m30s** |

**Superseded by a direct measurement of the stage itself.** On 2026-09-03 a full
cold run of the workflow recorded:

```text
[4/23] generate_annual_mc completed in 311.1s
```

**311.1s (5m11s) — 1.44% of a six-hour run.** The in-process estimate above is
**6.1% high** (330.1s against 311.1s), and the two must not be cited
interchangeably: one times the kernels with warm imports inside an
already-running interpreter, the other is the stage as the runner executes it,
subprocess spawn and all.

The direction of the gap is what is worth recording, because the obvious
explanation does not fit. A real stage additionally pays interpreter start,
imports, cache reads, `np.save` and report writing — all of which should push it
*above* a kernel-only figure, not below. Nor does the cold first call explain it:
the first in-process realization ran 69.5s against a warm 65.1s, so dropping it
accounts for ~4.4s of ~19s, about a quarter. The remainder is that each pipeline
realization runs at 62.2s against the warm in-process 65.1s — roughly 4% faster
across the whole series. Plausible causes not checked: a fresh interpreter doing
only this work, differing BLAS/OMP defaults between an interactive process and a
runner-spawned subprocess, or warmer page cache after stages 1–3. None was
chased; at 1.44% of the run it does not pay.

**The transferable finding is the shape, not the number:** an in-process timing
of a stage ran ~6% slow against the stage itself, and only a quarter of that was
the cold start. Worth knowing the next time an in-process measurement is used to
decide whether to build something — here it erred in the safe direction.

The "K = 1000 Monte-Carlo draws" figure that this belief rests on refers to
`K` in `projects/ev_hosting_flex/scripts/config.py`, which that constant's own
docstring marks **RETIRED** (Phase 15 RETIRE-02, D-13) and which no pipeline
stage reads. The count the stage actually loops over is `K_ANNUAL`, and
`K_ANNUAL = 1` — the study-B faithful default, since within-year day-to-day
variation is the sampling axis. `annual_mc_report.json` records `k_annual: 1`.
The stage's five realizations are one base plus one per forecast sigma.

Two consequences worth carrying forward:

1. There is no Monte-Carlo ensemble inside this stage to parallelise. The loop
   `for r in range(int(K_ANNUAL))` runs once.
2. The loop that *does* exist there — the four forecast sigmas — draws its
   per-day offsets **sequentially from one pinned generator**
   (`fc_rng = np.random.default_rng(SEED_FC_OFFSETS)`, the study-B draw order,
   D-B3). Splitting that loop across workers changes the draw order and so the
   results. Only the `SEED + r` base realizations are addressed by index and
   safe to divide.

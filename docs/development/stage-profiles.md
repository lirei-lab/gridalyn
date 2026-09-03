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
| `ev_hosting_flex` | **2/23** | — | — | **not measured** | 3.29x |

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

For the flagship, neither question is answered yet: wave 3 holds ten stages, and
whether the hours sit in one of them or spread across them is exactly what the
missing profile would say.

## The flagship is not profiled

`ev_hosting_flex` records 2 of its 23 stages, because the manifest on disk came
from a partial `--stage` run (its `stage_filter` names the two). No per-stage
profile of the ~6-hour run exists, and none can be produced without a full run.
The tool reports this rather than presenting the two-stage total as a profile.

One component of it *was* measured directly, in-process, without a runner
invocation — see "the annual Monte-Carlo is not the bottleneck" below.

## Two manifest defects the profiles exposed

**A partial run overwrites a full run's record.** The flagship's manifest is
honest that it was filtered — it carries
`stage_filter: ["prepare_topology_cache", "prepare_workspace"]` — but it
replaced whatever record the full run left. The filter field is what makes the
partial run detectable at all.

**`stage_filter: null` does not mean the record is current.**
`admm_thermal_consensus` records 13 stages with no filter and
`status: completed`, yet its workflow declares 14. The run (2026-08-18 23:10
UTC) predates the commit that added `export_twin_network_model` to that
workflow (`11dde791`, 2026-08-20 00:37 UTC). The manifest is a faithful record
of a workflow that has since changed. A reader therefore cannot conclude "full
run" from the absence of a filter; the recorded stage ids have to be compared
against the workflow as it stood at the manifest's `git_commit`.
`tools/stage_profile.py` reports this as `STALE MANIFEST` and marks the derived
figures a lower bound.

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
| | | | **≈ 5m40s** |

Roughly **1.6% of a six-hour run**, not the bulk of it.

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

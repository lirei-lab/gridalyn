# `flexibility_cls` Authoring-Path Audit (REPRO-02)

**Audited:** 2026-06-15
**Scope:** Pin the code path that authored the committed `results_baseline.json`
golden master, so the upcoming consolidation merges (Phases 2-5) cannot silently
re-route the study through a different clearing/settlement implementation without
the regression gate noticing.

This is a documented audit with reproduction evidence — not a re-investigation.
Every claim below was verified by reading the cited source at the cited line and
by re-running `gridalyn project regression projects/flexibility_cls` (green,
74/74, zero committed-number change).

---

## 1. The committed baseline was authored through the flexibility facade

Stages 02 and 03 call the **flexibility facade**, never the market OO engine
directly:

- `02_solve_capacity_allocation.py` →
  `from gridalyn.operations import run_cls_capacity_allocation`
- `03_stage2_realization_replay.py` →
  `from gridalyn.operations import prepare_cls_market_replay_context`

As of Phase 4 the study imports these symbols **only** through the top-level
`gridalyn.operations` facade (the canonical surface); no study script reaches
into `gridalyn.operations.flexibility` / `gridalyn.operations.market` or any
concept submodule. The `tests/test_study_facade_boundaries.py` (D-04) guard
locks this facade-only rule for all study code.

The descriptions below trace what the facade does **internally** — plumbing that
is **interior to the facade, not study-facing**.

> **UPDATE (2026-07-17):** the consolidation completed. The legacy
> `gridalyn/operations/flexibility/` and `gridalyn/operations/market/` packages
> (described below as "quiet deprecation shims" pending Phase-5 deletion)
> **no longer exist** — `gridalyn/operations/` now holds `clearing/`,
> `settlement.py`, `contracts.py`, `constraints.py`, `replay.py`, `runs.py` and
> friends. The line-number citations below refer to the deleted
> `cls_market.py` and are kept only as a historical record of what the facade
> replaced; do not treat them as navigable paths. `BuildingAggregator`, for
> example, now lives in `gridalyn/operations/clearing/engine_mode.py`. The
> facade-only rule and its guard (`tests/test_study_facade_boundaries.py`)
> remain in force.

Historical record — in the (now deleted) `cls_market.py`:

- `:17` `from gridalyn.operations.market.dso_dispatch import DSODispatcher`
- `:18` `from gridalyn.operations.market.engine import MarketSimulationEngine`
- `:80,85` `dispatcher = DSODispatcher(..., hard_cls_price=hard_cls_price)`
- `:87` `market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)`

**Conclusion:** authoring path = study stage script → flexibility facade
(`cls_market` / `cls_replay`) → `DSODispatcher` + `MarketSimulationEngine`. The
two security-relevant headline quantities are produced here into two **distinct**
files: the 95% security **envelope** into `outputs/json/ev_summary_results.json`
(Stage 02) and the per-realization out-of-sample **E_omega** distribution into
`outputs/json/stage2_realization_summary.json` (Stage 03). The golden master pins
them as two never-interchangeable metric groups (D-04).

---

## 2. The `hard_cls_price` flexibility-vs-market default divergence is LATENT, not active

The study supplies `hard_cls_price` explicitly from config:

- `projects/flexibility_cls/scripts/config.py:43` →
  `PAPER_CONFIG["market"]["hard_cls_price"] = 10.0`
- `:93` → `HARD_CLS_PRICE = PAPER_CONFIG["market"]["hard_cls_price"]`
- threaded into both stages (`02_...py:75`, `03_...py:91`:
  `hard_cls_price=HARD_CLS_PRICE`).

The in-engine default is the **same value**:

- `gridalyn/operations/market/dso_dispatch.py:40` →
  `hard_cls_price: float = 10.0`
- `gridalyn/operations/flexibility/cls_market.py:48` →
  `hard_cls_price: float = 10.0`

Because the study passes `10.0` explicitly and the engine default is also `10.0`,
the documented flexibility-vs-market default divergence (CONCERNS.md
"flexibility_cls economic magic numbers") **does not affect any committed
number** — it is latent, not active, for the committed baseline. A future merge
that removes the explicit pass-through would still reproduce today's numbers only
*so long as* the engine default stays `10.0`; the new `stage02.*` and
`*.Eomega.*` baseline rows are the tripwire if either side ever changes.

---

## 3. Weather is pinned (not `source="auto"`)

The study loads a **committed** PVGIS TMY, not a network download with a silent
synthetic fallback:

- `projects/flexibility_cls/scripts/weather_input.py:17` →
  `TMY_INPUT_PATH = .../inputs/tmy_trois_rivieres.csv`
- `:18` → `TMY_SOURCE = "pvgis_sarah3 (pinned project input)"`
- `:21-28` → `load_project_tmy()` reads the committed CSV; the module docstring
  explicitly warns against replacing it with `download_tmy()` (whose silent
  synthetic fallback would change the study day).

The committed PVGIS study weather is pinned per commit `6f93a40`. **Caveat
(carry-forward from CONCERNS.md "Weather reproducibility footgun"):** the source
pin holds only because every stage routes weather through `load_project_tmy()`;
any new caller that reaches for `download_tmy(..., source="auto")` re-introduces
the nondeterminism. No code change is required this phase — this is recorded so
the pin is not silently lost during consolidation.

---

## 4. RNG discipline (REPRO-01 context)

The CLS pipeline uses **per-instance** generators, never a project-wide global
seed:

- `projects/flexibility_cls/scripts/config.py:90` → `SEED = 42`
- `00_generate_stochastic_profiles.py:85,126` →
  `np.random.default_rng(SEED + r)` per Monte-Carlo realization; downstream
  datagen agents (`make_buildings`/`make_ev_chargers`/`simulate_buildings`)
  thread the same `SEED + r` discipline.

The only global `np.random.seed` in the tree lives in
`gridalyn/twin/geoprocess/generator.py` inside `FakeGeoJSONGenerator`, which draws
**only** from the stdlib `random` module — the line is dead code and is **not on
the CLS path**. Its removal (REPRO-01, plan 01-02) cannot change any committed CLS
number; this audit records the finding so the dead-code removal is not
re-litigated as a reseed/rebaseline.

---

## 5. Reproduction evidence

- `uv run python projects/flexibility_cls/scripts/verify_regression.py` →
  `"valid": true`, 74/74 metrics, exit 0.
- `gridalyn project regression projects/flexibility_cls` →
  `returncode 0`, `"valid": true`, 74/74.
- The 18 pre-existing committed numbers are unchanged; the widening is additive
  (56 new stage-boundary stat/hash + E_omega rows). Verified by re-running the
  full pipeline on this machine (stages 00→03) and diffing the boundary arrays:
  max same-machine abs-diff `0.0` for all six D-02 arrays.

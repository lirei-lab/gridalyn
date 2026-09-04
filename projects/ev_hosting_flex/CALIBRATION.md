# Québec load calibration — `ev_hosting_flex`

Reference for the two sizing knobs that set how soon EVs congest the feeder:
`TRANSFORMER_UTILIZATION_MARGIN` and the LV diversity / coincidence assumption.
It records the Québec-relevant evidence so the calibration is **traceable**, and
corrects an earlier over-statement (that `diversity = 1` was "pessimistic, real
1.5–2.5" — the evidence shows it is actually defensible for this load type).

## Current headline figures

**Read this table and the one after it before quoting anything else in this
file.** Both are checked by `tools/check_calibration_claims.py` at the precision
shown — headline figures against `baselines/results_baseline.json`, knobs against
`project.yaml`'s `spec.inputs.studyConfig` — so a figure in either cannot survive
a change that moved its source.

The rest of this document is a **chronological record** (decided 2026-09-02).
Sections carry the numbers that were current when they were written, and a
re-base appends rather than revising them — so an older section may state a
figure these two tables supersede. When they disagree, these tables win.

That structure has one obligation, and it is the one this file has twice failed:
**a section whose code is retired must say so at its top.** A stale number in a
dated section is a legitimate record; a section written in the present tense
about machinery that no longer exists is not a record of anything, because it
never was true of the tree a reader is looking at. Two such sections are
bannered below — Cold-load pickup (retired Phase 15) and Recommended values
(adopted in `10-03`). The re-base procedure in
`docs/contributing/verification.md` carries the rule.

| Figure | Current value | Baseline pin |
|---|---|---|
| Firm hosting capacity | 11 EVs | `annual.firm_ev_count` |
| Flexible hosting capacity | 16 EVs | `annual.flexible_ev_count` |
| Hosting expansion | 0.4545 | `annual.hosting_expansion_percent` |
| Firm hosting, P05 | 10.0 EVs | `cred.firm_p05` |
| Firm hosting, P50 | 11.0 EVs | `cred.firm_p50` |
| Firm hosting, P95 | 12.55 EVs | `cred.firm_p95` |
| Flexible hosting, P50 | 16.0 EVs | `cred.flex_p50` |
| Base peak, P50 | 65.76 kW | `cred.base_peak_p50` |
| Congested hours at pool top | 19.5 h/yr | `annual.congested_hours_at_pool_top` |
| Economic break-even | 6 EVs | `annual.econ_breakeven_ev_count` |
| Naive-model firm overestimate | 45.45 % | `coldcoupling.firm_overestimate_percent` |
| Insurance crossover adoption | 11 EVs | `insurance.crossover_adoption` |
| Expected flexibility cost at reference | 480.05 $ | `insurance.expected_cost_flex_at_ref` |
| Short years if planning at P50 | 0.24 | `insurance.short_years_if_plan_p50` |
| corr(winter severity, firm) | 0.36 | `insurance.delta_firm_correlation` |
| Fleet: transformers in the fleet | 540 | `fleet.n_transformers` |
| Fleet at risk at 1 EV/home, static rating | 500 | `fleet.n_at_risk_at_1ev_static` |
| Fleet deferred by flexibility at 1 EV/home, static | 73 | `fleet.flex_defers_at_1ev_static` |
| Fleet needing steel at 1 EV/home, static | 1 | `fleet.needs_steel_at_1ev_static` |
| Fleet base-constrained at 1 EV/home, static | 426 | `fleet.base_constrained_at_1ev_static` |
| Fleet deferred fraction of at-risk, static | 0.146 | `fleet.deferred_fraction_at_1ev_static` |
| Fleet at risk at 1 EV/home, hourly rating | 186 | `fleet.n_at_risk_at_1ev_hourly_kt` |
| Fleet deferred by flexibility at 1 EV/home, hourly | 182 | `fleet.flex_defers_at_1ev_hourly_kt` |
| Fleet needing steel at 1 EV/home, hourly | 4 | `fleet.needs_steel_at_1ev_hourly_kt` |
| Fleet base-constrained at 1 EV/home, hourly | 0 | `fleet.base_constrained_at_1ev_hourly_kt` |
| Fleet deferred fraction of at-risk, hourly | 0.978495 | `fleet.deferred_fraction_at_1ev_hourly_kt` |

**The fleet rows are the study's declared primary result** — `project.yaml`
calls `fleet_triage` "the study's primary result; the per-feeder stages below
are the worked example behind it" — and until 2026-09-04 they were the only
substantive figures in the study with no pin. They are pinned under **both**
rating conventions, not only the declared headline (`static`), because the two
disagree by 6.7x on the deferred fraction and pinning one would re-hide that
one commit after it was made visible. **They carry no `uncertainty` block, on
purpose, and the reason is specific.** Two sampling axes sit under these
counts. The **allocation** axis — which homes get the EVs, at clustered
dispersion 0.7 — is characterised and independent: across 200 allocation
seeds with the per-size limits held fixed, `flex_defers` has sd ≈ 1.9 (95 %
[68, 76] around the pinned 73) and `n_at_risk` sd ≈ 1.9 ([495, 502] around
500); the single-draw spread is 2.6× the 6-draw spread against √6 = 2.45, so
the averaged draws scale as independent samples (measured 2026-09-04,
`syntgrid-eei.3`). The **base-MC** axis — the `triageKBase` = 3 realizations
behind those limits, shared by every transformer of equal home count — is
*uncharacterised and non-independent by construction*, and it is the binding
one. Two different reasons: one axis is quotable, the other is not. An
interval is carried where it can be defended and is absent rather than faked
where it cannot; the honest interval here would have to include the axis
nobody has measured. Two consequences for a reader: `needs_steel` = 1 is a
pinned value, not a finding — its allocation range is [0, 2], so "1 of 540
needs reinforcement" is equally consistent with 0 and with 2; and raising
`triageKBase` is a deliberate re-base to be recorded here, not a free change —
since 7f8cbb03 the shared base-MC cache already holds six realizations, so its
generation cost is paid, but it buys exactly the unmeasured axis, and measuring
`per_size_limits` across base seeds first would say whether six is enough.

## Current knob values

The same rule, against the other source of truth. Headline figures are pinned in
`baselines/results_baseline.json`; the sizing **knobs** are declared in
`project.yaml` under `spec.inputs.studyConfig`, which is what `scripts/config.py`
reads. `tools/check_calibration_claims.py` checks this table against that block,
so a recalibration cannot leave a knob stated here that the study no longer uses.

| Knob | Current value | Declared in |
|---|---|---|
| Per-EV charger nameplate | 7.2 kW | `evUnitKw` |
| EV coincident fraction | 0.35 | `diversityFactor` |
| EV coincident draw per EV | 2.52 kW | `evUnitKw` x `diversityFactor` |
| Transformer utilization margin | 0.8 | `transformerUtilizationMargin` |
| EV coincidence mixing weight | 0.5 | `evCoincidenceRho` |
| Per-home thermal resistance | 7.0 | `rQuebec` |
| Fleet triage base realizations | 3 | `triageKBase` |

Sequence-valued knobs are deliberately **not** restated here — `evSweep` and
`chargingWindow` are declared in the same `studyConfig` block and should be read
from it. A restated sequence is precisely what went stale: the sweep ran
`(0, 20, …, 200)` in the text long after the study had moved to a step of 2 up
to 52.

## Evidence status — verified (adversarial votes)

Gathered with the deep-research harness (5 angles, 19 sources). The adversarial
verification pass **ran** (3-vote panel per claim).

**Superseded on this point, 2026-08-04.** As written (2026-06-23) this section
said no Québec metered per-house kW was found, and the *literature review*
still stands on that footing: no published HQ sizing rule and no IEEE C57.91
threshold were found directly, so the figures below remain inferences from HQ
consumer docs plus cold-climate literature (German/Belgian sources are
directional, not transferable). But the study is no longer validated only
against literature — `datasets/hq` supplies **metered** Hydro-Québec
consumption, and the RC building model is checked against its all-electric
subset (n = 215, 15-minute) with the residual bias disclosed. See the latching
thermostat entry below and `docs/components/assets.md`. A reader who stops here
gets the opposite of the truth, in the direction that understates the work.

**Confirmed:**
- **[3-0]** HQ: cold-day heating reaches **~80 % of household electricity**; coincident
  winter peak **~10–15 kW/dwelling**. L2 EV 7.2 kW → **~1.4 kW diversified** at 40
  connections (coincidence ~0.44 at 50 EVs), rising on small feeders.
- **[2-1]** Resistance heating is **high-coincidence**: CF **~0.85** (⇒ diversity
  factor ~1.18); instantaneous thermostat diversity ~0.5; winter CLPU ~2.2 p.u.

**Refuted:**
- **[0-3]** "Heating is *perfectly* coincident / near-zero diversity" → there **is**
  diversity (CF ~0.85), so `diversity = 1` is the **conservative edge**, not the centre.
- **[0-3]** "EV per-connection is *comparable* to electric heating" → the EV is clearly
  **secondary** to heat — this **validates the study's thesis**.

**Verified summary:** *defensible LV diversity factor **1.0–1.5**, transformer
utilization **~80 % with CLPU headroom**, per-dwelling winter peak **~10–15 kW**, EV
diversified **~1.4 kW** (higher on small/cold feeders).*

## Findings

### 1. Heating diversity / coincidence (the profile's `diversity = 1`)

| Source | Finding |
|---|---|
| LBNL — Hong, *Heating-load diversity in residential districts* | Space-heating-dominated districts: peak-load reduction from diversity is **≤ ~15 %** → coincidence ≈ 0.85, **diversity factor ≈ 1.0–1.18**. Climate-driven peaks line up at the same time step. |
| PES-PSRC report 075 (cold-load pickup) | Electric resistance heaters carry a **~0.5** *thermostatic* diversity in normal operation (≈50 % drawing at any instant), rising toward 1.0 after an outage (CLPU, +110 %). This is *instantaneous sub-hourly* coincidence, distinct from the hourly envelope. |
| arxiv 1810.05734; IEEE 4113138 | Measured feeder CLPU demand ratios **1.28–3.31×** normal diversified peak; saturated electric-heat CLPU can reach **3×** rated transformer current at −40 °C. |

**Reading:** at the **hourly** resolution this study uses, all-electric space heating is
genuinely **highly coincident** → `diversity ≈ 1` is defensible (at most ~10–18 %
conservative). The 1.5–2.5 range belongs to *instantaneous* thermostat cycling or
*mixed* loads, not the hourly heating envelope. The mis-set knob is the **topology**
`diversity_factor_lv = 5` (mixed-urban value), already bypassed by the stage-2 resize.

### 2. Per-dwelling winter peak

| Source | Finding |
|---|---|
| PMC/NCBI PMC11534675 (Québec all-electric dwelling) | A two-storey single-family Québec home (~60 m²) has **~13 kW** installed baseboard (plinthe) heating, room heaters 1–2 kW. |
| `gridalyn/assets/datagen/agents/buildings.py` (project calibration) | ~6 kW heat at −25 °C + ~1.5 kW background; ~20–22 MWh/yr; ~5500 HDD18 (Trois-Rivières). |
| ResearchGate 257227221 (12 Canadian houses) | **Gas-heated** dataset — *not* representative of Québec all-electric; do not use for this study. |

**Reading:** realistic diversified winter peak **~10–15 kW/dwelling** (13 kW baseboard +
DHW/appliances). The model's **17.64 kW** is at the **high end** — plausible but could be
trimmed via `WINTER_PEAK_FACTOR`.

### 3. EV charging as a secondary load

| Source | Finding |
|---|---|
| arxiv 2409.18105 | On a 40-connection LV feeder the **diversified** per-unit peak contribution is heat-pump 1.2 kW, EV **1.4 kW**, fast EV (>6.5 kW) **2.0 kW** — far below the ~7.2 kW nameplate. A fast EV adds *more* than a heat pump. |
| ResearchGate 390753742 | EV coincidence **<25 %** for >50 EVs, but **higher for the few dwellings on one transformer**, and **rises with cold ambient + lower charge power**. Uncontrolled EV ~**halves** the hosting of small 25/50 kVA transformers. |

**Reading:** EV diversified contribution **~1.4–2.0 kW** on large feeders, higher on a
small cold-climate feeder. The model's **4.32 kW** (`7.2 × 0.6`) is at the high end —
conservative but reasonable for 26 cold-climate homes.

### 4. Transformer utilization margin / IEEE C57.91

| Source | Finding |
|---|---|
| Hydro-Québec Blue Book (E.21-10) | Customer service-connection standard — **does not** specify transformer margins or diversity factors. (HQ does not publish these here.) |
| IEEE C57.91-2011 | Custom (non-nameplate) ratings from design + ambient; **cold ambient raises capacity**, so winter peaks can be carried **at/above nameplate**. |

**Reading (corrected after verification):** a **0.8** utilization margin (sizing to 80 %
of base peak) is **the defensible Québec value**, not something to raise — distribution
transformers are sized to ~80 % with the remaining headroom reserved for the brief
1.3–3× winter CLPU transients. An earlier draft suggested raising it to ~0.9–1.0; the
verified evidence says **keep `TRANSFORMER_UTILIZATION_MARGIN = 0.8`.**

### 5. EV charging behavior (Canadian validation)

EV behavior of the study's `_profiles.py` model (fixed `CHARGING_WINDOW = (17, 22)`,
flat `EV_UNIT_KW × DIVERSITY_FACTOR = 4.32 kW`, seasonless) vs Canadian data:

| Source | Finding | Model consistency |
|---|---|---|
| Jonas, Daniels & Macht, *Energies* 2023, **16(4):1592** (>7000 CA stations) | Residential charging peaks **15:00–24:00** ("EV duck curve"); session energy **6–13 kWh**; plugged **~11 h** but **drawing only ~2 h** | ✅ evening peak (17–22 ⊂ 15–24); ⚠️ model's flat 5 h ⇒ **21.6 kWh/EV/day** is ~2× high; ⚠️ ignores the 11 h plug-in / latent flexibility |
| **Charge the North** (Geotab/FleetCarma, >1000 CA drivers) | Winter **total** energy ≈ summer (cold raises kWh/km but driving drops) | ✅ **seasonless is validated** for Canada |
| arxiv 2409.18105 | EV diversified peak **~1.4 kW** (40 conn.), L2 7.2 kW nameplate | ⚠️ model's 4.32 kW is **high** (small/cold feeder raises it) |

**Reading.** Behaviorally consistent in the grid-critical dimensions (evening-peaked L2,
seasonless total energy — both Canadian-validated; EV secondary to heat — verified). Two
quantitative biases: (a) **per-EV energy ~2× high** (flat 5 h vs ~2 h active, 21.6 vs
6–13 kWh) inflates the `curtailed_energy_fraction` **denominator** → biases the headline
**optimistic**; (b) **EV coincident power high** (4.32 vs ~1.4 kW) → **pessimistic** on the
peak. They partly offset, but both should move toward the Canadian values.

## Power-limited multi-session availability (Phase 10.3)

The flexible leg was re-baselined from the 10.1 in-window valley-fill **deferral**
mechanism to **power-limited natural charging** (V1G smart-charging) over multiple
daily availability sessions (D-08 goal amendment; ROADMAP lineage). This subsection
records the model, the windows, the scenarios, the unserved-energy gate, and — the
honest, genuinely-load-bearing record — the **weak** midday-headroom margin.

### Model

Per hour the aggregate EV draw is throttled to the available headroom and the charger
ceiling:

```
delivered[h] = min(remaining_requirement, charger_kw, max(0, rating − base[h]))
```

walked in **clock order** from arrival across the day's sessions; energy undelivered in
one session **carries forward** (per-day **carry-forward**) to that day's next
chronological session. Energy still undelivered after the day's **last** session is the
**unserved energy**. There is no valley-fill / `argsort` relocation: charging is throttled
in place and what does not fit this hour simply waits for the next chronological plug-in
hour. `charger_kw=inf` (the `min(natural aggregate draw, max(0, rating − base))`
natural-draw cap, RESEARCH Open-Q1 / Assumption A1) — at the
aggregate level the natural draw is the ceiling and the headroom binds first; no separate
aggregate charger limit is imposed. The model runs at **aggregate** (feeder-transformer
downstream-sum) granularity, reusing the existing TMY heating-degree base unchanged (no
new daytime-occupancy term — byte-stability).

The over-limit/headroom decision reuses the strict-`>` `is_congested` convention (no
second epsilon): an hour whose base sits exactly at the rating has zero headroom and
hosts no charging.

### Windows & scenarios

- **`WORKPLACE_WINDOW = [9-16]`** — the same-day daytime workplace plug-in window (does
  not wrap midnight). Rationale: many EVs are plugged in at the workplace during the day,
  adding lower-loaded midday hours to complete the charge.
- **`AVAILABILITY_SCENARIOS`** (three, emitted side-by-side):
  - `overnight` — the 18→07 home-only baseline session.
  - `workplace` — overnight home **+** the daytime `[9-16]` window — **the citable
    HEADLINE**.
  - `all_day` — full 24 h availability, the hosting **ceiling**.

### Unserved-energy gate

`TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95 = 0.01` — the unserved-energy fraction
(energy undelivered at throttled power across all available session-hours, ÷ annual EV
demand) must be **strict-`<` 1% at P95** for a swept point to pass. This is a NEW aliased
constant reusing the value `0.01`; it does not edit the dormant deferral gate
`TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95`.

### Re-derived hosting (modeled 71.25 kW / 7-home idx-62 unit, K=1000, P95)

| Scenario | flexible EVs | hosting_expansion | unserved P95 @ flexible |
|---|---|---|---|
| firm (read denominator) | 3 | — | — |
| `overnight` | **34** | +10.33 | 0.0088 |
| `workplace` (HEADLINE) | **35** | +10.67 | 0.0020 |
| `all_day` (ceiling) | **35** | +10.67 | 0.0019 |

(The 10.1 spike's indicative 5/6/14 counts were on the older 50 kVA/6-home unit and the
deferral mechanism; the pipeline **re-derives** these under power-limiting on the
re-calibrated 71.25 kW/7-home unit.) Both runs are **byte-stable** (identical
`availability_curve_content_sha256`).

### The midday-headroom premise is WEAK (honest framing)

The premise that daytime `[9-16]` headroom exceeds overnight headroom holds only
**marginally** on this cold-climate TMY (RESEARCH Pitfall 1, verified against the
committed TMY):

| Window | Mean cold-day headroom |
|---|---|
| workplace `[9-16]` | **~33.6 kW** (33.57) |
| overnight `[18-23, 0-7]` | **~32.0 kW** (31.95) |

Workplace exceeds overnight by only **~1.6 kW (+~5%)** — the cold snaps are sustained day
and night (average cold-day diurnal swing ~9.4 °C; even the warmest midday hour is
~−16 °C). **The lift comes from the extra ~8 available HOURS, not richer midday
headroom; `all_day` is the ceiling.** Daytime availability does **not** unlock dramatic
capacity — this is recorded honestly so a future TMY re-copy re-checks the premise
(`test_midday_headroom_premise`).

### Penetration sweep extension (append-only)

Under power-limited charging the per-hour headroom (~27-34 kW) vastly exceeds the
aggregate EV draw until very high penetration, so the overnight unserved-energy P95 stays
below the 1% gate across the entire frozen `PENETRATION_SWEEP` (0→2.0) — a flat-zero
saturation that would pin the flexible count uninformatively at the sweep top (Pitfall 2).
The overnight cliff crosses 1% near **~4.6 EV/home**, so an **append-only**
`EXTENDED_PENETRATION_SWEEP` (0→5.0 at the same 0.1 step) was added **below** the frozen
block; the single re-point site is the sweep loop in `apply_flexibility_contracts.py`. The
frozen `PENETRATION_SWEEP` and the golden config bytes are never mutated.

## Partial EV coincidence (diversity) — `EV_COINCIDENCE_RHO` (260625-lgg)

The governed pipeline originally built EV demand everywhere as ONE per-EV-unit
realization shape scaled by the EV count (`ev_unit * count`) — i.e. **every EV
charging with the same shape at the same time**, an implicit model **coincidence
factor CF ≈ 1** (full coincidence). That is the source of the over-conservative
`firm_ev_count = 3`: the governed firm implicitly assumed near-FULL EV
coincidence, which the literature does **not** support for ~7 dwellings.

**Literature basis.** Jonas, Daniels & Macht, *Energies* 2023, **16(4):1592**
(>7000 CA stations; residential charging peaks 15:00–24:00; EV coincidence
**< 0.25 for >50 EVs**) and the **[EV-3]** coincidence row above (§3/§5:
coincidence is **HIGHER for the few dwellings on one transformer**, and **RISES
with cold ambient + lower charge power**) place the citable coincidence factor for
**7 cold-Québec all-electric homes** at **CF ≈ 0.55–0.7** — partial, not full,
coincidence. Prototype 260625-lf4 confirmed CF ≈ 0.55 lands at the diversified end
of this small-feeder model.

**Mechanism.** A new `EV_COINCIDENCE_RHO = ρ` knob (config.py, append-only) blends
the legacy coincident shape with an INDEPENDENT diversified shape at every EV
count: `aggregate(count) = ρ·count·ev_unit + (1−ρ)·independent_aggregate(count)`,
where `independent_aggregate(count)` is `count` INDEPENDENTLY-drawn per-EV days
summed (the same pinned `_ev_day` draw order, byte-stable per-count via
`SeedSequence([SEED, count])`). `ρ = 1` reproduces the legacy full-coincidence path
bit-for-bit; `ρ = 0` is fully independent. The blend is wired through the four
headline-driving EV-demand consume sites (firm gate, the two flexibility-sweep
legs, and the two-stage annual headline / activated-fraction); the two-stage
cold-day **oracle ensemble** (`compose_scenarios`) already draws independently and
is left unchanged.

**Chosen value and resulting CF.** On the governed 71.25 kW / 7-home idx-62 unit
(`OMP_NUM_THREADS=1`, K=1000, non-worktree re-run, 260625-lgg) the value is
calibrated against the **frozen** governed gates (FIRM_PCONG_TOLERANCE strict-<,
etc. — never relaxed):

| ρ | model CF (6-EV aggregate) | firm_ev_count |
|---|---|---|
| 1.0 (legacy) | ≈ 1.0 | 2–3 (over-conservative) |
| 0.4 | ≈ 0.65 | 7 (firm above band) |
| **0.5 (chosen)** | **≈ 0.71** | **6** |
| 0.6 | ≈ 0.76 (CF above cited 0.7) | 5 |

**`EV_COINCIDENCE_RHO = 0.5`** is the unique value satisfying BOTH the cited CF
band (CF ≈ 0.71, at the 0.7 ceiling) AND the firm **[5, 6]** target band (firm 6)
on this feeder. A lower ρ over-diversifies the governed feeder (firm 7–9); a higher
ρ pushes CF above the cited 0.7 ceiling.

**Citable-headline re-base (deliberate).** Recalibrating to literature-grounded
partial coincidence **deliberately re-bases the study's citable hosting headlines**
off the new firm:

| Headline | Was (CF ≈ 1) | Now (CF ≈ 0.71, ρ = 0.5) |
|---|---|---|
| `firm_ev_count` | 3 | **6** (+100%) |
| flexible — overnight | 34 | **35** (+483% vs firm 6) |
| flexible — **workplace (HEADLINE)** | 35 | **35** (+483%) |
| flexible — all_day (ceiling) | 35 | **35** (+483%) |
| curtailment | — | **8** (+33%) |
| two-stage OPTIMAL (ε=0.05) | 6 (+100%) | **11** (+83.3%) |

The two-stage cvxpy solve still matches the closed-form oracle exactly
(`cvxpy_oracle_drift = 0.0 ≤ 1e-6`, `cvxpy_fellback = false`, status `optimal`).
All re-run digests are byte-stable across two consecutive runs (D-05/D-13).
**No committed Phase-12 regression baseline exists yet** (Phase 12 not done), so
**no baseline is broken** — only the phase outputs shift, deliberately, onto the
literature-defensible partial-coincidence model.

## Cold-load pickup (CLPU) base uplift — `CLPU_PEAK` (260625-pwz)

> **RETIRED — Phase 15 (RETIRE-02, D-13). Historical record; nothing below is
> live.** The four knobs this section chooses (`CLPU_PEAK`, `CLPU_TEMP_ONSET`,
> `CLPU_TEMP_FULL`, `CLPU_WINDOW`) were **physically deleted from
> `scripts/config.py`**, together with their sole consumer
> `_stochastic.clpu_factor` and the annual `tmy_base` that applied it; the
> re-anchored `_twostage.compose_scenarios` applies no CLPU lift, because the
> base is now the emitted `Q_design` building mean. The determinism guard
> described below is gone with them: `PRE_CLPU_BASE_*_SHA256` /
> `PRE_CLPU_REQUIRED_SHA256` and the file that asserted them,
> `tests/test_ev_hosting_flex_stochastic.py`, no longer exist. `config.py`
> carries the deletion tombstone at the point the block used to be.
>
> Kept rather than deleted because the *evidence* is still citable — the
> hourly-averaged evening CLPU bump of ~1.3–1.5 against the sub-hourly
> post-outage ~2.2 p.u. is a literature finding, not an implementation detail —
> and because the headline table below records a real re-base the study passed
> through. Read every present-tense sentence from here to the next `##` as past
> tense. For what the study uses now, see **Current knob values** at the top.

The governed base `_stochastic.tmy_base` was a **static grades-day heating
envelope that never spikes**: the coldest-evening 7-home feeder base reached only
**~62 %** of the 71.25 kW rating (43.94 / 71.25; the config-derived ADMD figure is
~64 %, 45.5 / 71.25), so EV scenarios barely congested and (under the
literature-grounded partial coincidence `EV_COINCIDENCE_RHO = 0.5`) `firm_ev_count`
sat at an unrealistically high **6**. **Cold-load pickup** — thermostats recovering
from daytime setback together on cold evenings — lifts the cold-evening base to the
**~80 % design point** the 75 kVA transformer is sized for, making congestion
genuine. This ports the validated manuscript prototype
(`manuscripts/ev_hosting_flex/scripts/figures/_clpu.py`, quick 260625-pul) into the
GOVERNED pipeline (the manuscript figures already included CLPU; the governed base
did not).

### Mechanism

On cold evenings occupants return home and thermostats recover from daytime setback
~simultaneously: the **hourly** heating coincidence jumps from its normal
thermostatic diversity (~0.5 — about half the baseboards drawing at any instant)
toward ~1.0 (all on), briefly lifting the aggregate heating peak. The factor is
applied to the **HEATING term only** (`max(0, T_BALANCE − temp) / R_THERM`) in BOTH
`_stochastic.tmy_base` (the annual base) and `_twostage.compose_scenarios` (the
two-stage cold-day ensemble, reconstructed from the same heating form). The
occupancy-shaped `BG_KW` background and the EV layer are **never** amplified.

### Chosen knobs (`config.py`, append-only)

| Knob | Value | Meaning |
|---|---|---|
| `CLPU_PEAK` | **1.40** | Hourly-averaged evening setback-recovery bump on the heating term |
| `CLPU_TEMP_ONSET` | **−8 °C** | CLPU begins below this (factor 1.0 above) |
| `CLPU_TEMP_FULL` | **−22 °C** | Full synchronization at/below this (strength clips at 1) |
| `CLPU_WINDOW` | **{16: 0.55, 17: 1.00, 18: 0.75, 19: 0.45}** | Evening recovery decay weights by hour-of-day (fraction of full `CLPU_PEAK`) |

### Citable basis

- **CALIBRATION.md [2-1]** (above): winter CLPU **~2.2 p.u.** — but that is the
  **sub-hourly / post-outage** diversity-loss extreme (thermostatic diversity ~0.5
  rising toward 1.0 after a diversity-loss event). The **hourly** evening bump is
  **~1.3–1.5**.
- **PES-PSRC report 075**: resistance heaters ~50 % drawing in normal operation,
  rising toward 100 % after a diversity-loss event.
- **Validated prototype** (quick 260625-pul): firm 5→2, base ~62 %→81 %.

**Calibration framing.** `CLPU_PEAK = 1.40` lands the coldest-evening feeder base at
the **~80 % design point** the 75 kVA / 71.25 kW unit is sized for, up from the
pre-CLPU ~62 % (config-derived ~64 %, 45.5 / 71.25). It is **NOT 2.0** (which pushes
the base **alone** above the rating → firm 0, congesting with zero EVs, unphysical
for an HQ-sized unit) and **NOT 1.0** (the static envelope, firm an unrealistically
high 6). At 1.40 the base sits near the design peak so **EVs remain the congestion
trigger**.

**Honest caveat.** 1.40 is the **hourly-averaged** evening bump. The sub-hourly
post-outage CLPU (~2.2 p.u.) is stronger and is **intentionally NOT** used at the
hourly resolution of this study.

### Determinism guard

`clpu_factor(hod, temp)` is a **pure function of (hour-of-day, temperature) only —
no RNG, no global state**, so byte-stability is trivial. The hard guard is
**`CLPU_PEAK = 1.0` reproduces the pre-CLPU base AND the two-stage `required`
ensemble bit-for-bit** — and this is only meaningful because the pre-CLPU
`content_sha256` of both was **captured on the unmodified tree BEFORE any edit** and
**pinned as the literal** the guard test asserts against (`PRE_CLPU_BASE_*_SHA256`
/ `PRE_CLPU_REQUIRED_SHA256` in `tests/test_ev_hosting_flex_stochastic.py`),
otherwise the comparison would reduce to the `x·1.0 == x` tautology. Both governed
re-run digests (base, two-stage required + headline) are byte-stable across two
consecutive non-worktree runs.

### Before/after headline re-base (deliberate; modeled 71.25 kW / 7-home idx-62 unit, K=1000, P95)

| Headline | Pre-CLPU (CF ≈ 0.71, ρ = 0.5) | Now (CLPU_PEAK = 1.40) |
|---|---|---|
| coldest-evening feeder base / rating | **~62 %** (43.94 / 71.25) | **~81 %** (57.89 / 71.25) |
| per-home design-cold peak | ~6.28 kW | **~8.27 kW** |
| `firm_ev_count` | 6 | **3** (firm drops as the base lifts) |
| curtailment flexible | 8 (+33 %) | **7** (+133 % vs firm 3) |
| flexible — overnight | 35 | **35** (+1066.7 %) |
| flexible — **workplace (HEADLINE)** | 35 | **35** (+1066.7 %) |
| flexible — all_day (ceiling) | 35 | **35** (+1066.7 %) |
| two-stage OPTIMAL (ε = 0.05) | 11 (+83.3 %) | **10** (+233.3 %) |

The two-stage cvxpy solve still matches the closed-form oracle exactly
(`cvxpy_oracle_drift = 0.0 ≤ 1e-6`, `cvxpy_fellback = false`, status `optimal`).
The hosting-expansion **percentages rise** because the firm denominator dropped
(6 → 3) even though the absolute flexible counts are similar — the study's headline
is now keyed off the realistic cold-evening congestion the static envelope missed.

**Deliberate citable-headline re-base.** This is the **third** deliberate re-base
(after the TMY/stochastic Phase 10.1 and the `EV_COINCIDENCE_RHO` 260625-lgg
re-base). **No committed Phase-12 regression baseline exists yet** (Phase 12 not
done), so **no baseline is broken** — only the phase outputs move, deliberately,
onto the literature-defensible CLPU cold-evening base.

## Recommended values (Québec / Canada-defensible, verified) — ADOPTED in 10-03

> **Historical record of a recommendation that was carried out.** The
> "Was" column below is the state this review found on 2026-06-23; the "Became"
> column is what `10-03` set, and every one of those values is now gated at the
> top of this file under **Current knob values** (or, for the sequence-valued
> ones, declared in `project.yaml`'s `spec.inputs.studyConfig`). This table
> previously carried the pre-adoption numbers in a column headed *Current* with
> an *Action* column telling a reader to perform work already done — a reader
> saw a model over-stated by ~71 % on EV coincident power and ~186 % on session
> energy. Past tense is what stops that recurring: an adopted recommendation
> cannot go stale, whereas a standing one can.

| Knob | Was (2026-06-23) | Defensible band | Became (10-03) |
|---|---|---|---|
| `TRANSFORMER_UTILIZATION_MARGIN` | `0.8` | **0.8** ✅ verified | **unchanged** — 80 % + headroom is the standard |
| Profile diversity | `1` (fully coincident) | **1.0–1.5** (centre ~1.15) | **kept ≈1** — conservative edge, defensible |
| `WINTER_PEAK_FACTOR` → per-home peak | 17.64 kW | **10–15 kW** | **~13.2 kW** (factor 1.6 → 1.2), mid-band |
| `EV_UNIT_KW × DIVERSITY_FACTOR` (coincident) | 4.32 kW | ~1.4 kW (↑ small/cold feeders) | **2.52 kW** (diversity 0.6 → 0.35) |
| EV daily energy (window shape) | 21.6 kWh (flat 5 h) | **6–13 kWh** (~2 h active) | **7.56 kWh** (window (17,22) → (17,20)) |
| Topology `diversity_factor_lv` | `5` | **~1.2–1.5** | inconsistent for all-electric; the load-aware resize bypasses it |
| `EV_SWEEP` | `(0,20,…,200)` = 0–769 % adoption | ≤ ~2 EV/dwelling (≤ ~52) + finer step | **step 2 to 52** (27 points) |

**Headline takeaway.** That the feeder hosts **~1 EV/dwelling firm** before congesting is a
**real, verified** result for a Québec all-electric feeder: EV charging (~1.4 kW diversified)
is *secondary* to electric heat (~10–15 kW). It is **not** a sizing error and the **0.8
margin is correct**. The refinements this review called for — trim the per-home peak,
lower EV power and energy toward the Canadian values, cap and refine `EV_SWEEP` — were
all applied in `10-03`; `WINTER_PEAK_FACTOR` itself was later superseded outright by the
TMY heating-degree base (D-14), which is why `config.py` marks it deprecated.

## Generative-MC design-day seam (Phase 13)

The v1.3 milestone replaces the project-local degree-day annual base with a
**generative design-day Monte-Carlo seam** (`scripts/_generators.py`, GEN-01..04):
the **SDK building agent** (`make_buildings` / `simulate_buildings`,
`gridalyn.assets.datagen.agents`) — used exactly as the SDK exposes it —
recalibrated to the Québec all-electric archetype, plus the **project-local MDPI EV
sampler** (kept `_stochastic._session` / the `_ev_day` draw order), run over the
**binding cold design day** to emit the idx-62 transformer-load ensemble
`Q_real (K, n_steps)` + the day-ahead forecast `Q_design`. The operating point below
is **empirically locked** (2026-06-26 throwaway probes `exp_firmsweep.py` /
`exp_genseam.py`); Phase 13 implements it byte-stably — it does **not** re-discover it.

### SDK building agent ADOPTED (GEN-02)

The SDK building agent replaces the project-local degree-day `tmy_base`. Its default
calibration (`R_MEAN ≈ 11` °C/kW, `P_HEAT_MAX_KW ≤ 8` kW) **under-loads** the 7-home
idx-62 unit to ~6.5 kW/home / ~60 % of the 71.25 kW rating. The **locked
recalibration** overrides per `Building`:

- `R = 7.0` °C/kW (`config.R_QUEBEC`)
- `p_heat_max = 13.0` kW (`config.P_HEAT_QUEBEC`)

**Anchors:** PMC/NCBI PMC11534675 Québec all-electric baseboard dwelling ~13 kW
installed baseboard; HQ 10–15 kW/dwelling (§2 of this doc). At `R = 7.0` / baseboard
13 the design-day EV-free feeder base lands at **~8.4 kW/home coincident / ~82–87 %
of the 71.25 kW rating, firm = 3** (empirically verified at K=60 on the 1990-01-19
design day; reproduced in the governed kernel at p50=82 % / p90=87 % / ~8.3 kW/home,
pinned by `tests/test_ev_hosting_flex_generators.py`).

**NO CLPU.** The heating recalibration is the dominant lever; CLPU *on top* of it
overshoots to ~117 % / firm = 0 (congesting with zero EVs, unphysical for an HQ-sized
unit) — so the Phase-10.3 `clpu_factor` is **dropped from the generative path**.
`simulate_buildings` uses `ParametricArxGenerator` ONLY for the small non-HVAC
**background** channel (which carries the morning/evening human-activity peaks; the
feeder peaks ~18:00); the **heating** is each `Building`'s RC baseboard
(winter-peaking), so the prior ARX-as-base rejection (quick 260625-ox4) does **not**
apply here.

### MDPI EV truth (GEN-03)

EV truth = the **project-local MDPI sampler** calibrated to **Jonas, Daniels & Macht,
*Energies* 2023, 16(4):1592** (Canada, >7000 stations): charger mix
`{7.2:0.75, 9.6:0.20, 11.5:0.05}` kW, lognormal session energy (median 8 kWh, σ 0.5,
floor 1 kWh), arrival `N(18, 1.5)` clipped to `(16, 22)`, plug-in probability 0.65.
The per-EV **pinned draw order** (`rng.random` plug-in → `rng.choice` charger mix →
`rng.lognormal` energy → `rng.normal` arrival) is the byte-stability contract. EV
draws are **nested/cumulative** (`ev_nested_pool`): row *n* is the aggregate hourly
draw for the first *n* EVs, so `P(overload)` is **monotonic in EV count** (adding an
EV never removes load). The pool is drawn once per realization on a seed independent
of the building seed and **exposed** alongside `Q_real` for the Phase-14 firm sweep
(it is not summed into the `Q_real` building-base headline). The generic SDK EV
session model is **not** adopted as truth; the SDK `EVCharger` **actuator** pattern
(`dynamic_p_cap_kw` / `cls_active`) is reserved for the Phase-15 curtailment cap.

### Design-day MC + forecast (GEN-01 / GEN-04)

The binding cold day is selected via `select_peak_load_day` over the committed
Trois-Rivières TMY (`config.TMY_INPUT_PATH`), empirically **1990-01-19** (occupied
HDH proxy, −20.1 °C mean). `K` Monte-Carlo realizations (default `K_DESIGN = 60`),
each re-seeding the SDK building agent and a smoothed day-ahead
temperature-forecast-error offset from `SEED + r`, aggregate to
`Q_real (K, n_steps)` at `DESIGN_DAY_RES_MINUTES = 60` (hourly → 24 steps; the
building hourly aggregate worked in the probes). This is a **design-day generative
statement**, not an annual 8760 h integrated risk (the latter is FUT-07).

`Q_design` is the **day-ahead forecast** (`make_q_design`): a gaussian-smoothed macro
shape of `Q_real`'s per-step mean plus a single temperature-forecast-error term
(`config.SIGMA_DAILY` / `SIGMA_HOURLY`). It is strictly a **smoothing / forecast of
`Q_real`'s predictable part** (corr ≥ 0.9, max deviation < 15 % of the mean peak) —
**never** an independent load model (GEN-04).

**Determinism (GEN-01, feeds SEAL-01).** A single seeded RNG from `config.SEED`
covers the SDK building seed AND the MDPI EV draws; pinned draw order; float64
throughout; round-before-write (`config.ROUND_DECIMALS`, callers round). Two calls
with the same seed return byte-identical `Q_real` / `Q_design` / `ev_pool`. **No
silent SDK fallback:** the building agent + `select_peak_load_day` are imported
deferred in the governed path and the kernel **raises** (`ImportError`) if a required
SDK symbol is missing — it never substitutes a hand-rolled base
(`test_no_silent_sdk_fallback_in_source`, `test_select_design_day_raises_when_sdk_unavailable`).

## RETIRE-02 framing change — energy gates → reliability-only (Phase 15, D-14)

**Dated: 2026-06-26.** Phase 15 (CTRL + RETIRE-02) re-points the flexibility stage
from the energy-fraction-gated availability sweep to the two-stage day-ahead
controller and records the following framing changes (D-14):

- **(a) Energy → reliability-only acceptability.** The retired stage gated a swept
  EV count on an **energy-fraction** tolerance (`TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX`
  / `TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95` / `TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95`,
  all strict-`<` 1%). Phase 15 **removes the energy gate from the acceptability
  decision**: energy (reserve `Σr`, expected activation `E[Σa]`) is **reported, never
  gated**. The acceptability criterion is now **realized reliability alone** — the
  largest adoption with **realized `P(transformer overload after activation) ≤ ε`**
  (`ε = EPS_HEADLINE = 0.05`) on a fresh out-of-sample `Q_real` ensemble (D-12). The
  superseded energy-gate knobs are bannered/deleted per RETIRE-02 (D-13).

- **(b) SDK building adoption / recalibration.** The base building load is now the
  **SDK building agent** (`make_buildings`/`simulate_buildings`) recalibrated to the
  Québec all-electric archetype: per-home thermal envelope **`R_QUEBEC = 7.0` °C/kW**
  and baseboard capacity **`P_HEAT_QUEBEC = 13.0` kW** (overriding the SDK defaults
  `R_MEAN ≈ 11` / `P_HEAT_MAX = 8.0`, which under-load the 7-home idx-62 unit). This
  lands the EV-free design-day base at **~82–87 % of the 71.25 kW rating, firm = 3**
  (empirically locked at K = 60 on the 1990-01-19 design day). **No CLPU** — the
  heating recalibration is the dominant lever; CLPU on top overshoots to ~117 % /
  firm 0 (the CLPU base-uplift knobs are deleted this phase).

- **(c) MDPI EV provenance.** The EV **truth** is the project-local MDPI sampler
  (charger mix, lognormal session energy, Gaussian evening arrivals, plug-in
  probability), grounded in **Jonas, Daniels & Macht, *Energies* 2023, 16(4):1592**
  (Canada, >7000 charging stations): residential charging peaks 15:00–24:00. The SDK
  `EVCharger` **session model is NOT adopted as truth**; only its cap-actuator
  *pattern* (`dynamic_p_cap_kw`/`cls_active`) is ported, applied to the MDPI aggregate.

- **(d) Transformer-overload framing.** Acceptability is keyed on the **transformer**
  overload probability, not the prior congestion-line proxy: `loading = (Σ building +
  Σ EV) / rating`, **overload = loading > 1 strict** (the Phase-14 single binding-state
  kernel, rating = `TRANSFORMER_KVA · POWER_FACTOR` = 71.25 kW). Realized
  `P(overload)` is the mean over the K/N design-day realizations of any step
  overloading — the citable risk statement is a **design-day `P(overload)` + risk
  distribution**, not an annual integrated risk (the latter is FUT-07).

- **(e) ROADMAP #4 vs CONTEXT D-12 divergence (explicit).** ROADMAP Phase-15 success
  criterion #4 reads `flexible_ev_count` requires realized reliability ≤ ε **AND
  contract cost below break-even**. **CONTEXT D-12 (later, authoritative) overrides
  this**: in Phase 15 `flexible_ev_count` is gated on **realized reliability ALONE**;
  the **contract-cost / break-even gate is deferred to Phase 16** (economics ledger).
  The controller emits the `Σr` / `E[Σa]` reserve/activation totals so Phase 16
  applies the cost gate **without re-running** the controller. CONTEXT supersedes
  ROADMAP per GSD upstream-input precedence; the headline shift (firm 3 → flexible,
  +%) is reported explicitly with this rationale.

## Realistic residential base — DHW tank + R re-base (2026-07-14)

The 4th deliberate re-base. An audit found the base **peak-calibrated but
energy-inflated**: `R_STUDY_B = 5.0` hit the HQ winter peak (11.4 kW/home) with
the bare RC envelope but inflated annual energy to **38.9 MWh/home** (~1.8× the
SDK-native 20–22; QC all-electric typical 25–30).

**Frontier evidence (no single R hits both):** the single-R RC model couples peak
and energy (ratio fixed by climate); sweeping R, energy lands in band (25–30) only
at R≈8–9 where the peak is 7.5–8.1 kW (below the 10–15 band), and the peak lands in
band only at R≈5–6 where energy is 34–39 MWh.

| R | MWh/home | peak kW/home |
|---|---|---|
| 5.0 | 38.9 | 11.4 (peak ✓, energy ✗) |
| 8.0 | 28.8 | 8.1 (energy ✓, peak ✗) |
| 11.0 (SDK native) | 24.1 | 6.6 |

**Mechanism (physical):** QC all-electric homes peak higher for the same energy
because of the **electric water-heater tank** — a ~4.5 kW element recovering after
occupancy-clustered morning/evening draws — which the model had smoothed into the
~1.5 kW ARX background. `dhw_tank_annual` (project-local, no SDK edit) models it as
a single-node thermostatic tank (270 L, 4.5 kW, setpoint 60 °C, standby loss,
seasonal 10–15 °C inlet, stochastic draws phase-anchored to the local evening via
`hod0`); `BG_SCALE = 0.6` removes the double-counted DHW from the background. The
base becomes `Σp_heat + Σp_cool + BG_SCALE·Σp_bg + DHW`.

**Final knobs (calibrate_base.py):** `R_STUDY_B = 7.5`, `DHW_ELEMENT_KW = 4.5`
(standard QC), `DHW_DAILY_L_MEAN = 180`, `BG_SCALE = 0.6`.

**Result — realistic in BOTH:** peak **11.2 kW/home** (centre of HQ 10–15, p99
daily-peak 10.2), energy **29.4 MWh/home**, split **63/14/24 %** heat/DHW/appliance
(textbook QC all-electric). The peak is **preserved** vs the old R=5 (11.4 kW) so
the congestion/voltage diagnostics survive; the energy is corrected (39→29 MWh) so
the curtailment-energy denominator is now realistic, and the base is **peaky, not
sustained** (high at recovery hours, lower otherwise).

**Deliberate headline re-base** (every pin re-pinned, byte-stable): firm 2 → 4,
flexible +200 %, curtailed 6.1 → 2.7 %, breakeven 5 → 6; cold-coupling naive 5 vs
cold 4 (+25 %); substation 2×33.3 → 2×25 MVA (66/540 over static at 0 EV, 0 over
dynamic); flex-incentive shift ≥ target in every bin (no crossover); voltage-net
first-risk 1.70 → 1.53 EV/home; VUF 1.75 → 1.63 %.

## Pilar-2 non-wires value — cost anchors (2026-07-14)

The network reinforcement-deferral stage (`analyze_nonwires_value`) uses
literature-illustrative cost anchors (like the pilar-1 WTA): the physical crossings
A₀/A₁ are the robust result, the $ are illustrative.

- **`TRAFO_CAPEX_PER_KVA = 107` $/kVA** — INSTALLED reinforcement (transformer +
  labor + outage), reconciled with pilar-1's `CAPEX_UPGRADE = 8000` / 75 kVA ≈ 107.
  The raw transformer hardware (~$20–40/kVA) is too low — at that level the
  annualized reinforcement is cheaper than the flex contract everywhere and the
  flex defers nothing (a calibration artifact, not a finding).
- **`SUBSTATION_CAPEX_PER_MVA = 25000` $/MVA** — substation reinforcement (~$15–30k/MVA).
- **Adoption ramp:** logistic S-curve 0 → 2 EV/home over 15 years (midpoint 7,
  steepness 0.7) — ONE scenario; the per-adoption snapshot is ramp-shape-robust.
- **`NONWIRES_CURTAIL_TOLERANCE = 0.10`** — the reliability side of A₁ (max EV-energy
  fraction curtailed before flex is unacceptable).

Result on the realistic DHW base: **$72 k NPV + 286 transformer-years deferred**
network-wide, DOMINATED by the substation deferral ($47 k, 66 %). Base-driven feeder
overloads (the all-electric base alone exceeds the rating — flexibility cannot defer
them) are honestly excluded, and per-size deferral is floored at 0 (a value-negative
flex contract is declined in favour of reinforcement).

## Credibility layer — headline confidence intervals (2026-07-15)

`analyze_credibility` re-runs the firm/flex/breakeven chain over **K=50** realizations
varying the building seed, the EV-fleet seed, and a synthetic **winter-severity**
temperature anomaly (`WEATHER_SIGMA_C = 1.5` °C, `δ₀=0`). **Caveat:** a single committed
TMY → the weather axis is a synthetic winter-severity proxy (uniform per-day offset),
NOT measured inter-annual weather years.

Result on the realistic DHW base (realization 0 reproduces the governed firm/flex/
breakeven exactly — a consistency anchor):

| Headline | Governed (nominal) | P5 | P50 | P95 | robustness |
|---|---|---|---|---|---|
| firm | 4 | 2 | 3 | 4 | **weather-sensitive** (P(=4)=0.32; a colder winter → 2–3) |
| flex | 12 | 12 | 12 | 12 | robust (P(=12)=1.0) |
| breakeven | 6 | 5 | 6 | 6 | robust (P(=6)=0.70) |

The citable `firm=4` is the nominal-weather value; under winter-severity uncertainty it
is **[2, 4] with median 3** — an honest CI a reader should cite alongside the point.

## DHW smooth-occupancy realism fix (2026-07-16, 5th re-base)

A visual validation of the substation aggregate revealed a **near-vertical evening
ramp** — an unphysical coincident step for a 3235-home aggregate. Serious
verification (continuous 3-day decomposition) isolated the cause: NOT the heating
(0.64 kW/home/h, smooth) but the **DHW tank** (5.85 kW/home/h). The old
`DHW_DRAW_WEIGHTS` was a **sparse dict with zeros** (no hot water at 9–11h, 13–16h,
overnight; a 0→0.10 jump at 17h) **identical across homes** → a coincident on/off
that does not diversify away.

**Fix:** (1) a continuous **`dhw_draw_profile()`** occupancy curve (all-day baseline +
smooth morning/evening Gaussians, no zero hours) replaces the sparse dict; (2)
**per-home tank diversity** — setpoint (±2 °C), deadband (±1.5 °C), element (±0.5 kW),
tank volume (±30 L) jittered inside the per-home loop so reheats stagger.
**Validation:** the hourly coincident step drops **70 %** (1.14 → 0.35 kW/home/h) and
the near-vertical ramp is gone (see `profiles_transformer_substation.png`); the DHW
daily energy is preserved (~11.8 kWh/home). The residual morning/evening coincidence
is physical (real hot-water use clusters, like heating CF~0.85).

**Re-calibration:** the diversified DHW lowers the coincident peak, so the P99
typical-cold-day peak drops to ~9.8 kW (the annual coincident peak stays 11.1 kW, in
the HQ 10–15 band; energy 29.7 MWh; split 62/14/24 %). No knob change — the lower P99
is the honest diversification effect, not a defect. **Headline re-base:** firm 4 → 5,
netchar `n_over_static_at_0ev` 66 → 0 (the base is now healthy before EVs — the
base-driven overload was partly the DHW coincident peak), nonwires
first-reinforcement-year 0 → 4.36, NPV $72k → $97k, credibility firm P50 3 → 4 [3, 5].

## DHW tank validated against CREST (2026-07-17)

The DHW tank was cross-checked against the **CREST demand model** lineage via
[demod](https://github.com/epfl-herus/demod) (EPFL HERUS, GPL-3.0), whose thermal
module ports CREST's hot-water cylinder. Parameters extracted from
`demod/datasets/Germany/parsed_data/v0.1/heating/_heating_system_dict.json` and the
CREST loader; `cyl_loss` confirmed to be in **W/K** with the same equation form as
ours (`loss = UA·(T_tank − T_interior)`), so the comparison is direct.

| Tank | V (L) | UA (W/K) | UA/V^⅔ | standby kWh/day | element | T_set | deadband |
|---|---|---|---|---|---|---|---|
| **gridalyn (ours)** | 270 | 2.5 | **0.0598** | 2.40 | 4.5 kW | 60 °C | 7 K |
| CREST ElectricWaterHeater | 50 | 0.5 | 0.0368 | 0.36 | 2.0 kW | ~50 | 5 K |
| CREST boiler cylinder | 125 | 1.5 | **0.0600** | 1.08 | — | ~50 | 5 K |

**Findings:**
1. **Model structure is identical** — 1R1C thermostatic tank, `C = V·cp` (cp 4200 vs
   our 4186), `loss = UA·ΔT`. demod also randomizes the per-household cylinder
   temperature, independently corroborating the per-home diversity we added.
2. **Our UA is CORRECT, not high.** Normalized by surface area (∝ V^⅔, since our tank
   is 2–5× larger), we land at **0.0598 vs CREST's 0.0600 — an exact match** with the
   boiler cylinder. (An earlier internal review flagged UA=2.5 W/K as "high"; that
   flag is retracted — it compared raw UA across different tank sizes.)
3. **Remaining differences are geographic and correct for North America:** 270 L
   (NA 60-gal standard) vs 50–125 L (European); 4.5 kW element (NA standard) vs
   2 kW (European immersion); 60 °C setpoint (NA Legionella code) vs CREST's 42–55 °C
   distribution.

Together with the HQ-real validation (diurnal shape + aggregate smoothness), the
building generator is now validated on three axes: **shape**, **smoothness**, and
**DHW tank physics**.

## Cold-tail insurance study — knobs and headline (2026-07-28)

`analyze_cold_insurance` prices flexibility as insurance against the cold tail of
the hosting-capacity distribution. It reuses the **credibility seeds verbatim**
(`CREDIBILITY_K`, `WEATHER_SIGMA_C`, `CREDIBILITY_WEATHER_SALT`,
`CREDIBILITY_EV_SALT`) so both studies report one firm distribution — enforced by
`test_governed_firm_distribution_matches_credibility`.

**Knobs:** `INSURANCE_ADOPTION_GRID` = 1..12 EVs on the 6-home feeder,
`INSURANCE_RELIABILITY_TARGET = 0.95` (BOTH strategies must cover ≥95 % of years;
they are compared on cost), `INSURANCE_REF_ADOPTION = 6` (1 EV/home).
Costs reuse the illustrative `C_AVAIL_EV_YR = 80`, `C_A_CURTAIL = 0.5` and
`TRAFO_CAPEX_PER_KVA = 107`.

**Part 1 — capacity is a distribution:** firm = {2:1, 3:10, 4:20, 5:18, 6:1} over
K=50, P5/P50/P95 = 3/4/5. Planning at the P50 leaves the feeder short **22 %** of
years; at the P5, 2 %. `corr(winter severity, firm) = +0.42` — the spread is
weather, not sampling noise.

**Part 2 — insurance vs reinforcement at equal reliability:**

| target adoption | P(short) | coverage | flex $/yr | of which unserved | mean curtailed | reinforce $/yr | kVA |
|---|---|---|---|---|---|---|---|
| 1–3 | ≤0.02 | 1.00 | 80–241 | ≤$0.20 | 0.0 % | 0 (present unit) | 75 |
| 4 | 0.22 | 1.00 | 324 | $0.58 | 0.1 % | 696 | 100 |
| **6 (ref)** | **0.98** | **1.00** | **503** | **$3.77** | **0.2 %** | **696** | 100 |
| 8 (crossover) | 1.00 | 1.00 | 717 | $12.86 | 0.6 % | 696 | 100 |
| 12 | 1.00 | 1.00 | 1340 | $63.29 | 2.1 % | 1162 | 167 |

**Reading:** there is a **window (4–7 EVs)** where flexibility-as-insurance is
cheaper than reinforcing. The crossover is **8 EVs** (1.33 EV/home).

**Two honesty corrections applied after adversarial review — read these before
citing the headline:**

1. **Coverage is an ENERGY-service test, not a congestion one.** With full
   enrollment the backstop can always hold the transformer under its rating (no
   un-enrolled EV draw is left to spill), so the congestion clause is satisfied *by
   construction*. What can fail is how much charging the backstop denies. Coverage
   stays 100 % because the mean curtailed fraction never exceeds **2.1 %** — far
   inside the 10 % tolerance. So flexibility fails on **cost**, never on
   reliability (`flex_viability_limit_adoption` is null — a finding, left unpinned).
2. **The comparison is made like-for-like by pricing the denied charging.**
   Reinforcement delivers 100 % of the EV energy; flexibility does not. The flex
   cost therefore includes the unserved energy at `C_RETAIL_KWH`, reported
   separately above so the concession stays visible. It is small ($3.77 of $503 at
   the reference) — which is what makes the cheaper headline defensible rather than
   an artifact of delivering less.

**Headline fragility (disclosed):** the crossover is an integer and the project
carries two reinforcement anchors. At `TRAFO_CAPEX_PER_KVA × the new rung`
(used here) it is **8 EVs**; at pilar-1's flat `CAPEX_UPGRADE = 8000` it is
**7 EVs** (`crossover_adoption_flat_capex`). The window exists under both; its
right edge moves by one rung.

Reinforcement is lumpy (ladder rungs) while insurance scales smoothly — that shape,
and the activation frequency, are the robust results; the dollars are illustrative.

## Sources

- Hydro-Québec — winter grid-capacity / cold-day heating share (≈80 % of household electricity).
- LBNL / T. Hong — heating-load diversity in residential districts (CF ~0.85).
- PES-PSRC report 075 — cold-load pickup; IEEE 4113138; arxiv 1810.05734 — CLPU magnitudes.
- arxiv 2409.18105 — diversified per-device LV peak contributions (EV ~1.4 kW).
- PMC/NCBI PMC11534675 — Québec all-electric baseboard dwelling (~13 kW).
- IEEE C57.91-2011 — transformer loading guide; Hydro-Québec Blue Book E.21-10 (negative result).
- **EV behavior:** Jonas, Daniels & Macht, *Energies* 2023, 16(4):1592 (Canada, >7000 stations);
  Charge the North (Geotab/FleetCarma, >1000 CA drivers); Pollution Probe — *Consumer EV
  Charging Experience in Canada*.

*Verified with a 3-vote adversarial panel (2026-06-23). The Québec-specific
figures in this list remain literature inferences — no published HQ sizing rule
was found directly. This is a statement about the SOURCES ABOVE, not about the
study: metered Hydro-Québec data (`datasets/hq`, n = 215 all-electric) arrived
2026-08-04 and is what the building model is validated against.*

## Latching thermostats — diversity re-base (2026-08-04)

The 6th deliberate re-base, and the first driven by a defect in the *dynamics*
rather than the levels.

**What was wrong.** The base was validated on two AGGREGATE properties — diurnal
shape and aggregate smoothness — and both hold. Neither constrains what a single
dwelling does. Measured against the Hydro-Québec 1000-home set (all-electric
subset: electric heating >= 60% of annual energy, n=215; windows matched on mean
outdoor temperature), real heating moves >2 kW between consecutive 15-min samples
in **39.9%** of intervals, mean |Δ| **2.60 kW**, cycling with a **~83 min** median
period. The SDK's `proportional` controller — a 10-level quantized law whose
docstring claimed ON/OFF hysteresis — produced **0.0%** and **0.05 kW**, cycling
every ~42 h. It does not cycle; it follows the outdoor temperature.

**Why it matters here.** Dwellings that never step arrive pre-diversified, so an
aggregate of a FEW of them is too smooth. Peak per home, full TMY year:

| homes | measured | proportional | hysteresis |
| --- | --- | --- | --- |
| 1 | 17.95 kW | −27.7% | −10.2% |
| **6** | **11.82 kW** | **−13.4%** | **−5.3%** |
| 12 | 10.83 kW | −13.9% | −7.8% |
| 60 | 9.38 kW | −10.2% | −7.4% |

Six is the pole-transformer size this study sizes. A negative bias understates
base load and therefore OVERSTATES hosting capacity — the headline.

Validating on a single cold week gave −9.6% at 6 homes; the full year gives
−13.4%. The weekly figure understated the defect by a third.

**The fix.** SDK `control="hysteresis"`: 3–6 zones per dwelling, each with its own
thermostat, setpoint and **air temperature**. The own-temperature part is what
makes it work — a first attempt shared one node, the zones latched together and
the ensemble degenerated back into a slow proportional law (181 min cycle). With
independent states, mean |Δ| is 2.65 kW against 2.60 measured.

**Energy is unchanged** (29.9 → 30.0 MWh/home over the TMY year), so `R_STUDY_B`
and the annual-energy anchor (~29 MWh against 28.3 measured for the all-electric
subset) stand as-is. This re-base moves dynamics only.

**Headline effect.** 50 of 81 pins moved. Firm hosting capacity **12 → 11 EVs**
(−8.3%); credibility p50 12 → 11, p05 11 → 10; deferral NPV −31.5%; flexibility
expansion 0.333 → 0.455 (firm is lower, so the relative gain from flexibility is
larger). A static-rating estimate had suggested ~35% — the realized effect is
much smaller because the study rates on the hourly K(T) curve, not nameplate.

**Residual.** The bias is −5.3% at 6 homes, not zero: the base remains mildly
optimistic. The mechanism is known and unfixed — `minute_of_day` is a dead
parameter in the building model and `occupancy_offset_min` is sampled but never
read, so the thermal model has no time-of-day dependence. Real dwellings hold
long high/low regimes driven by occupancy; the model jitters inside a narrow
band. Any future work on this base should start there.

Determinism verified: the recalibrated base hashes identically across repeat
invocations and across `PYTHONHASHSEED`. Regression: 81/81.

## Config-as-contract re-base (Phase 20, 2026-08-17) — NO value change

Phase 20 (Flagship Migration, R22 wave-2) moved the study knobs from
`scripts/config.py` into `project.yaml` under `spec.inputs.studyConfig`
(config-as-contract, the same pattern `admm_thermal_consensus` adopted in Phase
19). This is a **location change, not a calibration change**: every value was
migrated identity-preserving (same value, new source of truth), so no headline,
pin, or cache artifact moved. The 81-pin baseline is proven value-identical by
`tests/test_ev_hosting_flex_project.py` (json_path + tolerance against each
metric's declared source report), and the annual byte-stability seal re-ran in
fresh `python -m` subprocesses on the migrated surface.

This entry exists so a future reader does not mistake the config→contract move
for a deliberate re-calibration — there is none here. Any future re-base must
still be recorded in this file with its rationale, per repo discipline.

## EnergyPlus validation receipts published (2026-09-01) — NO value change

**Nothing in this study's numbers moves here.** This entry records evidence that
already existed and was unreadable: the results of `tools/ochre_calibration/`,
the EnergyPlus white-box reference for the RC building model, lived only in the
gitignored `.ochre-calibration/` working tree. They are now published under
`tools/ochre_calibration/receipts/`, typed by
`tools/ochre_calibration/receipts.py`, and held in place by
`tests/test_ochre_receipts.py`.

### The flexibility result, and its comfort cost

The deferral thesis this study rests on has an external validation, on dwellings
the decision was **not** fitted on. Decision: pre-heat +1.5 °C over 13:00–16:00,
curtail −2.0 °C over 16:00–19:00, relative to each household's own setpoint.

| arm | dwellings | mean relief kW/home | rebound kW/home | worst comfort drift |
|---|---|---|---|---|
| fit | 14 | 4.381 | 1.255 | −2.0 °C |
| **holdout** | **15** | **3.777** | 1.081 | **−2.0 °C** |

**The comfort cost belongs beside the relief and has not been quoted with it
before.** 3.777 kW/home of relief costs a worst-case 2.0 °C indoor depression
during the curtail window. Relief exceeds rebound, so the dispatch removes load
rather than merely moving it an hour later.

### The RC model's error bound against EnergyPlus

A separate and harsher experiment — **full** heating curtailment 16:00–19:00
over the coldest week, not the bounded setback above:

`mae_curtailment_relief_kw_per_home` = **5.3 kW/dwelling**, over the same
15-dwelling disjoint holdout. RC **promises 3.137** kW/home; EnergyPlus
**delivers 8.437**. The scalar is promised minus delivered, so the RC model
**understates** the relief it gets — conservative in direction, but a bound
larger than the promise it qualifies. Worst-case comfort drift under full
curtailment is −16.4 °C, which is why the shipped decision uses a bounded
setback.

Scope limit, quoted from the receipt: it covers shifted energy, rebound and
thermal inertia; it does **not** cover instantaneous coincidence, where
`datasets/hq` remains the arbiter.

### Coincidence — EnergyPlus corroborates the metered arbiter

Against `datasets/hq` (all-electric subset, n=215, 15-min, 2019-02-08…14), the
EnergyPlus coincidence curve tracks measured within 2–5 % across 2…32 homes,
consistently slightly low: 0.656 vs 0.677 at 6 homes, 0.597 vs 0.619 at 12,
0.549 vs 0.578 at 32. It is a corroborating second reference, not the arbiter.

**Caution for a reader of §1 of this file.** The CF ≈ 0.85 figure recorded there
comes from hourly, district-scale literature. Both the metered set and
EnergyPlus put the coincidence factor of a **6-home** group nearer **0.66–0.68**
at 15-minute resolution — the size and resolution this study actually sizes a
pole transformer on. The two are different statistics and should not be used
interchangeably.
## Cooling coupled to the thermal node (2026-09-01) — summer only, no headline change

**A defect fix, not a re-calibration.** The zone branch of `Building.step()` --
taken whenever `control="hysteresis"`, which is what this study declares
(`project.yaml:236`) -- advanced its state with a heating term only. The air
conditioner was computed, reported in `p_total_kw` and billed, and removed no
heat. Because it never satisfied its own thermostat it latched open-loop on
outdoor temperature, so it also drew far more than a working A/C would. The
other two integrator branches carried `- ETA_COOL * p_cool_actual` correctly;
only this one did not.

Demonstration, holding a dwelling at 32 °C for 8 h with the zone state
initialised to 32 °C: before the fix the A/C drew **24.0 kWh** and indoor
temperature was **identical** to the same dwelling with no A/C at all. After,
it draws 7.2 kWh and settles at 24.3 °C — and matches the `proportional`
branch exactly, which is the cross-check that matters, since the two modes
differ in *heating* control and share the same cooling physics.

### Blast radius, measured before the fix landed

Annual base trace, this study's own settings (`R_STUDY_B`, `P_HEAT_QUEBEC`,
hysteresis, 1-min integration), 6 homes, seed 42, full TMY year:

| | shipped | fixed | delta |
|---|---|---|---|
| annual peak kW | 73.578 | 73.578 | **0.00 %** |
| winter peak kW | 73.578 | 73.578 | **0.00 %** |
| P95 cold-evening kW | 49.670 | 49.653 | **−0.03 %** |
| hours over rating | 0.0 | 0.0 | unchanged |
| summer energy kWh | 13 586.9 | 11 005.8 | −19.0 % |
| summer peak kW | 43.731 | 34.058 | −22.1 % |
| annual energy kWh | 178 198.0 | 175 595.9 | −1.46 % |

**The headline does not move; three congestion pins do.** This study's firm and
flexible EV counts turn on cold evenings, where cooling never engages, and both
are unchanged (firm 11, flexible 16, +45 % expansion).

The table above was measured on the **base trace alone**, and read that way it
is misleading: with no EV pool on top, summer never crosses the transformer
rating, so it suggested nothing downstream could move. That was wrong. With the
EV pool at its top adoption the inflated summer base *did* cross the rating, and
three annual congestion pins carried it:

| pin | was | now | delta |
|---|---|---|---|
| `annual.congested_hours_at_pool_top` | 20.25 | 19.5 | −0.75 h/yr |
| `annual.curtailed_pct_at_pool_top` | 0.386786 | 0.362857 | −6.2 % |
| `annual.jain_fair` | 0.995782 | 0.99535 | −0.04 % |

Read plainly: **0.75 congested hours per year in the previous baseline were
produced by an air conditioner that removed no heat.** The fix removes them.

### Deliberate re-base of three pins

`results_baseline.json` is updated for those three, and for nothing else — 78 of
81 pins were value-identical before the edit. This is a re-base *behind a defect
fix*, which is the case the cross-cutting rule allows, and it is recorded here
rather than applied silently.

Determinism was checked separately, because the annual byte-stability seal fails
on any legitimate value change: it hashes the on-disk outputs, re-runs the
chain, and compares. The first run therefore compared old-code outputs against
new-code outputs and diverged, which is code-versus-code, not the run-versus-run
non-reproducibility that test exists to catch. **Re-run with the outputs already
regenerated, the seal passes** — two runs of the fixed code are byte-identical.
Annual energy falls 1.46 %, entirely from summer.

`admm_thermal_consensus` also declares `heatingControl: hysteresis`, and is
**unaffected**: it runs a single cold day (−21.9 to −15.5 °C) and its total
cooling energy over the window is exactly 0.

### Also fixed here

`Building.step()` accepted an `integrator` argument, validated it, and then
ignored it on the zone branch — so `integrator="exact"` silently ran Euler in
every shipped study. It is now honoured per zone, using the same exact-discrete
form as the whole-house node (τ = R·C is identical for every zone, so only
`T_eq` differs). Both studies run the default `"euler"`, so no result moves.
Measured agreement after a full day at dt = 1 min: 7.2 × 10⁻⁵ K on the smooth
controller, 0.081 K on the latching one — larger there because a zone that
flips one step earlier separates the trajectories discretely.

`tests/test_building_cooling.py` asserts, in **both** control modes, that a
cooling-capable dwelling ends colder than the same dwelling without cooling.
The defect lived in exactly one branch, so a mode-agnostic assertion is the one
that would have caught it.

## First coherent run, and the re-base it forced (2026-09-04) — 27 pins

**Read this with the "Cooling coupled to the thermal node (2026-09-01)"
section above.** That re-base measured its blast radius on the base trace
alone, moved three `annual.*` pins, and declared the other 78 value-identical —
against artifacts on disk that the cooling fix had never regenerated. Every one
of those artifacts dated from 08-04, 08-18 or 08-19. The eleven downstream
stages had not been re-run on the fixed base. "Value-identical" was true of the
files and false of the code.

The first run of all 23 stages from committed code (`7f8cbb03`, 15:30–19:21
UTC, outputs backed up first as `syntgrid-ev-outputs-PRE-clean-run-20260904`)
is the first measurement of what the cooling fix did downstream. 31 pins
differ; 27 are re-based here, on that run. Nothing since `bd1253ac` can have
moved them: the five scripts whose pins drifted have zero commits, `_annual.py`'s
one commit is reformatting (`annual.*` pins pass; `base_peak_kw` byte-identical),
the exported twin's `sha256` is identical across runs, and
numpy/scipy/pandapower/python match the 09-03 manifest.

Two magnitudes inside the 27. Eighteen drift under 1 % — annual energy −1.46 %
propagating through the AC solves (`pf.*`, `netchar.*`, `voltage*.*`). Nine
drift more, each with a mechanism: `coldcoupling.curtailment_underestimate_ratio`
+50 % because the *naive* model's summer-driven curtailment (its denominator,
7 kWh/yr) fell 37 % while the cold-coupled numerator fell 6 %;
`flexincentive.shift_ceiling_warmest` 2.5 → 1.83 and the `cluster.*` block
because summer peaks moved; `cred.firm_p95` 13 → 12.55 because one of K=50
realizations crossed the 95th-percentile position under numpy's linear
interpolation; `pf.post_ev_1p5_n_trafos_over_dynamic` 0 → 2 at a count boundary.

| Pin | Was | Now |
|---|---|---|
| `cred.firm_p95` | 13.0 | 12.55 |
| `cred.base_peak_p50` | 66.10 | 65.76 |
| `insurance.expected_cost_flex_at_ref` | 480.06 | 480.054 |
| `insurance.short_years_if_plan_p50` | 0.26 | 0.24 |
| `insurance.delta_firm_correlation` | 0.42 | 0.360694 |

(The full 27 are the diff of `baselines/results_baseline.json` in this commit.)

**Four pins are deliberately NOT re-based here:** `nonwires.*`. The clean run's
`total_deferral_npv` came out −19054, a sign flip, and it is a defect rather
than a measurement — `_substation_deferral` let the firm crossing run past the
planning horizon and booked a *negative* deferral (`syntgrid-eei.7`, fixed in
`dd50e374`). Those four land on an artifact the fixed code produced; expected
LV-only total +6359.52.

**Headline unchanged:** firm 11, flexible 16, +45 % expansion, break-even 6.

**The four `nonwires.*` pins, re-based on the second clean run** (from
`88c225f6`, which carries the `syntgrid-eei.7` fix):

| Pin | Was | Now |
|---|---|---|
| `nonwires.total_deferral_npv` | 6807.31 | 6359.52 |
| `nonwires.total_trafo_years_deferred` | 267.258 | 266.288 |
| `nonwires.first_reinforcement_year` | 5.37536 | 5.62674 |

The substation term is 0 with `needed_within_horizon: false` — the N-1
crossing at 1.31 EV/home is reached only after the 15-year horizon, so there
is nothing to defer. The total is the LV deferral alone.

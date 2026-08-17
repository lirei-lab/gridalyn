# EV Hosting Flex Project

Governed implementation of the **study-B EV hosting-capacity** case study:
pure Monte-Carlo over a full Trois-Rivières weather year, driven ONLY by the
SDK stochastic generators, on a physically consistent Hydro-Québec-style twin
(75 kVA / 240 V pole transformers, ~6 all-electric homes each). The study
quantifies how a **curtailment contract with day-ahead notice and a fair
real-time backstop** expands the feeder's EV hosting capacity beyond its firm
(curtailment-free) limit, and when that contract beats reinforcing the
transformer.

Design provenance: `manuscripts/ev_hosting_flex/scripts/study_b/` (the
authoritative sandbox) and the local migration design doc
`docs/superpowers/specs/2026-07-06-ev-hosting-flex-study-b-annual-migration.md`.

## Generators (the model, in two pieces)

1. **Buildings — SDK agent only** (`gridalyn.assets.datagen.agents`):
   first-order RC thermal model per dwelling with ON/OFF thermostat hysteresis
   over an electric baseboard, plus a time-correlated AR(1) background load
   (appliances/lighting, scaled by `BG_SCALE`), plus an explicit stochastic
   **electric water-heater tank** (`dhw_tank_annual`: 270 L / 4.5 kW thermostatic
   tank with draws following a **continuous occupancy profile** —
   `dhw_draw_profile()`, an all-day baseline + smooth morning/evening Gaussians —
   and **per-home tank diversity** (setpoint/deadband/element/volume jitter) so
   reheats stagger and the aggregate has no coincident on/off step; 2026-07-16 fix). Base = `Σp_heat + Σp_cool +
   BG_SCALE·Σp_bg + DHW`. Simulated at 1-min over the committed annual TMY and
   aggregated. Recalibrated to the Québec all-electric archetype (`R_STUDY_B =
   7.5 °C/kW`, `P_HEAT_QUEBEC = 13 kW`, `DHW_ELEMENT_KW = 4.5`, `BG_SCALE = 0.6`):
   the 6-home feeder base is realistic in **both** power and energy — peak
   ~11.2 kW/home (centre of the CALIBRATION.md 10–15 band) AND annual energy
   ~29.4 MWh/home (25–30 band), with a textbook 63/14/24 % heat/DHW/appliance
   split (2026-07-14 DHW re-base; the old `R = 5.0` hit the peak but inflated
   energy to ~39 MWh). No parametric fallback exists — the SDK agent import
   failing is a hard error.
2. **EVs — the study-B cold-coupled sampler** (`scripts/_annual.py`):
   per EV per day, plug-in probability (0.60 → 0.85) and lognormal session
   energy (+50 % median at −25 °C) BOTH rise with the day's cold intensity, so
   EV stress compounds with the heating peak exactly on the critical evenings;
   charger mix {7.2: 75 %, 9.6: 20 %, 11.5: 5 %} kW, evening Gaussian arrival
   (18 h ± 1.5, clip 16–22). One pinned nested pool (12 EVs × 8760 h); every
   sweep uses row prefixes.

## Pipeline (workflow.yaml)

| Stage | What it does | Key outputs |
|---|---|---|
| `prepare_topology_cache` | Synthetic HQ twin via the public facade (240 V / 75 kVA / 2 % vk pole transformers) + feeder selection (idx-10, 6 homes) | `outputs/cache/*` |
| `generate_annual_mc` | SDK annual base realizations + day-ahead forecast bases per σ + the cold-coupled EV pool | `base_annual.npy`, `fc_base_sigma_*.npy`, `ev_fleet_annual.npy` |
| `compute_congestion_annual` | **Firm** = largest pool prefix with P95 cold-day evening loading ≤ 100 % + congested-hours curve | `firm_hosting_annual.json` |
| `apply_curtailment_contracts` | The mechanism: day-ahead call (notice), real-time backstop (reliability), fair rotation; enrollment sweep + notice quality + fairness | `curtailment_hosting.json` |
| `compute_curtailment_economics` | Two-part contract vs annualized reinforcement + zone of agreement + break-even adoption | `curtailment_economics.json` |
| `analyze_credibility` | **Credibility layer** — confidence intervals on the citable headlines. Re-runs the firm/flex/breakeven chain over **K=50 realizations** varying the building seed (`SEED+r`), the EV-fleet seed, and a synthetic **winter-severity** temperature anomaly (δ~N(0, 1.5 °C), δ₀=0), reusing the governed kernels (`firm_annual`, `simulate_curtailment`). Reports P5/P50/P95 + mode + P(=governed point). Finding: **the governed firm=11 is weather-sensitive** — [P05=10, P95=13], median 11 (histogram 2:1 3:10 4:20 5:18 6:1), while **flex=12 and breakeven=6 are robust**. The realization-0 (δ=0, SEED) point reproduces the governed firm/flex/breakeven exactly (a consistency anchor). Single TMY → the weather axis is a synthetic winter-severity proxy, not measured weather years; governed feeder / pilar-1 trio only | `credibility.json`, figure |
| `analyze_cold_insurance` | **The study that answers "why flexibility if the network is robust?"** Two parts on the credibility seeds (so both studies share one firm distribution — enforced by a test). **Part 1 (methodological):** hosting capacity is a **distribution, not a number** — planning at the P50 leaves the feeder short **22 % of years** (at the P5, 2 %), and corr(winter severity, firm) = **+0.42** shows the spread is weather, not sampling noise. **Part 2 (economic):** to host a target adoption, compare **reinforcing** (upgrade so firm ≥ A in ≥95 % of years, paid every year) against **flexibility as insurance** (availability every year + the expected activation + the value of the charging it denies) — at an equal reliability target. Finding: there is a **window** where insurance wins. At 1–3 EVs neither is needed; at **4–7 EVs flexibility is cheaper** (at the 6-EV reference the feeder falls short 98 % of years yet flexibility covers **100 %** of them for **$503/yr vs $696/yr** to reinforce — 28 % cheaper); the **crossover is 8 EVs** (1.33 EV/home), beyond which reinforcing wins. Two honesty corrections from adversarial review: coverage is an **energy-service** test (with full enrollment the backstop always holds the transformer, so what can fail is denied charging — the mean curtailed fraction peaks at **2.1 %**, far inside the 10 % tolerance), and the flex cost **prices the denied charging** at retail so the comparison is like-for-like ($3.77 of the $503 at the reference). Flexibility fails on *cost*, never on *reliability* (`flex_viability_limit` null — a finding, not pinned). The crossover is one rung fragile: **7 EVs** under the project's flat CAPEX anchor, reported as `crossover_adoption_flat_capex`. Reinforcement is lumpy (75→100→167 kVA rungs) while insurance scales smoothly — that is the shape of the argument. Synthetic climate axis; illustrative costs (the robust results are the shape and the activation frequency, not the dollars) | `cold_insurance.json`, figure |
| `analyze_nonwires_value` | **Pilar-2: network-scale non-wires value** — the SOLUTIONS answer to the diagnostic. Per transformer SIZE (mapped to the 540) a kernel (`flex_deferral_curves`) gives the without-flex coincident-peak curve + the with-flex (valley-fill shift + local-curtailment backstop) curtailed-energy curve; the stage derives A₀ (first overload) and A₁ (adoption until flex stops being viable — reliability [curtailed > 10 %] OR economics [contract > annualized reinforcement]). A logistic adoption ramp maps A₀/A₁ to years, so **deferral NPV = CAPEX·((1+r)⁻ᵞ⁰ − (1+r)⁻ᵞ¹) − flex-contract cost**, aggregated over the 540 LV transformers (per-size × count) + the N-1 substation. Emits the ramp headline (**$6.8 k NPV + 267 transformer-years deferred**, DOMINATED by the substation $47 k) AND a ramp-shape-robust per-adoption snapshot (peak $1.8 M CAPEX under deferral at 0.8 EV/home). Finding: the non-wires value is **dominated by the substation** deferral — the feeders either bind **base-driven** (the realistic all-electric base alone overloads them, so EV flexibility cannot defer them) or bind late enough that reinforcement is cheaper than paying flexibility; only the early-binding sizes (5/9/10-home) defer at the feeder level. A₁ is a viability bound, not a physical crossing (curtailment always caps); base-driven overloads are honestly excluded; per-size deferral is floored at 0 (a value-negative contract is declined); CAPEX anchors illustrative ($107/kVA installed, reconciled with pilar-1); logistic ramp is one scenario (the snapshot is robust) | `nonwires_value.json`, figure |
| `analyze_network_characterization` | Design-day full-net sweep of technical losses, the substation N-1 firm capacity (standard HQ bank of 2 identical parallel 33.3 MVA units on a common tied MV bus, ~56% loaded normally — on a single-unit contingency the survivor carries the base on its emergency rating, and the area peak crosses that N-1 emergency firm capacity at ~1.35 EV/home), and the per-transformer hosting-headroom map | `network_characterization.json`, figure |
| `analyze_clustered_adoption` | Study 3B: non-uniform (clustered) EV adoption at a **fixed fleet** (mean-preserving lognormal draw over the 540 LV transformers, dispersion swept). The clustering **penalty** = worst-transformer loading at a fixed mean rate, uniform vs most-clustered (rises with the adoption Gini); clustering concentrates stress (fewer transformers overload but the hotspots get far worse). Then the **recovery**: per-transformer local curtailment (static-rating cap, no time-shift) pulls the worst hotspot back toward its rating, at a curtailment-energy cost concentrated (burden Gini) on the EV-heavy clusters. Phase imbalance out of scope (needs `runpp_3ph`) | `clustered_adoption.json`, figure |
| `analyze_flexibility_incentive` | Study 1A: the vanishing valley, reframed. Bins the TMY year by daily-mean temperature and computes the **shift-hosting ceiling** per bin — the EV/home at which optimal valley-fill smart-charging exhausts the day's *distributed* headroom (pure-kW, 24-hour peak on the governed feeder). Finding: even the all-electric cold base (67–89 %, never at 100 % all day) leaves enough headroom that optimal shift hosts ~3.8 EV/home at −20 °C, rising to 8+ in mild weather — so the naive "no overnight valley → curtailment required" fear is overturned at realistic penetration; the earlier fixed-window probe underestimated optimal smart-charging. Beyond the ceiling curtailment is required; at a high-adoption target a lognormal-WTA incentive optimum migrates shift→curtail at a crossover temperature. WTA illustrative; the shift-ceiling curve is the robust headline | `flexibility_incentive.json`, figure |
| `analyze_network_performance` | Network performance state under a load-growth hypothesis: the network is sized at G=1 and evaluated under base×G (real networks are under-reinforced — sized for an earlier load that grew). Per-transformer utilization / exceedance-hours / headroom / **growth-margin** over the 540 LV transformers, the **flexible-vs-inflexible peak share** (the ceiling on the value of EV flexibility), and the feeder **flexibility window** (uncontrolled vs optimal-shift hosting vs G). Findings: the healthy network sits ~7.6 % below the overload cliff (`growth_margin_p50`); the coincident peak is only ~31 % EV (mostly inflexible heating — why flex is bounded); flexibility is the right tool only in a narrow loadedness band `G ∈ [1.0, 1.13]` — below it over-built, above it the base overloads and reinforcement is required. Homogeneous-base approximation; pure-kW | `network_performance.json`, figure |
| `analyze_congestion_risk` | Probabilistic congestion DIAGNOSTIC (diagnosis before solutions, no flexibility). Monte-Carlos BOTH stochastic generators — the SDK building base (per distinct transformer size, cached in `base_mc_by_size.npz`) and the EV fleet — and takes the 15-min coincident daily-max peak on cold days to estimate, per transformer, the **probability** P(cong) and **peak severity** (P95/P99/max) of congestion across a load-growth surface (G × EV/home). Finding (overturns "the network is robust"): peaks and probabilities reveal what averages and optimal-coordination assumptions hid — at 1 EV/home already **488/540 transformers (90 %)** carry >5 % cold-day congestion probability with peaks to **157 %**, and the network crosses the 10 %-at-risk planning trigger at just **0.10 EV/home** — or, on the other growth axis, **+10 % baseline electrification alone (zero EVs)**. Emits the per-transformer risk map, the at-risk count vs growth, and BOTH first-risk triggers (EV-adoption and baseline-growth). kW-proxy (power/thermal); AC voltage + phase imbalance are future layers | `congestion_risk.json`, `base_mc_by_size.npz`, figure |
| `analyze_phase_imbalance` | Phase-imbalance DIAGNOSTIC at 25 kV MV (`runpp_3ph`) — the HQ topology the balanced model misses: the LV is single-phase 240 V split-phase, so phase imbalance lives at MV where the single-phase pole transformers are spread across the 3 phases. Rebuilds the twin as an MV 3-phase net (`to_three_phase_mv`), places each pole transformer as a single-phase load (round-robin), Monte-Carlo over which homes adopt EVs → P(any MV phase < CSA 0.917), worst voltage-unbalance factor (VUF), and the balanced-vs-unbalanced min-voltage gap. Honest finding: with round-robin assignment + Poisson adoption the imbalance is REAL but MODEST — worst VUF rises to 2.25 % at 2 EV/home, crossing the ~2 % IEC limit around 1.5 EV/home, and the worst phase sits ~0.017 pu below the balanced view, but no CSA undervoltage at ≤2 EV/home; the binding phase metric is the VUF, not undervoltage. Load per transformer is the TRUE coincident peak (base+EV summed per hour, then maxed). Zero-sequence params are standard multipliers; single-phase LV out of scope | `phase_imbalance.json`, figure |
| `analyze_voltage_risk` | Probabilistic LV **undervoltage** DIAGNOSTIC — the AC-balanced sibling of `validate_powerflow`, made stochastic. On the governed 6-home / 75 kVA feeder subnet, Monte-Carlo over resampled EV fleets (`VOLTAGE_MC_DRAWS`) × cold days, sweeping EV adoption (`VOLTAGE_EV_GRID`); each draw×day solves one balanced `runpp` (`feeder_min_voltage`) and records the day's minimum LV bus voltage → P(min V < CSA 0.917), the voltage tail (P5/P1/worst), and `first_risk_ev_per_home`. Honest finding: the governed feeder is small and well-sized, so its LV voltage stays healthy (worst ~0.93 pu at 2 EV/home > CSA 0.917) and P(undervoltage) is ~0 — `first_risk` is None. The stage **UNDERSTATES network risk**: the network-wide undervoltage `validate_powerflow` finds (0.916 pu at 1 EV/home) sits on the LARGER / deeper feeders, not this one (surfaced as a report warning); a follow-up should target the largest feeder size. Balanced AC only (phase imbalance is `analyze_phase_imbalance`) | `voltage_risk.json`, figure |
| `analyze_voltage_risk_network` | Probabilistic **full-network** undervoltage DIAGNOSTIC — the stochastic sibling of `validate_powerflow`. On the HQ-sized whole network (`size_network_to_load`: per-cluster kVA + LV conductors + N-1 substation), Monte-Carlo over resampled EV fleets × 163 cold days sweeping adoption (`VOLTAGE_EV_GRID`); each (draw × day × level) builds a per-load kW vector (each home = diversified per-home base of ITS cluster size + uniform EV overlay), takes the network coincident-peak hour, and solves ONE full-net AC with **lightsim2grid** → P(network min LV < CSA 0.917) + tail (P5/P1/worst) + `first_risk_ev_per_home`. Unlike the governed feeder subnet, this keeps the cumulative MV + transformer + LV drop. Honest finding: at 1 EV/home the network min sits right at the CSA edge (worst 0.918 pu, matching `validate_powerflow`'s deterministic 0.916), P(undervoltage)=0; genuine >10% risk emerges at **first-risk 1.70 EV/home** (FINITE, unlike the governed feeder's None), and the reference binding bus is on the **12-home** (largest) cluster — the risk is on the biggest feeders, as the governed stage flagged. Uniform adoption (clustered = `analyze_clustered_adoption`); deep-feeder ~0.91 residual = MV-feeder drop held by LTC/regulators | `voltage_risk_network.json`, figure |
| `validate_powerflow` | AC validation before/after EVs: (1) design-day network family with each of the 540 LV transformers sized to its own load on the HQ standard kVA ladder + IEEE C57.91 cold dynamic rating; (2) cold-day Monte-Carlo on the 6-home feeder subnet (transformer + LV line loading + home voltage) | `powerflow_*.parquet`, `powerflow_violations.json`, figures |

The kW chain runs at **15-minute resolution** (`ANNUAL_RES_MINUTES`): hourly
means understate the sub-hourly coincidence of the few 13 kW baseboards and the
discrete EV step, so the congestion metrics are computed at the utility
demand-metering interval (the SDK agent already simulates 1-min, so the finer
base aggregation is free; the AC validation layer stays hourly).

## Lead finding: cold-coupled EV charging shrinks winter hosting

In a cold all-electric network the winter heating peak coincides with the
evening EV-charging peak, and EVs charge MORE on the coldest evenings (higher
plug-in probability + larger sessions). `analyze_cold_coupling` re-runs the
firm/flexible/curtailment analysis on a NAIVE (cold-agnostic) EV model — the
standard hosting-study assumption of a fixed year-round profile — against the
governed cold-coupled model:

- A naive model **overestimates the firm winter hosting limit by 50 %** (3 vs
  2 EVs on the 6-home feeder).
- It **underestimates the curtailment the flexibility contract must deliver
  ~2.8×** (2.2 % vs 6.1 % of EV energy).
- Driver: the cold-coupled model puts **+54 % more EV energy on cold days**,
  exactly when the electric-heating base also peaks.

Takeaway: cold-climate EV hosting studies need cold-coupled charging demand;
a typical/mild profile is optimistic about both the limit and the flexibility
work. See `cold_coupling_comparison.png`.

## Headlines (governed pins, `baselines/results_baseline.json`)

- **Firm = 11 EVs** (P95 cold-evening rule against the hourly K(T) capability
  curve; P05-P95 across weather years is 10-13).
- **Flexible = 16 EVs (+45 %)**: the full-enrollment backstop hosts the whole
  pool, curtailing **0.39 %** of EV energy.
- **Notice**: at σ_T = 1.5 °C day-ahead forecast error, ~97 % of curtailment
  arrives pre-notified; the backstop covers the rest (no forecast-blindness).
- **Economics**: the contract (80 $/EV·yr + 0.5 $/kWh) beats the ~520 $/yr
  annualized reinforcement up to **6 EVs (38 % of the pool)** — the technical
  +45 % vs the narrower economic window is the study's two-sided headline.
- **AC network validation (HQ-realistic network)**: the LV transformers (load-
  matched on the standard kVA ladder + C57.91 cold dynamic rating), the LV
  secondary conductors (thermal ampacity + ≤1 %/conductor voltage drop), and the
  substation (the standard HQ N-1 bank of 2 identical parallel 33.3 MVA 120/25 kV
  units on a common tied MV bus, ~56 % loaded normally — sized so the lone
  survivor carries the full load on a single-unit contingency using its 1.5×
  emergency rating) are all matched to the Québec all-electric design-cold load.
  The network is then fully healthy before EVs (LV min voltage 0.942 pu, no
  overloads), and EV adoption drives undervoltage and LV line overloads (the
  binding channels — 1.5 EV/home: min 0.900 pu, 431 lines over 100 %) while the
  load-matched LV transformers stay robust and the substation N-1 becomes a real
  reinforcement trigger at ~1.35 EV/home. The governed 6-home / 75 kVA feeder
  stays fixed, so the firm/flexible headlines are unaffected.
- **AC caveat (reported, not silently fixed)**: the governed firm/flexible gate
  uses the conservative STATIC feeder rating (kVA × PF); the cold-day AC feeder
  MC shows the firm count overloading a few % of cold days (losses/reactive
  flow push AC apparent power ~3–4 % above the kW proxy). An AC-consistent
  governed rating is an open, deliberate study decision.

## Running

```bash
uv run gridalyn project validate projects/ev_hosting_flex
uv run gridalyn project run projects/ev_hosting_flex
uv run gridalyn project regression projects/ev_hosting_flex
# or stage by stage:
uv run python projects/ev_hosting_flex/scripts/pipeline/generate_annual_mc.py
uv run python projects/ev_hosting_flex/scripts/verify_regression.py
```

Outputs land under `projects/ev_hosting_flex/outputs/` (gitignored; every
artifact-producing stage emits a platform report). Reproducibility contract:
`SEED = 42`, BLAS thread caps at stage import, float64 everywhere, 1e-6
rounding before writes; the annual chain is byte-stable across runs
(`tests/test_ev_hosting_flex_annual_seal.py`).

## History

The design-day two-stage-reserve pipeline (Phases 8–17, firm=6/deferral=12 on
the decoupled unit) was retired on 2026-07-07 in favour of this annual
study-B model; its record lives in git history and the migration design doc.

---

<!-- Merged from the former docs/projects/ev-hosting-flex.md. The published
documentation now covers the project CONTRACT in general; per-project
detail lives with the project. -->

`projects/ev_hosting_flex` is the repository's flagship research study: how many
electric vehicles a Québec all-electric distribution feeder can host, where the
network actually binds, and what EV flexibility is worth against reinforcement.

It is a governed `StudyProject` (22 workflow stages, ~9.7k lines of study code)
whose distinguishing property is that **its generators are validated against real
data** and its headlines are reported **with uncertainty**.

## What It Answers

The study follows a deliberate arc — *diagnosis before solutions*:

1. **Diagnosis.** Where does the network actually bind under EV growth?
    - **Thermal congestion** — probabilistic, per transformer, on cold days.
    - **AC undervoltage** — both the governed feeder and the full network.
    - **MV phase imbalance** — at 25 kV, where Québec's single-phase pole
      transformers spread across the three phases (the LV is 240 V split-phase,
      so imbalance is an MV phenomenon, not an LV one).
2. **A realistic base.** The stochastic building population is calibrated to be
   realistic in **both** coincident peak and annual energy — see below.
3. **Solutions.** Network-scale non-wires value: how much reinforcement
   (transformer-years and NPV) EV flexibility defers, across all 540 LV
   transformers plus the N-1 substation bank.
4. **Credibility.** Confidence intervals on the citable headlines over K=50
   realizations spanning seeds and winter severity.
5. **Cold-tail insurance** — the study the others were building toward, and the
   answer to *why flexibility matters if the network is robust at the median*:
    - **Hosting capacity is a distribution, not a number.** Firm hosting spans
      **10–13 EVs** (P05–P95) across weather years, and the spread is weather
      (corr(severity, firm) = **+0.42**), not sampling noise. Planning at the P50
      still leaves the feeder short **26 % of years**.
    - **At the governed feeder there is currently nothing to insure.** Judged
      against the capability each hour's ambient allows (see *Rating convention*
      below), the reference adoption never falls short — activation frequency
      **0**, and the reinforcement it would defer costs **$0/yr** because no
      reinforcement is triggered. The crossover where reinforcing wins sits at
      **11 EVs**, i.e. at the firm limit itself.
    - This is a **result of the rating convention, not an absence of risk.**
      Under the static nameplate the same feeder falls short in most years and
      the insurance case is worth several hundred dollars a year against
      reinforcement; under the ambient-dependent capability it never binds. The
      convention moves the answer more than the EVs do. Set
      `RATING_CONVENTION = "static"` and re-run to reproduce that comparison —
      the figures are deliberately not quoted here, because a number carried
      across a convention change is how this study previously acquired several
      stale headlines.
    - Coverage is an **energy-service** criterion: the backstop always holds the
      transformer, so what can fail is denied charging, and that denied energy is
      **priced into** the flex cost so the comparison is like-for-like.
    - Where the value does live is the **fleet**, not this feeder — see the fleet
      triage, which classifies all 540 transformers rather than the one the
      headline happens to sit on.

## Why It Is Defensible

The building base generator is validated on three independent axes:

| Axis | Validated against | Result |
|---|---|---|
| Diurnal shape | Real Hydro-Québec 1000-home dataset (`datasets/hq/`) | Same dual morning/evening peak |
| Aggregate smoothness | Same HQ dataset | Needs revalidation — see note |
| DHW tank physics | CREST model lineage (via `demod`) | Surface-normalized UA matches (0.0598 vs 0.0600) |

!!! warning "The smoothness axis is stale"

    This axis was measured at the 5th re-base as 0.35 kW/home/h coincident step
    against an HQ reference of 0.41. Neither figure survives scrutiny today: the
    0.41 reference appears nowhere in the repository, and the 0.35 predates the
    6th re-base, which gave dwellings latching thermostats and deliberately
    raised per-dwelling stepping. An attempt to recompute it did not reproduce
    the original definition — the home count, window and normalisation were not
    recorded — so the numbers are withdrawn rather than replaced with new ones
    that would be equally unverifiable. The other two axes are unaffected.

The base is realistic in **both** dimensions at once — ~11 kW/home coincident peak
(inside the Hydro-Québec 10–15 kW design band) **and** ~29 MWh/home/year — rather
than hitting one at the cost of the other. Reaching that required modelling the
electric water-heater tank explicitly, since a single-R envelope model couples
peak and energy and cannot satisfy both.

Full calibration provenance, including six deliberate re-bases and their
rationale, is in `projects/ev_hosting_flex/CALIBRATION.md`.

## Rating Convention

How a load is judged against a transformer limit is a **declared axis** of this
study, not an assumption. `RATING_CONVENTION` in the project config decides it in
one place, and every stage consumes it through the same helper.

| Convention | What "overloaded" means |
|---|---|
| `static` | above the nameplate — a rating defined at a 30 °C ambient basis |
| `hourly_kt` (default) | above the IEEE C57.91 capability at **that hour's** ambient |

It matters more here than the EVs do. In a heating-dominated feeder the load
peak and the thermal capability are driven by the same variable and rise
together: at the design cold the capability is ~1.43× nameplate, arriving in
exactly the hours the load peaks. Judged against the nameplate, 255 of 540
transformers are in trouble today; judged against the ambient-dependent
capability, none are. Choosing the convention moves more assets than
electrifying every household vehicle in Québec would.

The extra capability is not borrowed against transformer life: across the whole
reachable adoption range the resulting hot spot stays below the 110 °C
normal-insulation-life limit.

## Honest Findings

The study reports results that weaken the flexibility case where the evidence
says so — this is deliberate:

- At realistic penetration the network is **genuinely robust**; the median feeder
  has headroom. Validation against real HQ feeders confirms this is how Québec is,
  not a modelling artifact.
- The winter peak is dominated by **inflexible electric heating**, not EVs.
- The non-wires value is **dominated by the substation**, not the feeders: feeders
  either bind for reasons flexibility cannot fix, or bind late enough that
  reinforcing is cheaper than contracting flexibility.
- The firm hosting headline is **weather-sensitive** — a colder-than-typical winter
  moves it materially, which is why it is published with a confidence interval.

## Reproducing It

The study is heavy — the annual Monte-Carlo base and the AC power-flow stages
are the multi-hour core of the roughly six-hour full regeneration, so it is
**not** executed in CI. Its regression baseline is **operator-verified** (a
shape-covering subset runs the non-heavy stages via
`tools/flagship_verify.py`; the full regeneration is scheduled and recorded in
the verification receipts). Since Phase 20 the stages are invoked as
interpreter-bound modules (module identity for the pickled caches):

```bash
# run a stage (Phase 20: {python} -m, the workflow's own invocation mode)
python -m projects.ev_hosting_flex.scripts.pipeline.<stage>

# verify the governed baseline
python projects/ev_hosting_flex/scripts/verify_regression.py
```

The reproduce-and-pin tests in `tests/test_ev_hosting_flex_*.py` `skipif` their
(gitignored) outputs are absent, so they **skip in CI**. After touching any
generator or kernel, re-run the affected stages locally and re-verify the baseline
before trusting a green test run.

## Phase 20 migration (2026-08-17)

The flagship was migrated onto the Project Developer API surface (R22 wave-2),
mirroring the `admm_thermal_consensus` migration in Phase 19. The migration is
**identity-preserving** — every governed pin and cache artifact has the same
value as before; nothing was re-calibrated (see `CALIBRATION.md`).

- **config-as-contract (20-01):** the ~177 study knobs (seeds, thresholds,
  calibration constants) moved from `scripts/config.py` into
  `project.yaml` under `spec.inputs.studyConfig`. `config.py` now reads that
  block through located errors; `project.yaml` is the single source of truth.
- **`{python} -m` + boilerplate removal (20-02):** the 20 pipeline stage
  commands in `workflow.yaml` are now
  `"{python} -m projects.ev_hosting_flex.scripts.pipeline.X"`, and every stage
  dropped its `sys.path`/`parents[N]`/`noqa: E402`/`os.environ` boilerplate.
  JSON IO routes through `script.read_json`/`script.write_json` (the SEAL-01
  BLAS thread cap moved to `scripts/__init__.py`, which executes before the
  stage under `-m`).
- **SDK topology closure (20-03):** the private `scripts/_topology.py` was
  deleted; its 5 SDK-duplicated functions now resolve from
  `gridalyn.simulation.analytics.topology` (GAP-1/GAP-2 closure). The
  flagship-specific helpers (`select_feeder`, `annual_peak_base_factor`, the
  seasonal factor curves) were re-homed into `scripts/_topology_helpers.py`.
- **R7 proof (20-04):** `tests/test_ev_hosting_flex_project.py` pins the 81
  baselines as **value-identical** post-migration (json_path + tolerance against
  each metric's declared source report), asserts zero `sys.path`/`parents[N]`/
  `noqa: E402` in the migrated scripts, and asserts the runtime `studyConfig`
  read. The annual byte-stability seal re-ran in fresh `python -m` subprocesses
  and confirmed byte-stable artifacts.

The migration's R7 guarantees are enforced by `tests/test_ev_hosting_flex_project.py`
(81-pin value-identity, zero-sys.path guard, runtime studyConfig read) and the
annual byte-stability seal in `tests/test_ev_hosting_flex_annual_seal.py`.

## Related

- `docs/projects/overview.md` — the project contract these studies implement.

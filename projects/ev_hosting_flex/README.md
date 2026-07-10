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
   (appliances/DHW/lighting). Simulated at 1-min over the committed annual TMY
   and aggregated hourly. Recalibrated to the stressed Québec all-electric
   archetype (`R_STUDY_B = 5.0 °C/kW`, `P_HEAT_QUEBEC = 13 kW`): the 6-home
   feeder base peaks at ~93 % of the 71.25 kW usable rating (~11 kW/home,
   inside the CALIBRATION.md 10–15 band). No parametric fallback exists —
   the SDK agent import failing is a hard error.
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
| `analyze_network_characterization` | Design-day full-net sweep of technical losses, the substation N-1 firm capacity (standard HQ bank of 2 identical parallel 33.3 MVA units on a common tied MV bus, ~56% loaded normally — on a single-unit contingency the survivor carries the base on its emergency rating, and the area peak crosses that N-1 emergency firm capacity at ~1.35 EV/home), and the per-transformer hosting-headroom map | `network_characterization.json`, figure |
| `analyze_clustered_adoption` | Study 3B: non-uniform (clustered) EV adoption at a **fixed fleet** (mean-preserving lognormal draw over the 540 LV transformers, dispersion swept). The clustering **penalty** = worst-transformer loading at a fixed mean rate, uniform vs most-clustered (rises with the adoption Gini); clustering concentrates stress (fewer transformers overload but the hotspots get far worse). Then the **recovery**: per-transformer local curtailment (static-rating cap, no time-shift) pulls the worst hotspot back toward its rating, at a curtailment-energy cost concentrated (burden Gini) on the EV-heavy clusters. Phase imbalance out of scope (needs `runpp_3ph`) | `clustered_adoption.json`, figure |
| `analyze_flexibility_incentive` | Study 1A: the vanishing valley, reframed. Bins the TMY year by daily-mean temperature and computes the **shift-hosting ceiling** per bin — the EV/home at which optimal valley-fill smart-charging exhausts the day's *distributed* headroom (pure-kW, 24-hour peak on the governed feeder). Finding: even the all-electric cold base (67–89 %, never at 100 % all day) leaves enough headroom that optimal shift hosts ~3.8 EV/home at −20 °C, rising to 8+ in mild weather — so the naive "no overnight valley → curtailment required" fear is overturned at realistic penetration; the earlier fixed-window probe underestimated optimal smart-charging. Beyond the ceiling curtailment is required; at a high-adoption target a lognormal-WTA incentive optimum migrates shift→curtail at a crossover temperature. WTA illustrative; the shift-ceiling curve is the robust headline | `flexibility_incentive.json`, figure |
| `analyze_network_performance` | Network performance state under a load-growth hypothesis: the network is sized at G=1 and evaluated under base×G (real networks are under-reinforced — sized for an earlier load that grew). Per-transformer utilization / exceedance-hours / headroom / **growth-margin** over the 540 LV transformers, the **flexible-vs-inflexible peak share** (the ceiling on the value of EV flexibility), and the feeder **flexibility window** (uncontrolled vs optimal-shift hosting vs G). Findings: the healthy network sits ~7.6 % below the overload cliff (`growth_margin_p50`); the coincident peak is only ~31 % EV (mostly inflexible heating — why flex is bounded); flexibility is the right tool only in a narrow loadedness band `G ∈ [1.0, 1.13]` — below it over-built, above it the base overloads and reinforcement is required. Homogeneous-base approximation; pure-kW | `network_performance.json`, figure |
| `analyze_congestion_risk` | Probabilistic congestion DIAGNOSTIC (diagnosis before solutions, no flexibility). Monte-Carlos BOTH stochastic generators — the SDK building base (per distinct transformer size, cached in `base_mc_by_size.npz`) and the EV fleet — and takes the 15-min coincident daily-max peak on cold days to estimate, per transformer, the **probability** P(cong) and **peak severity** (P95/P99/max) of congestion across a load-growth surface (G × EV/home). Finding (overturns "the network is robust"): peaks and probabilities reveal what averages and optimal-coordination assumptions hid — at 1 EV/home already **488/540 transformers (90 %)** carry >5 % cold-day congestion probability with peaks to **157 %**, and the network crosses the 10 %-at-risk planning trigger at just **0.10 EV/home** — or, on the other growth axis, **+10 % baseline electrification alone (zero EVs)**. Emits the per-transformer risk map, the at-risk count vs growth, and BOTH first-risk triggers (EV-adoption and baseline-growth). kW-proxy (power/thermal); AC voltage + phase imbalance are future layers | `congestion_risk.json`, `base_mc_by_size.npz`, figure |
| `analyze_phase_imbalance` | Phase-imbalance DIAGNOSTIC at 25 kV MV (`runpp_3ph`) — the HQ topology the balanced model misses: the LV is single-phase 240 V split-phase, so phase imbalance lives at MV where the single-phase pole transformers are spread across the 3 phases. Rebuilds the twin as an MV 3-phase net (`to_three_phase_mv`), places each pole transformer as a single-phase load (round-robin), Monte-Carlo over which homes adopt EVs → P(any MV phase < CSA 0.917), worst voltage-unbalance factor (VUF), and the balanced-vs-unbalanced min-voltage gap. Honest finding: with round-robin assignment + Poisson adoption the imbalance is REAL but MODEST — worst VUF rises to 2.3 % at 2 EV/home (over the ~2 % IEC limit), the worst phase sits ~0.017 pu below the balanced view, but no CSA undervoltage at ≤2 EV/home; the binding phase metric is the VUF, not undervoltage. Zero-sequence params are standard multipliers; single-phase LV out of scope | `phase_imbalance.json`, figure |
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

- **Firm = 2 EVs** (P95 cold-evening rule crosses 100 % between 2 and 3 at
  15-min resolution; hourly aggregation gave a too-generous 3).
- **Flexible = 12 EVs (+500 %)**: the full-enrollment backstop hosts the whole
  pool with zero residual congestion, curtailing **6.1 %** of EV energy,
  shared fairly (Jain 0.9999).
- **Notice**: at σ_T = 1.5 °C day-ahead forecast error, ~97 % of curtailment
  arrives pre-notified; the backstop covers the rest (no forecast-blindness).
- **Economics**: the contract (80 $/EV·yr + 0.5 $/kWh) beats the ~520 $/yr
  annualized reinforcement up to **5 EVs (83 % adoption)** — the technical
  +200 % vs the economic +25 % is the study's two-sided headline.
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

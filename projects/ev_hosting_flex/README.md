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
| `analyze_network_characterization` | Design-day full-net sweep of technical losses, the substation constraint, and the per-transformer hosting-headroom map (before the economics) | `network_characterization.json`, figure |
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
- **AC network validation (load-matched HQ fleet)**: each of the 540 LV
  transformers is sized to its own downstream load and rated for the −20 °C
  ambient (IEEE C57.91, K≈1.4), and each LV secondary conductor is sized for
  BOTH thermal ampacity (~85 %) and voltage drop (≤1 %/conductor). The network
  verification found the SDK `load_aware` conductors undersized for the winter
  peak (40 lines over 100 % and 468 LV buses below CSA 0.917 pu before any EV,
  on the larger clusters); sizing to load clears the thermal overloads and the
  LV-secondary undervoltage. Documented modeling boundary: the residual
  deep-feeder undervoltage (~0.91 pu) is the inherent drop of the long 25 kV MV
  feeder, which a real network holds with the substation LTC / line regulators
  (not conductor gauge). Congestion, voltage drops and line overloads all
  escalate cleanly with EV adoption; the governed 6-home / 75 kVA feeder stays
  fixed.
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

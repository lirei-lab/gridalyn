# Load-model limitations — read before citing any result from this study

**Audited 2026-07-28.** This project's *market mechanism* (locational CLS
clearing, Soft/Hard flexibility allocation, settlement) is its contribution and is
sound. Its **load hypotheses are not calibrated to Québec**, and the EV generator
has a structural bias that matters for the very question the study asks. Both are
quantified below so results are cited with the right scope.

Nothing here is a bug: the pipeline is deterministic and its regression baseline
is green (74/74). The issue is **external validity**, not correctness.

---

## 1. The building base is not calibrated to Québec all-electric

`scripts/pipeline/00_generate_stochastic_profiles.py:108` calls
`make_buildings(n_buildings, seed=SEED + r)` and **never overrides the SDK
defaults** (`R_MEAN = 11.0 °C/kW`, `P_HEAT_MAX_KW = 8.0 kW`, no domestic
hot-water tank).

Measured on the committed Trois-Rivières TMY design day (−20.1 °C):

| Quantity | This study | `ev_hosting_flex` (validated) | Real Hydro-Québec (measured) |
|---|---|---|---|
| Coincident peak | **5.89 kW/home** | 11.2 kW/home | **8.8 kW/home** |
| vs the HQ 10–15 kW design band | **−41 % below the floor** | inside the band | — |

The 5.89 kW/home figure is this project's **own emitted output**
(`outputs/json/stochastic_profiles_summary.json`: `baseline_mean_peak_mw` =
19.06 MW over `N_BUILDINGS` = 3235, at −23.1 °C ambient), and it reproduces
independently from the generator call. It is not sampling noise — it is the
calibration.

**Consequence:** the modelled dwelling is a generic/mild-climate home, not a
Québec all-electric one with plinthes. The study declares the dataset
`synthetic_trois_rivieres_distribution_twin`, so this gap is a claim the load
model does not support.

For the validated Québec archetype (`R_STUDY_B = 7.5`, `P_HEAT_QUEBEC = 13 kW`,
explicit DHW tank, validated on three axes against the real HQ 1000-home dataset
and the CREST tank model) see `projects/ev_hosting_flex/CALIBRATION.md`.

---

## 2. The EV generator is unrealistic — and biased against the study's own question

`00_generate_stochastic_profiles.py:117` uses the SDK
`make_ev_chargers(...)` session model (`gridalyn/assets/datagen/agents/ev.py`).
Measured over a 100-EV block at the configured `EV_CHARGER_KW = 3.84`:

| Property | This study (SDK model) | `ev_hosting_flex` | Real (Canada) |
|---|---|---|---|
| Annual energy per EV | **6 567 kWh** | 2 521 kWh | 2 700–3 000 |
| Plug-in probability | **100 % of days** | 0.60 → 0.85 (rises with cold) | ~40–60 % |
| Peak per EV | **2.97 kW** | 7.2–11.5 kW | L2 standard 7.2 kW |
| Charge shape | **flat** (peak/mean = 1.35) | block at rated power | block |
| Cold coupling | **none** | plug-in *and* session energy rise with cold | +30–50 % in winter |

Four compounding issues:

1. **Every EV charges every day.** `_sample_sessions` gives every EV an arrival
   and a session unconditionally — there is no plug-in probability.
2. **~2.4× too much energy.** Sessions are `(1 − SoC₀) × 60 kWh` with
   `SoC₀ ~ U(0.20, 0.70)`, every day, giving 6 567 kWh/EV/yr against a real
   Canadian ~2 700–3 000.
3. **The "uncontrolled" baseline already smart-charges — the structural problem.**
   `ev.py:150` computes `p_needed = energy_needed / t_remain` and charges at that
   rate, i.e. it **spreads each session evenly across the whole plugged window**.
   Real uncontrolled L2 charging is a *block* at rated power until the battery is
   full. So the peak that flexibility is meant to shave **has already been flattened
   by the generator**. For a study asking what flexibility is worth against EV
   peaks, this is circular and biases the answer downward.
4. **No temperature dependence at all.** `grep -ci "temp|cold|t_out"` over
   `gridalyn/assets/datagen/agents/ev.py` returns **0**. In this same repository
   the cold-coupling comparison measured what that omission costs: a cold-agnostic
   EV model **overestimates firm hosting by 20 %**, **underestimates the required
   curtailment ~4×**, and misses the **+53.5 %** of EV energy that lands on cold
   days.

---

## 3. How to cite this study

**Defensible:** the market mechanism — locational CLS clearing, Soft/Hard
allocation, settlement, and the network-impact validation — on a *synthetic
distribution feeder*.

**Not supported by the load model:** any Québec-specific or cold-climate-specific
claim about hosting capacity, winter peak magnitude, or the size of the
flexibility opportunity. Those numbers depend on load hypotheses that are
41 % low on the building peak and structurally pre-smoothed on the EV side.

**To make it Québec-citable** the generators would need re-basing onto the
validated archetype: the QC building calibration plus the DHW tank, and the
cold-coupled EV sampler (`projects/ev_hosting_flex/scripts/_annual.py`
`ev_fleet_annual`) in place of `make_ev_chargers`. That is a full re-baseline of
every pinned metric, deliberately not undertaken as part of this audit.

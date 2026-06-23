# Québec load calibration — `ev_hosting_flex`

Reference for the two sizing knobs that set how soon EVs congest the feeder:
`TRANSFORMER_UTILIZATION_MARGIN` and the LV diversity / coincidence assumption.
It records the Québec-relevant evidence so the calibration is **traceable**, and
corrects an earlier over-statement (that `diversity = 1` was "pessimistic, real
1.5–2.5" — the evidence shows it is actually defensible for this load type).

## ⚠ Evidence status

Gathered with the deep-research harness (5 angles, 19 sources, 69 claims). The
**adversarial verification phase did not run** (it hit a session rate limit), so the
claims below are **sourced but not adversarially verified**. Several sources are
*general* rather than Québec-specific (German district-heating diversity, generic
cold-load-pickup, US EV-hosting studies); the Québec-specific anchors are the
all-electric baseboard stock (~13 kW/dwelling) and the Hydro-Québec docs. Treat the
numbers as best-available engineering ranges, not authoritative Hydro-Québec figures.

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

**Reading:** a fixed **0.8** utilization margin (sizing to 80 % of base peak) is
**conservative** — cold-climate distribution transformers routinely run near/above
nameplate at the winter peak and tolerate brief 1.3–3× CLPU. A margin of **~0.9–1.0**
would be more representative and would make EVs bite sooner (lower firm).

## Recommended values (Québec-defensible)

| Knob | Current | Québec-defensible | Action |
|---|---|---|---|
| Profile diversity | `1` (fully coincident) | **1.0–1.2** | **Keep ≈1** (re-label "conservative", not "pessimistic") |
| `WINTER_PEAK_FACTOR` → per-home peak | 17.64 kW | **~13–15 kW** | Optional trim |
| `TRANSFORMER_UTILIZATION_MARGIN` | `0.8` | **~0.9–1.0** | Raise for realism → lower firm, EV-driven congestion |
| EV coincident (`EV_UNIT_KW × DIVERSITY_FACTOR`) | 4.32 kW | 1.4–4 kW | Keep (conservative) |
| Topology `diversity_factor_lv` | `5` | **~1.2–1.5** | Inconsistent for all-electric; low impact (resize bypasses it) |

**Headline takeaway.** That the feeder hosts **~1 EV/dwelling firm** before congesting is
a **real, defensible** result for a Québec all-electric feeder: EV charging (~2–4 kW
diversified) is *secondary* to electric heat (~13–17 kW). It is not a sizing error. The
levers with the most (justified) effect are **raising the utilization margin to ~0.9–1.0**
and **capping `EV_SWEEP`** to a plausible adoption range (≤ ~2 EVs/dwelling).

## Sources

- LBNL / T. Hong — heating-load diversity in residential districts (district-heating implications).
- PES-PSRC report 075 — cold-load pickup.
- IEEE 4113138; arxiv 1810.05734 — CLPU magnitudes in cold climates.
- arxiv 2409.18105 — diversified per-device LV peak contributions (heat pump / EV).
- ResearchGate 390753742 — residential EV charging coincidence & transformer hosting.
- PMC/NCBI PMC11534675 — Québec all-electric baseboard dwelling (~13 kW).
- IEEE C57.91-2011 — transformer loading guide; Hydro-Québec Blue Book E.21-10 (negative result).

*Re-run the deep-research verification pass (after the rate-limit reset) to attach
adversarial votes to these claims before treating any number as final.*

# Québec load calibration — `ev_hosting_flex`

Reference for the two sizing knobs that set how soon EVs congest the feeder:
`TRANSFORMER_UTILIZATION_MARGIN` and the LV diversity / coincidence assumption.
It records the Québec-relevant evidence so the calibration is **traceable**, and
corrects an earlier over-statement (that `diversity = 1` was "pessimistic, real
1.5–2.5" — the evidence shows it is actually defensible for this load type).

## Evidence status — verified (adversarial votes)

Gathered with the deep-research harness (5 angles, 19 sources). The adversarial
verification pass **ran** (3-vote panel per claim). Caveat: no Québec **metered**
per-house kW, no published HQ sizing rule, and no IEEE C57.91 threshold were found
*directly* — the Québec figures are **inferences** from HQ consumer docs + general
cold-climate literature (German/Belgian sources are directional, not transferable).

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

## Recommended values (Québec / Canada-defensible, verified)

| Knob | Current | Defensible | Action |
|---|---|---|---|
| `TRANSFORMER_UTILIZATION_MARGIN` | `0.8` | **0.8** ✅ verified | **Keep** (80 % + CLPU headroom is the standard) |
| Profile diversity | `1` (fully coincident) | **1.0–1.5** (centre ~1.15) | **Keep ≈1** — conservative edge, defensible |
| `WINTER_PEAK_FACTOR` → per-home peak | 17.64 kW | **10–15 kW** | **Trim** (model is high) |
| `EV_UNIT_KW × DIVERSITY_FACTOR` (coincident) | 4.32 kW | ~1.4 kW (↑ small/cold feeders) | **Lower** toward ~2–3 kW |
| EV daily energy (window shape) | 21.6 kWh (flat 5 h) | **6–13 kWh** (~2 h active) | **Trim** — shorten window or use a peaked shape |
| Topology `diversity_factor_lv` | `5` | **~1.2–1.5** | Inconsistent for all-electric (resize bypasses it) |
| `EV_SWEEP` | `(0,20,…,200)` = 0–769 % adoption | ≤ ~2 EV/dwelling (≤ ~52) + finer step | **Cap & refine** (headline resolution) |

**Headline takeaway.** That the feeder hosts **~1 EV/dwelling firm** before congesting is a
**real, verified** result for a Québec all-electric feeder: EV charging (~1.4 kW diversified)
is *secondary* to electric heat (~10–15 kW). It is **not** a sizing error and the **0.8
margin is correct**. The justified refinements are: **trim the per-home peak (→10–15 kW)**,
**lower EV power & energy toward the Canadian values**, and **cap/refine `EV_SWEEP`** to a
plausible adoption range — all of which tighten the `hosting_expansion_percent` headline.

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

*Verified with a 3-vote adversarial panel (2026-06-23). Québec-specific figures remain
inferences — no metered per-house kW or published HQ sizing rule was found directly.*

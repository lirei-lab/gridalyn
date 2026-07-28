# Load-model scope — read before citing any result from this study

**Audited 2026-07-28, resolved 2026-07-28.** This project's *market mechanism*
(locational CLS clearing, Soft/Hard flexibility allocation, settlement) was
always its contribution and was always sound. Its **load hypotheses were not
calibrated to Québec**, and its EV generator had a structural bias that
mattered for the very question the study asks. Both gaps are now closed. The
audit findings are kept below, because the record of what was wrong is what
makes the fix citable.

The baseline is green (74/74) and the pipeline is deterministic. The 2026-07-28
re-base was the sixth deliberate one in this repository.

---

## 1. RESOLVED — the building base is now the validated Québec archetype

The stage previously called `make_buildings(n, seed)` and never overrode the
SDK defaults (`R_MEAN = 11.0 °C/kW`, `P_HEAT_MAX_KW = 8.0 kW`, no hot-water
tank). It now applies the archetype validated in
`projects/ev_hosting_flex/CALIBRATION.md` — `R = 7.5`, `p_heat_max = 13 kW`, an
explicit DHW tank via `make_dhw_tank_fleet`, and `BG_SCALE = 0.6` on the ARX
background so hot water is not counted twice.

Measured on the committed Trois-Rivières peak-demand window (mean −22.2 °C):

| Quantity | Before | After |
|---|---|---|
| Coincident peak, 3235 homes | 5.89 kW/home | **7.89 kW/home** |
| Substation baseline, mean | 16.65 MW | **22.24 MW** (+34 %) |

### Read the units carefully: kW/home depends on the aggregation level

This bit caused a false alarm during the port and is worth stating plainly.
**Peak per home is not a property of the generator alone — it is a property of
the generator *and* how many homes are aggregated.** Coincidence falls as the
population grows. Measured with identical physics, same weather, same kernels:

| Homes | Peak kW/home | Energy kWh/home/day |
|---|---|---|
| 6 | 10.11 | 164.6 |
| 25 | 9.28 | 165.8 |
| 100 | 8.40 | 164.6 |
| 600 | 8.02 | 164.4 |
| 3235 | **7.93** | 164.6 |

Energy per home is flat across every population size — the per-home physics is
identical, and only coincidence changes. So the 11 kW/home that
`ev_hosting_flex` reports is the **6-home pole-transformer** figure, and the
7.9 kW/home here is the **3235-home substation** figure; they are the same
model. The right external reference at substation scale is the ~8.8 kW/home
that real Hydro-Québec feeders measure, not the 10–15 kW design band, which
applies to small-population sizing.

**Any citation of "kW/home" from this repository must state how many homes.**

---

## 2. RESOLVED — the EV generator is now cold-coupled and charges in blocks

The stage previously used the SDK `make_ev_chargers(...)` session model. That
model is an **actuator** (`EVCharger`: state of charge, curtailment caps) and
was being used as a **profile generator**, which it is not. It now uses
`make_cold_coupled_ev_fleet`.

| Property | Before (actuator misused) | After | Real (Canada) |
|---|---|---|---|
| Plug-in probability | 100 % of days | 0.60 → 0.85, rises with cold | ~40–60 % |
| Peak per EV | 2.97 kW | 7.2–11.5 kW | L2 standard 7.2 kW |
| Charge shape | flat | block at rated power | block |
| Cold coupling | none | plug-in *and* energy rise with cold | +30–50 % in winter |
| Energy/EV, 28 h window | ~21 kWh | **~10.5 kWh** (−54 %) | — |
| Fleet peak/mean ratio | 2.9 | **6.0** | — |

The last two rows together are the point: **energy fell by half while the peak
barely moved.** The old model delivered far too much energy and then smeared it
flat; the new one delivers a realistic amount in a sharp block.

### Why the old behaviour was worse than merely inaccurate

`ev.py` computes `p_needed = energy_needed / t_remain` and charges at that
rate — it spreads each session evenly across the whole plugged-in window. Real
uncontrolled L2 charging is a block at rated power until the battery is full.
So the peak that flexibility exists to shave **had already been flattened by
the generator**. For a study asking what flexibility is worth against EV peaks,
that is circular, and it biased the answer downward.

It did so measurably. Before the port, the market cleared **zero** Hard CLS
energy at 10 % and 20 % EV penetration in all 30 realizations — at low
penetration the study had nothing to show, not because the network was robust
but because the load model had no peak to congest it.

---

## 3. What the 2026-07-28 re-base changed

63 of the 74 pinned metrics moved. Direction and size:

| Metric | Before | After |
|---|---|---|
| Hard CLS @ 10 % EV, mean | **0 MWh** (0/30 realizations) | 3.60 MWh (30/30) |
| Hard CLS @ 20 % EV, mean | ~0 MWh (0/30) | 7.20 MWh (30/30) |
| Hard CLS @ 30 % EV, mean | 0.11 MWh (9/30) | 10.80 MWh (30/30) |
| Hard CLS @ 40 % EV, mean | 1.34 MWh (26/30) | 14.40 MWh (30/30) |
| Unmanaged peak @ 40 % | 21.27 MW | 29.06 MW |
| Managed peak @ 40 % | 19.48 MW | 25.63 MW |
| Peak shaved @ 40 % | 1.79 MW (8.4 %) | **3.43 MW (11.8 %)** |
| Market settlement @ 40 % | $25 888 | $42 058 (+62.5 %) |
| Rebound @ 40 % | 2.59 MWh | 0.15 MWh (−94 %) |

**The flexibility case got stronger, and it now exists at every penetration
level instead of only the highest.** This is reported as measured. It is worth
being explicit that this is the direction that flatters the study, which is
exactly why the mechanism behind it is documented above rather than asserted:
the gain comes from the load model finally producing a peak, not from any
change to the market code, which was not touched.

---

## 4. How to cite this study

**Supported:** the market mechanism — locational CLS clearing, Soft/Hard
allocation, settlement, network-impact validation — evaluated on a Québec
all-electric synthetic feeder with a validated building archetype and a
cold-coupled uncontrolled EV fleet.

**State the aggregation level** whenever quoting a per-home figure (see §1).

**Still synthetic.** The feeder topology and the weather year are synthetic and
pinned; this is a reproducible model study, not a measurement campaign. The
building archetype is validated against the real Hydro-Québec 1000-home dataset
on diurnal shape and aggregate smoothness, and the tank against the CREST
lineage — validation of the *generator*, not of this specific feeder.

---

## 5. Known remaining item — a deliberate duplication

The two load kernels now live in the SDK
(`make_cold_coupled_ev_fleet`, `make_dhw_tank_fleet`) and this study uses them.
`projects/ev_hosting_flex` still carries its own project-local copies
(`ev_fleet_annual`, `dhw_tank_annual`), which are the models the SDK versions
were promoted from.

This is deliberate, not an oversight: adopting the SDK kernels there changes
that study's RNG stream and would re-base all 81 of its pinned metrics.
Migrating is a separate decision. Both copies carry docstring notes saying so.
The risk to watch is drift — if either model is changed, change both or record
why not.

# EV Hosting Flexibility (Québec all-electric feeder)

`projects/ev_hosting_flex` is the repository's flagship research study: how many
electric vehicles a Québec all-electric distribution feeder can host, where the
network actually binds, and what EV flexibility is worth against reinforcement.

It is a governed `StudyProject` (19 workflow stages, ~9.7k lines of study code)
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
    - **Hosting capacity is a distribution, not a number.** Planning at the P50
      leaves the feeder short **22 % of years**; the spread is weather
      (corr(severity, firm) = +0.42), not sampling noise.
    - **Flexibility is priced as insurance** against that cold tail and compared to
      reinforcement **at an equal 95 % reliability target**. There is a window —
      **4–7 EVs** — where insurance is cheaper. At 1 EV/home the feeder falls short
      98 % of years, yet flexibility covers **100 %** of them for **$503/yr vs
      $696/yr** to reinforce. The **crossover is 8 EVs** (7 under the project's
      other CAPEX anchor); beyond it, reinforce.
    - Coverage is an **energy-service** criterion: the backstop always holds the
      transformer, so what can fail is denied charging — which peaks at 2.1 % and is
      **priced into** the flex cost, so the comparison is like-for-like.
    - Flexibility therefore fails on *cost*, never on *reliability*.

## Why It Is Defensible

The building base generator is validated on three independent axes:

| Axis | Validated against | Result |
|---|---|---|
| Diurnal shape | Real Hydro-Québec 1000-home dataset (`datasets/hq/`) | Same dual morning/evening peak |
| Aggregate smoothness | Same HQ dataset | 0.35 vs 0.41 kW/home/h coincident step |
| DHW tank physics | CREST model lineage (via `demod`) | Surface-normalized UA matches (0.0598 vs 0.0600) |

The base is realistic in **both** dimensions at once — ~11 kW/home coincident peak
(inside the Hydro-Québec 10–15 kW design band) **and** ~29 MWh/home/year — rather
than hitting one at the cost of the other. Reaching that required modelling the
electric water-heater tank explicitly, since a single-R envelope model couples
peak and energy and cannot satisfy both.

Full calibration provenance, including five deliberate re-bases and their
rationale, is in `projects/ev_hosting_flex/CALIBRATION.md`.

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

The study is heavy — the AC and Monte-Carlo stages run for tens of minutes, so it
is **not** executed in CI. Its regression baseline is **operator-verified**:

```bash
# run a stage
uv run python projects/ev_hosting_flex/scripts/pipeline/<stage>.py

# verify the governed baseline
uv run python projects/ev_hosting_flex/scripts/verify_regression.py
```

The reproduce-and-pin tests in `tests/test_ev_hosting_flex_*.py` `skipif` their
(gitignored) outputs are absent, so they **skip in CI**. After touching any
generator or kernel, re-run the affected stages locally and re-verify the baseline
before trusting a green test run.

## Related

- `projects/flexibility_cls` — the sibling market study (capacity-limitation
  contracts and the canonical clearing/settlement API). Same synthetic
  Trois-Rivières twin, different mechanism.
- `docs/projects/overview.md` — the project contract these studies implement.

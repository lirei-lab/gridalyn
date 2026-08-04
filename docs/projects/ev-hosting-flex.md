# EV Hosting Flexibility (Québec all-electric feeder)

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

- `docs/projects/overview.md` — the project contract these studies implement.

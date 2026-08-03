# ADMM Thermal Consensus

`projects/admm_thermal_consensus` is a research study on **distributed ADMM
coordination of cold-climate electric-heating homes**, with ML imputation for
agents whose communication fails, validated on the IEEE-33 feeder with
pandapower.

It is a governed `StudyProject` with 13 workflow stages.

## What It Studies

Electric space heating in a cold climate is highly coincident — every thermostat
responds to the same weather — so it produces a sharp aggregate winter peak.
This study asks whether **distributed** coordination (ADMM consensus across
household agents, rather than a central optimiser) can flatten that peak while
respecting each home's thermal comfort, and what happens when the communication
layer degrades.

Its distinguishing contributions over the coordination literature it builds on:

- **Network validation.** The coordinated set-points are run through an actual
  power flow on the IEEE-33 feeder, rather than coordinating an aggregate signal
  in isolation.
- **Communication failure.** Agents that drop out are handled with an ML imputer,
  and the study compares imputation strategies rather than assuming ideal comms.
- **Comfort as a constraint**, validated explicitly (`comfort_validation` stage).

The scenario ladder runs from `native` (no coordination — the firm peak baseline)
through `coordinated_ideal` (perfect communications) to the degraded-comms cases.

## Running It

```bash
uv run gridalyn-project run projects/admm_thermal_consensus
```

The study is heavy and is **not** executed in CI; its regression baseline is
operator-verified.

!!! note "Test placement"
    This project's unit tests currently live inside the project
    (`scripts/admm/test_consensus.py`, `scripts/admm/test_cvxpy_reference.py`,
    `scripts/forecast/test_imputer.py`) rather than under `tests/`. There is no
    `testpaths` configuration, so pytest collects them from the repository root
    incidentally rather than by design.

## Provenance

Methodology adapted from the reja MAS/ADMM thesis and extended with power-flow
validation. The design spec is at
`docs/superpowers/specs/2026-06-25-admm-thermal-consensus-design.md`, and the
accompanying manuscript is under `manuscripts/admm_thermal_consensus/`.

## Related

- `projects/ev_hosting_flex` — the flagship study, which shows that in a Québec
  all-electric feeder the winter peak is dominated by exactly this inflexible
  heating load. The two studies attack the same physical problem from different
  angles: hosting/deferral economics versus distributed coordination.

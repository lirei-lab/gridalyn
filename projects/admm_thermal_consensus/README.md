# ADMM Thermal Consensus

Network-validated distributed ADMM coordination of cold-climate electric-heating
homes, with ML imputation of communication-failed agents, validated on the
IEEE-33 feeder with pandapower. A governed `StudyProject` with 14 workflow
stages.

## What this study asks

Electric space heating in a cold climate is highly coincident — every thermostat
responds to the same weather — so it produces a sharp aggregate winter peak.
This study asks whether **distributed** coordination (ADMM consensus across
household agents, rather than a central optimiser) can flatten that peak while
respecting each home's thermal comfort, and what happens when the communication
layer degrades.

Three things distinguish it from the coordination literature it builds on:

- **Network validation.** Coordinated set-points are run through an actual power
  flow on the IEEE-33 feeder, rather than coordinating an aggregate signal in
  isolation.
- **Communication failure.** Agents that drop out are handled with an ML
  imputer, and the study compares imputation strategies rather than assuming
  ideal comms.
- **Comfort as a constraint**, validated explicitly in its own stage.

The scenario ladder runs from `native` (no coordination — the firm peak
baseline) through `coordinated_ideal` (perfect communications) to the
degraded-comms cases.

## Running it

```bash
uv run gridalyn-project run projects/admm_thermal_consensus
```

The study is heavy and is **not** executed in CI; its regression baseline is
operator-verified.

## What it produces

Fourteen stages of governed artifacts under `outputs/`, ending in the scenario
comparison the study is written around. `realized_peak_kw_at_rep` is the metric
to read across imputation methods — see the saturation warning below before
using the probability-of-violation table instead.

## How it is verified

Power flow is the verification: coordinated set-points are checked on the
IEEE-33 feeder rather than accepted from the optimiser, and comfort is validated
in its own stage rather than assumed from the constraint. The regression
baseline is operator-verified rather than CI-run, because the study is heavy.

Its unit tests currently live inside the project
(`scripts/admm/test_consensus.py`, `scripts/admm/test_cvxpy_reference.py`,
`scripts/forecast/test_imputer.py`) rather than under `tests/`. There is no
`testpaths` configuration, so pytest collects them from the repository root
incidentally rather than by design.

## Scope and limits

Read these before quoting a number from this study.

**The coordinated schedule has almost no headroom.** With the Québec
all-electric calibration the uncoordinated winter peak loads the transformer to
~126%, and coordination brings it to ~104.5% against a 105% limit — about half a
point of margin. Every conclusion about degraded communication inherits that.

**The probability-of-violation table is saturated, not informative.** At the
representative non-responsive fraction every imputation method — including no
imputation — violates with probability 1.0, because the limit sits below the
entire realized-peak distribution. Compare methods on `realized_peak_kw_at_rep`
instead, where they separate by ~36 kW (ridge lowest, no-imputation highest).
The report carries `violation_metric_saturated` so this cannot be missed.

**The building model has no occupancy.** `minute_of_day` is accepted and ignored
by the SDK building agent, so the thermal side has no time-of-day dependence.
Against measured all-electric dwellings at matched temperature the model steps
~33% harder between 15-min samples but varies ~34% less across the day: real
homes hold long high/low regimes, this one jitters inside a narrow band. It also
inflates the forecast error the coordinator works against.

**The base is ~11% below measured at the 74-home aggregate**, after the Québec
calibration was propagated here (it was ~38% below before). The residual is the
same one `ev_hosting_flex` documents.

The percentages in these last two paragraphs come from a comparison against the
Hydro-Québec 1000-home set on temperature-matched days. That dataset is not
committed (`datasets/hq/`, gitignored), so unlike every other number on this
page they are **not** backed by a pinned baseline and cannot be re-derived from
a clone. They are reported as measurements taken during calibration, not as
study outputs.

**The transformer is sized 500 kVA, not 400.** With realistic dwellings, 74
homes would load a 400 kVA unit to ~150% — not a design any utility installs, so
the scenario would have rested on an asset that does not exist.

## Where this sits

Methodology adapted from the reja MAS/ADMM thesis, extended with power-flow
validation — the thesis coordinated only an aggregate signal. The design spec
that accompanied this study lived under `docs/superpowers/`, a tree since
deleted; the reasoning it carried is summarised above rather than linked to a
path that no longer exists.

It consumes the RC building agent from
[Assets](../../docs/components/assets.md) — see that layer's generator
comparison for why the RC model, not the EnergyPlus reference, is the right one
for a study whose flexibility comes from thermostat cycling.

`projects/ev_hosting_flex` is its sibling: the flagship study shows that in a
Québec all-electric feeder the winter peak is dominated by exactly this
inflexible heating load. The two attack the same physical problem from
different angles — hosting and deferral economics versus distributed
coordination.

### Project Developer API migration (Phase 19, 2026-08-17)

Migrated onto the Project Developer API surface (R22) in an
**identity-preserving** pass — same values, new location — so its baselines did
not move (R7):

- **Config to contract**: study knobs formerly hardcoded in `scripts/config.py`
  are now declared in `project.yaml` under `spec.inputs.studyConfig`;
  `scripts/config.py` reads them. `project.yaml` is the single source of truth;
  `config.py` remains the module the stage scripts import, exposing the same
  names and values.
- **Boilerplate removed**: the `ROOT = Path(__file__).parents[N]` +
  `sys.path.insert` pattern is gone from every script. Stages run as modules
  (`{python} -m projects.admm_thermal_consensus.scripts.pipeline.<stage>`),
  which binds the interpreter via the runner's `{python}` placeholder, puts the
  repo root on `sys.path` natively, and preserves the module identities the
  imputer pickle depends on.
- **Governed JSON IO**: stage scripts read and write JSON through
  `script.read_json` / `script.write_json` instead of hand-rolled
  `json.dumps`/`json.loads` plus path arithmetic.

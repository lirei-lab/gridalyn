# admm_thermal_consensus

Network-validated distributed ADMM coordination of cold-climate electric-heating
homes with ML imputation of communication-failed agents, validated on the
IEEE-33 feeder with pandapower.

Run the full study:

    uv run gridalyn-project run projects/admm_thermal_consensus

Methodology adapted from the reja MAS/ADMM thesis; extended with power-flow
validation (the reja work coordinated only an aggregate signal). See the design
spec in `docs/superpowers/specs/2026-06-25-admm-thermal-consensus-design.md`.

---

<!-- Merged from the former docs/projects/admm-thermal-consensus.md. The published
documentation now covers the project CONTRACT in general; per-project
detail lives with the project. -->

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

## Limitations

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

## Provenance

Methodology adapted from the reja MAS/ADMM thesis and extended with power-flow
validation.

## Project Developer API migration (Phase 19, 2026-08-17)

This study was migrated onto the Project Developer API surface (R22) in an
**identity-preserving** pass — same values, new location — so its baselines did
not move (R7):

- **Config → contract**: the study knobs formerly hardcoded in
  `scripts/config.py` are now declared in `project.yaml` under
  `spec.inputs.studyConfig`; `scripts/config.py` reads them. `project.yaml` is
  the single source of truth; `config.py` remains the module the stage scripts
  import, exposing the same names and values.
- **Boilerplate removed**: the `ROOT = Path(__file__).parents[N]` +
  `sys.path.insert` pattern is gone from every script. Stages now run as modules
  (`uv run python -m projects.admm_thermal_consensus.scripts.pipeline.<stage>`),
  which puts the repo root on `sys.path` natively and preserves the module
  identities the imputer pickle depends on.
- **Governed JSON IO**: stage scripts read/write JSON through
  `script.read_json` / `script.write_json` (ProjectScript fills) instead of
  hand-rolled `json.dumps`/`json.loads` + path arithmetic.
- The migration is identity-preserving: the committed `results_baseline.json`
  values are unchanged (compared by json_path + tolerance).

## Related

- `projects/ev_hosting_flex` — the flagship study, which shows that in a Québec
  all-electric feeder the winter peak is dominated by exactly this inflexible
  heating load. The two studies attack the same physical problem from different
  angles: hosting/deferral economics versus distributed coordination.

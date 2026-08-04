# Projects

A Gridalyn project is an executable, reproducible study. Every project — from a
two-stage smoke test to a twenty-two-stage research arc — declares the same
contract:

| File | Role |
| --- | --- |
| `project.yaml` | What the study is: problem, dataset, declared inputs, required reports. |
| `workflow.yaml` | Ordered stages, their dependencies, and the artifacts each produces. |
| `scripts/` | Thin stage scripts that call the SDK; reusable logic lives in `gridalyn/`. |
| `baselines/` | Pinned metric values that a re-run must reproduce. |
| `outputs/` | Generated reports, figures, manifests — never committed. |

Because the contract is uniform, the same commands drive every project and the
same verification decides whether a result still holds.

## The Catalog

Projects differ in what they are *for*, and that determines how much weight a
number from one of them can carry.

### Research studies

Full arcs with calibrated inputs, pinned headline metrics, and findings intended
to be cited.

| Project | Stages | Pins | What it studies |
| --- | --- | --- | --- |
| [EV Hosting Flexibility](ev-hosting-flex.md) | 22 | 81 | EV hosting capacity and flexibility across a 540-transformer Québec fleet, with the transformer rating convention as a declared axis. |
| [ADMM Thermal Consensus](admm-thermal-consensus.md) | 13 | 13 | Distributed ADMM coordination of cold-climate electric-heating homes, with ML imputation for failed communication, on the IEEE-33 feeder. |

### Contract fixtures

Small, fast projects that gate the `StudyProject → Workflow → report → baseline`
contract on every push. They run end to end in CI in about 78 seconds, which is
what makes them useful: a break in the contract shows up immediately.

| Project | Stages | Pins | Primary lesson |
| --- | --- | --- | --- |
| [Minimal Grid Project](minimal-grid-project.md) | 2 | 3 | The smallest complete project contract. |
| [IEEE 33-Bus Demo](ieee-33-demo.md) | 4 | 7 | A familiar benchmark feeder with planning-style metrics. |
| [Synthetic GeoJSON Feeder](synthetic-geojson-feeder.md) | 3 | 4 | Building a feeder from building-footprint GeoJSON. |
| [Prosumer Battery Market](prosumer-battery-market.md) | 3 | 4 | Forecast-aware real-time market with distributed prosumers. |
| [DER Voltage Optimization](der-voltage-optimization.md) | 3 | 4 | CVXPY optimization followed by pandapower verification. |
| [RL Voltage Control](rl-voltage-control-lightsim.md) | 3 | 5 | A learning-control environment over platform modeling assets. |

Start with **Minimal Grid Project** to see the contract, then **IEEE 33-Bus** for
a recognizable network.

## Running Any Project

```bash
uv run gridalyn project validate projects/<name> --check-artifacts
uv run gridalyn project plan projects/<name>
uv run gridalyn project run projects/<name>
uv run gridalyn project status projects/<name> --check-artifacts
uv run gridalyn project verify projects/<name>
```

The fixtures run in seconds. The research studies do not — they Monte-Carlo an
annual horizon and are verified by an operator rather than by CI, so their
reproduce-and-pin tests skip when their gitignored outputs are absent.

## How To Read A Project

| File or folder | What to inspect |
| --- | --- |
| `project.yaml` | Identity, problem, scenarios, experiments, inputs, required artifacts, sense checks. |
| `workflow.yaml` | Ordered stages and their commands. |
| `scripts/` | Orchestration only; reusable behaviour should come from `gridalyn/`. |
| `outputs/reports/` | Stable JSON reports for applications and publication. |
| `outputs/figures/` | Figures generated from project data. |
| `outputs/manifests/` | Run metadata and artifact inventories. |

## What Verification Means

`baselines/results_baseline.json` pins each headline metric to a JSON path in a
declared output, with a tolerance. A re-run that moves a pinned value fails, and
that failure is the point: it forces a change in results to be deliberate.

Baselines are re-based when the model changes on purpose, and each re-base is
recorded with its rationale — several are documented in
`projects/ev_hosting_flex/CALIBRATION.md`. Carrying a pinned number across a
modelling change without re-verifying it is how a study acquires a stale
headline, so the pins exist to make that hard to do quietly.

## Next Steps

- To create your own project, read the [Project Model](project-model.md) and
  [Project Template Guide](template-guide.md).
- To understand workflow stages, read the
  [Workflow YAML Reference](../workflows/workflow-yaml-reference.md).
- To connect project outputs to the dashboard, read
  [Applications And Interfaces](../platform/applications-and-interfaces.md).

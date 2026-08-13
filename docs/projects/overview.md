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
number from one of them can carry. Each project documents itself: read its
`README.md` in the repository for what it studies, how to run it, and what its
results mean. This section documents the **contract they all share**, not the
individual studies.

### Research studies

Full arcs with calibrated inputs, pinned headline metrics, and findings intended
to be cited. They Monte-Carlo an annual horizon and are verified by an operator
rather than by CI: a full `ev_hosting_flex` regeneration is roughly six hours
across 22 stages (receipt-pinned), while `admm_thermal_consensus` regenerates in
about ten minutes.

| Project | Stages | Pins |
| --- | --- | --- |
| `projects/ev_hosting_flex` | 22 | 81 |
| `projects/admm_thermal_consensus` | 13 | 14 |

### Contract fixtures

Small, fast projects that gate the `StudyProject → Workflow → report → baseline`
contract on every push. A break in the contract shows up immediately, which is
what makes them useful. They are **not** sources of citable domain findings.

| Project | Stages | Pins |
| --- | --- | --- |
| `projects/minimal_grid_project` | 2 | 3 |
| `projects/ieee_33_bus_demo` | 4 | 7 |
| `projects/synthetic_geojson_feeder` | 3 | 4 |
| `projects/prosumer_battery_market` | 3 | 4 |
| `projects/der_voltage_optimization` | 3 | 4 |
| `projects/rl_voltage_control_lightsim` | 3 | 5 |

Start with `minimal_grid_project` to see the contract in its smallest complete
form, then `ieee_33_bus_demo` for a recognizable network.

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
- To understand how a regression run decides pass/fail against a baseline,
  read [Testing And Validation](../development/testing-and-validation.md).

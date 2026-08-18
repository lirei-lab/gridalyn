# Testing And Validation

Use this page as the standard verification path before claiming that the
platform, a project workflow, or the documentation is healthy.

## Unit And Integration Tests

```bash
uv run --with pytest python -m pytest -q
```

## Documentation Build

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

## Artifact Policy

```bash
uv run gridalyn validate
```

For the stricter project-artifact and regression path:

```bash
uv run gridalyn validate --check-project-artifacts
uv run gridalyn validate \
  --project projects/ev_hosting_flex \
  --check-project-artifacts \
  --regression
```

## Larger Workflow Regression

```bash
uv run gridalyn project regression projects/ev_hosting_flex
```

## Project Sense Checks

Project validation proves that a workflow is runnable and that declared
artifacts exist. Sense checks go further: they verify that generated numbers are
plausible for the objective of each demo.

Run a sense check for one project:

```bash
uv run gridalyn project sense-check projects/rl_voltage_control_lightsim
```

The command writes:

```text
projects/<project>/outputs/reports/project_sense_check_report.json
```

Use it after regenerating project outputs. Examples of objective-level checks:

| Project | Example checks |
| --- | --- |
| `minimal_grid_project` | five buses, four lines, converged power flow, near-nominal voltage. |
| `ieee_33_bus_demo` | expected benchmark scenario set, EV peak increases demand, PV reduces net demand. |
| `synthetic_geojson_feeder` | one load per generated building, no isolated nodes, converged synthetic feeder. |
| `prosumer_battery_market` | rolling horizon is consistent, peak import does not increase, voltage remains safe. |
| `der_voltage_optimization` | solver is optimal, PV accounting balances, verified voltage limit is met. |
| `rl_voltage_control_lightsim` | LightSim2Grid backend, reward improves, control reduces voltage deviation. |

## Agent-Friendly Project Verification

Use `verify` when you want the full project ladder in one JSON payload:

```bash
uv run gridalyn project verify projects/<project>
```

It combines:

- project schema and dependency validation;
- required report and figure artifact checks;
- project status summary;
- objective-level sense checks.

To verify every governed demo project:

```bash
uv run gridalyn project verify-all
```

**Expect a non-zero exit on the current tree.** `verify-all` covers all eight
governed projects, but sense checkers are registered for the six CI fixture
studies only (`_PROJECT_CHECKERS` in `gridalyn/projects/sense_checks.py`). The two
research studies — `ev_hosting_flex` and `admm_thermal_consensus` — therefore fail
`project_has_registered_sense_checks` and the run reports `"valid": false` with
exit 1, on a clean checkout and regardless of whether their gitignored outputs are
present. Measured 2026-08-06: six projects `ok`, those two failing on that check
alone. Read the per-project entries rather than the top-level `valid`, and treat a
*seventh* failing project as the real signal.

## Project Contract Check

```bash
uv run gridalyn project validate projects/ev_hosting_flex --check-artifacts
uv run gridalyn project status projects/ev_hosting_flex --check-artifacts
```

## When To Run Which Check

| Change type | Required checks |
| --- | --- |
| Documentation-only | `mkdocs build --strict` |
| Project workflow | project validate, project status, project sense-check |
| Core Python package | pytest plus any affected project regression |
| Artifact policy or generated outputs | artifact policy check plus project status |
| Dashboard catalog or reports | dashboard/report command plus docs link check if documentation changed |
| Dashboard source | `node --test dashboard/src/*.test.js` and `npm run build` in `dashboard/` |
| Public module boundary | selected lint/import-boundary checks plus `tests/test_project_hygiene.py` |

The release checklist combines these checks in
[Release Readiness](releasing.md).

# Demo Projects

Gridalyn demos are executable projects. They are small enough to understand,
but structured with the same contract used by larger utility studies:
`project.yaml`, `workflow.yaml`, declared inputs, generated outputs, manifests,
reports, figures, and verification checks.

Use demos to learn how the platform pieces fit together before writing a new
project.

## Recommended Order

| Demo | Primary lesson | Typical output |
| --- | --- | --- |
| [Minimal Grid Project](minimal-grid-project.md) | Smallest project contract and pandapower smoke test. | One report and one figure. |
| [IEEE 33-Bus Demo](ieee-33-demo.md) | Familiar benchmark feeder with planning-style metrics. | CSV tables, JSON report, voltage figure. |
| [Synthetic GeoJSON Feeder](synthetic-geojson-feeder.md) | Build a feeder from building-footprint GeoJSON inputs. | Network artifacts and validation reports. |
| [Prosumer Battery Market](prosumer-battery-market.md) | Forecast-aware real-time market with distributed prosumers. | Market clearing and feeder verification outputs. |
| [DER Voltage Optimization](der-voltage-optimization.md) | CVXPY optimization followed by pandapower verification. | Optimized setpoints and voltage checks. |
| [RL Voltage Control With LightSim2Grid](rl-voltage-control-lightsim.md) | Learning-control environment backed by platform modeling assets. | Training trace and policy verification. |
| [Flexibility CLS](../workflows/flexibility-cls.md) | Larger flexibility operations workflow with clearing, dispatch, and reports. | Full project output tree. |

## Common Lifecycle

```bash
uv run gridalyn project validate projects/<name> --check-artifacts
uv run gridalyn project plan projects/<name>
uv run gridalyn project run projects/<name>
uv run gridalyn project status projects/<name> --check-artifacts
uv run gridalyn project verify projects/<name>
```

## How To Read A Demo

| File or folder | What to inspect |
| --- | --- |
| `project.yaml` | Identity, inputs, outputs, required artifacts, and sense checks. |
| `workflow.yaml` | Ordered stages and commands. |
| `scripts/` | Project orchestration. Reusable behavior should come from `gridalyn/`. |
| `outputs/reports/` | Stable JSON reports for applications and publication. |
| `outputs/figures/` | Figures generated from project data. |
| `outputs/manifests/` | Run metadata and artifact inventories. |

## Next Steps

- To create your own project, read the [Project Model](project-model.md) and
  [Project Template Guide](template-guide.md).
- To understand workflow stages, read the
  [Workflow YAML Reference](../workflows/workflow-yaml-reference.md).
- To connect project outputs to the dashboard, read
  [Applications And Interfaces](../platform/applications-and-interfaces.md).

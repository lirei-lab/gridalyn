# IEEE 33-Bus Demo Project

This project is a compact Gridalyn demo based on the 33-bus radial distribution
benchmark exposed by `pandapower.networks.case33bw`.

It is intentionally smaller than the EV capacity limitation reference project.
Use it to verify the project workflow contract, report contract, figure
generation, and pandapower integration without running a full digital-twin case
study.

The project also includes deterministic operational scenarios for load growth,
distributed PV, EV evening charging, and a mixed PV+EV case.

## Run

From the repository root:

```bash
uv run gridalyn project run projects/ieee_33_bus_demo
uv run gridalyn project status projects/ieee_33_bus_demo --check-artifacts
```

## Outputs

```text
outputs/data/buses.csv
outputs/data/lines.csv
outputs/data/loads.csv
outputs/data/scenarios.csv
outputs/data/scenario_results.csv
outputs/data/scenario_voltage_profiles.csv
outputs/reports/ieee33_powerflow_report.json
outputs/reports/ieee33_scenario_comparison_report.json
outputs/figures/ieee33_voltage_profile.png
outputs/figures/ieee33_scenario_voltage_comparison.png
outputs/manifests/project_run_manifest.json
```

The generated outputs are ignored by Git. Regenerate them locally when needed.

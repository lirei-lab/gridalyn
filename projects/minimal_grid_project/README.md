# Minimal Grid Project

This is the smallest complete Gridalyn project. It is meant for developers who
want to understand the platform contract before opening the larger demos.

The workflow builds a five-bus radial feeder, runs one AC power flow, writes
CSV tables, creates one JSON report, and saves one voltage-profile figure.

Run it from the repository root:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

Use this project as the first template when creating a new study. Copy the
folder, rename the project, then replace the single script with domain-specific
logic while keeping the same `project.yaml`, `workflow.yaml`, report, and
artifact structure.

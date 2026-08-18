# Quickstart

This page is the shortest path from a fresh checkout to a verified Gridalyn
platform workspace. It focuses on the platform contract first: CLI, artifact
policy, one small governed project, optional operations workflow, dashboard
readiness, and documentation.

Demo projects are executable checks for that contract. They are not the
platform identity; the reusable platform lives in the `gridalyn` SDK, canonical
artifact layout, CLI, reports, and validation rules.

## 1. Install The Workspace

From the repository root:

```bash
uv sync --extra dev
```

For library-only use, `uv sync` is enough. The `dev` extra installs the docs
and test tools used later in this guide.

Verify that the CLI is available:

```bash
uv run gridalyn --help
```

Check repository policy and project contracts:

```bash
uv run gridalyn validate
```

Expected result: `"valid": true`. If the command reports tracked generated
artifacts, read [Artifact Policy](../reference/artifact-policy.md) before
adding files to Git.

If anything looks off, inspect the installation, optional capabilities, and
workspace in one command:

```bash
uv run gridalyn doctor
```

## 2. Your First Simulation In One Command

Create and run a complete IEEE 33-bus power-flow study, including a
voltage-profile figure and a governed JSON report:

```bash
uv run gridalyn quickstart my-first-study
```

This scaffolds a project from the `powerflow-demo` template, runs its
workflow with live progress, and prints where the artifacts landed:

```text
outputs/figures/powerflow_demo_voltage_profile.png
outputs/reports/powerflow_demo_report.json
```

The same study in Python, using only top-level imports. `init_project` refuses
a target directory that already exists, so this uses a second path — run either
the CLI command above or this snippet, not both into the same directory:

```python
import gridalyn

created = gridalyn.init_project("my-second-study", template="powerflow-demo")
gridalyn.run_workflow(created.root, echo=True)
print(gridalyn.project_verify(created.root)["valid"])
```

Inside a project script, `gridalyn.project_script()` removes the remaining
boilerplate: it resolves the workspace, prepares `outputs/*`, configures
headless matplotlib, and writes reports stamped with the project name:

```python
from gridalyn.projects.scripting import project_script
from gridalyn.simulation import build_ieee33_benchmark_feeder, write_voltage_profile_figure

script = project_script()
net = build_ieee33_benchmark_feeder(run_powerflow=True)
write_voltage_profile_figure(
    net,
    script.figures_dir / "voltage_profile.png",
    title=f"{script.name} - Voltage Profile",
)
script.write_report("my_report", summary={"min_voltage_pu": float(net.res_bus.vm_pu.min())})
```

## 3. Run A Minimal Governed Project

The smallest complete project contract is:

```text
projects/minimal_grid_project/
  project.yaml
  workflow.yaml
  scripts/
  outputs/
```

Run it:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
uv run gridalyn project verify projects/minimal_grid_project
```

This proves the basic platform loop:

```text
project contract -> workflow stages -> generated artifacts -> reports -> sense checks
```

Expected outcome: a five-bus feeder, one AC power-flow run, CSV tables, one
JSON report, one voltage-profile figure, a run manifest, and a passing
project-level verification.

More detail is in [Minimal Grid Project](https://github.com/lirei-lab/gridalyn/tree/main/projects/minimal_grid_project).

## 4. Inspect The Platform Surfaces

After the minimal project passes, inspect the reusable surfaces instead of
jumping straight into a large demo:

| Surface | What to check |
| --- | --- |
| [Platform Overview](../components/overview.md) | The seven layers, the source-of-truth rule, and the reading order that walks all of them in one pass. |
| [Project Model](../components/projects.md) | The reusable `project.yaml` and `workflow.yaml` contract. |
| [Testing And Validation](../contributing/testing-and-validation.md) | Which checks to run for docs, projects, SDK changes, and release readiness. |

Read the [Components](../components/overview.md) walk end to end when you want
to understand the platform before extending it — it is the single map every
other doc links back to.

## 5. Choose One Additional Verification Path

Pick one path based on what you need to prove:

| Goal | Command | Read next |
| --- | --- | --- |
| Benchmark feeder smoke test | `uv run gridalyn project verify projects/ieee_33_bus_demo` | [IEEE 33-Bus Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/ieee_33_bus_demo) |
| Geospatial model generation | `uv run gridalyn project verify projects/synthetic_geojson_feeder` | [Synthetic GeoJSON Feeder](https://github.com/lirei-lab/gridalyn/tree/main/projects/synthetic_geojson_feeder) |
| Compact market operation | `uv run gridalyn project verify projects/prosumer_battery_market` | [Prosumer Battery Market Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/prosumer_battery_market) |
| Optimization and physical verification | `uv run gridalyn project verify projects/der_voltage_optimization` | [DER Voltage Optimization Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/der_voltage_optimization) |
| Learning-control environment | `uv run gridalyn project verify projects/rl_voltage_control_lightsim` | [RL Voltage Control With LightSim2Grid](https://github.com/lirei-lab/gridalyn/tree/main/projects/rl_voltage_control_lightsim) |
| Larger operations workflow | `uv run gridalyn project verify projects/ev_hosting_flex` | [Run Demo Projects](run-demo-projects.md) |

`verify` inspects artifacts a project has already produced; it does not run the
workflow. Precede each command above with
`uv run gridalyn project run <project>`, or `verify` exits non-zero reporting
the missing reports.

The larger EV hosting flexibility workflow is useful as an end-to-end stress
test for locational clearing, operation artifacts and figures. Run it when you
need the full arc, not as the first proof that Gridalyn works.

## 6. Validate Code And Documentation

Run the Python test suite:

```bash
uv run --with pytest python -m pytest -q
```

Build the documentation strictly:

```bash
uv run --extra docs mkdocs build --strict -f docs/mkdocs.yml
```

The generated HTML goes to `site/` and should not be committed.

## 7. Optional Application Surfaces

Build the semantic graph when you need ontology-aligned artifacts. It reads the
materialized twin — in particular
`instances/default/digital_twin/scenarios/asset_registry.parquet` — which is
git-ignored and absent from a fresh checkout, so build the twin first (see
[Digital Twin](../components/twin.md)):

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --flexibility-dir instances/default/digital_twin/flexibility \
  --timeseries-dir instances/default/digital_twin/timeseries \
  --out-dir instances/default/digital_twin/semantic

uv run gridalyn semantic validate \
  --semantic-dir instances/default/digital_twin/semantic
```

Build the dashboard only after the data contracts are valid:

```bash
npm install --prefix dashboard
npm --prefix dashboard run build
docker compose -f dashboard/docker-compose.yml up -d --build dashboard
```

Open:

```text
http://localhost:8081/
```

Dashboard details are in [Dashboard](../components/interfaces.md).

## Next Step

Read [Reading The Outputs](reading-the-outputs.md) to understand what the run
above actually wrote to disk, then [First Hour With Gridalyn](first-study.md)
for a guided platform reading path, or [Run Demo Projects](run-demo-projects.md)
when your goal is to compare executable examples. To understand the platform
itself rather than run it, go to [Components](../components/overview.md).

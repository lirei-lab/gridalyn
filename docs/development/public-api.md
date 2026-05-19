# Public API

The public API is for developers who want to build workflows, reports,
dashboards, adapters, or automation on top of Gridalyn without depending on
study-specific scripts.

New code should use the native seven-module structure:

| Module | Stable responsibility |
| --- | --- |
| `gridalyn.foundation` | Workspaces, artifact policy, reports, manifests, validation, and governance. |
| `gridalyn.twin` | Network repositories, topology, source adapters, IO helpers, and semantic graph. |
| `gridalyn.assets` | Building, EV, DER, thermal, load, and synthetic-network model generation. |
| `gridalyn.simulation` | Power-flow builders, solver adapters, network impact, and validation analytics. |
| `gridalyn.operations` | Providers, aggregators, offers, clearing, dispatch, settlement, constraints, and KPIs. |
| `gridalyn.projects` | `project.yaml`, `workflow.yaml`, workflow execution, regression, and sense checks. |
| `gridalyn.interfaces` | CLI, visualization, reporting entrypoints, and application-facing surfaces. |

## Project API

Use `gridalyn.projects` when building tooling around `project.yaml` and
`workflow.yaml`.

```python
from gridalyn import projects

created = projects.init_project("projects/my_case", name="my_case")
project = projects.load_project(created.root)
stages = projects.plan_project(project)
status = projects.project_status(project.root, check_artifacts=True)
verification = projects.project_verify(project.root)
```

Stable project imports:

| Symbol | Purpose |
| --- | --- |
| `CreatedProject` | Result object returned by project initialization. |
| `init_project` | Create a governed project workspace. |
| `list_projects` | Discover project workspaces under `projects/`. |
| `load_project` | Load a project from a workspace directory or `project.yaml`. |
| `validate_project` | Validate the project contract. |
| `plan_project` | Convert workflow metadata into executable stages. |
| `run_workflow` | Execute or dry-run project stages. |
| `project_status` | Summarize contract, stages, manifests, and required reports. |
| `project_sense_check` | Run declared and registered objective checks. |
| `project_verify` | Run contract, artifact, report, and sense-check verification for one project. |
| `project_verify_all` | Verify every governed project in the workspace. |
| `project_regression` | Run a project-local numerical regression verifier when present. |

## Network And Adapter API

Use `gridalyn.twin` when applications need topology, source adapters, or
semantic graph generation.

```python
from gridalyn import twin

repo = twin.NetworkModelRepository.from_parquet("instances/default/digital_twin/base")
model = repo.load_model()
downstream = repo.get_downstream("transformer:25")
equipment = repo.get_connected_equipment("bus:17")
integrity = repo.validate_integrity()
```

Adapter discovery uses the same module:

```python
from pathlib import Path
from gridalyn import twin

registry = twin.default_network_adapter_registry()
available = registry.list_descriptors()
adapter = registry.create(
    "synthetic_pandapower",
    cache_dir=Path("projects/flexibility_cls/outputs/cache"),
    config_path=Path("configs/grid/config.json"),
)
result = adapter.export(out_dir=Path("instances/default/digital_twin/base"), root=Path("."))
```

Current network adapter IDs include:

| Adapter ID | Source ecosystem | Source format |
| --- | --- | --- |
| `synthetic_pandapower` | `pandapower` | Synthetic pandapower cache. |
| `cim_parquet` | `cim` | Lightweight CIM-like Parquet interchange. |

The adapter contract is intentionally source-neutral: every adapter should
produce canonical base network artifacts plus validation metadata.

## Report And Governance API

Use `gridalyn.foundation` for report contracts, manifests, workspace paths, and
artifact policy checks.

```python
from gridalyn import foundation

foundation.write_report(
    "projects/my_case/outputs/reports/sample_report.json",
    metadata=foundation.ReportMetadata(report_id="sample_report", source_domain="my_case"),
    inputs=[foundation.file_reference("projects/my_case/outputs/data/results.parquet")],
    artifacts=[],
    summary={"ready": True},
    validation={"valid": True, "errors": [], "warnings": []},
)
```

Stable foundation imports include:

| Symbol | Purpose |
| --- | --- |
| `GridalynWorkspace` | Resolved workspace layout. |
| `workspace_from_path` | Resolve canonical instance, project, cache, and output paths. |
| `check_artifact_policy` | Detect generated, private, or misplaced artifacts. |
| `ReportMetadata` | Common report metadata contract. |
| `file_reference` | Build a report input/artifact file reference. |
| `build_report` | Build a canonical report object. |
| `read_json_report` | Load a JSON report from disk. |
| `validate_report` | Validate report structure and required fields. |
| `write_manifest` | Write a report manifest. |
| `write_report` | Write a report JSON file. |
| `build_model_version` | Create a governed model-version record. |
| `build_study_run` | Create a governed study-run record. |

## Operations API

Use `gridalyn.operations` when an application or workflow needs utility-facing
services instead of low-level market functions.

```python
from gridalyn import operations

events, selections, report = operations.run_flexibility_clearing_operation(
    requirements=requirements,
    providers=provider_registry,
    impact=network_impact_predictions,
    scenario_id="S4",
    dt_h=0.25,
    clearing_method="surrogate",
    model_version_id="model:sha256:...",
    study_run_id="run:...",
)
```

Wrap completed operation artifacts in an `OperationRun` for APIs, dashboards,
and audit trails:

```python
operation_run = operations.build_operation_run(
    operation_id=report["operation_context"]["operation_id"],
    operation_type="flexibility_clearing",
    scenario_id="S4",
    network_model_version_id="model:sha256:...",
    study_run_id="run:...",
    input_artifacts={"provider_registry": "instances/default/digital_twin/flexibility/provider_registry.parquet"},
    output_artifacts={"dispatch_instructions": "projects/my_case/outputs/operations/dispatch_instructions.parquet"},
    kpi_report="projects/my_case/outputs/reports/operational_kpi_report.json",
)
operations.write_operation_run("projects/my_case/outputs/operations/operation_run.json", operation_run)
```

Stable operations imports include provider registries, locational clearing,
dispatch instructions, settlement records, operation-run contracts, operational
KPI reports, and network-constraint summaries.

## Asset Modeling API

Use `gridalyn.assets` for reusable asset, building, scenario-device,
thermal-limit, and synthetic-network models. Project scripts may wrap these
functions to pin local configuration, but implementation should stay in the SDK.

```python
from gridalyn import assets

forecast = assets.build_thermal_forecast(
    336,
    resolution_minutes=5,
    s_rated_kva=15_000.0,
    theta_max=110.0,
)
metadata = assets.thermal_forecast_metadata(forecast)
```

Synthetic network generation from building footprints is also exposed here:

```python
from gridalyn import assets

result = assets.build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="projects/my_project/inputs/synthetic_network_config.json",
    out_dir="projects/my_project/outputs/cache",
)
```

## Time-Series IO API

Use `gridalyn.twin.io` when workflow code needs to read time-series artifacts
without binding itself to a specific project directory.

```python
from pathlib import Path
from gridalyn.twin.io import get_baseline_building_load_all

baseline_kw = get_baseline_building_load_all(
    data_dir=Path("projects/flexibility_cls/outputs/data"),
)
```

## Simulation API

Use `gridalyn.simulation` for solver engines and validation analytics. The SDK
keeps solver-specific dependencies behind optional extras when possible, while
the public objects remain stable.

```python
from gridalyn import assets, simulation

feeder = assets.build_voltage_control_feeder(...)
env = simulation.VoltageControlEnvironment(...)
```

See [Solver And Model Adapters](../sdk/solver-and-model-adapters.md) for the
adapter contract and optional solver capability groups.

## Semantic Graph API

Use `gridalyn.twin` or the semantic CLI to convert digital-twin artifacts into
node and edge tables.

```bash
uv run gridalyn semantic build --profile north_america
uv run gridalyn semantic validate --semantic-dir instances/default/digital_twin/semantic
```

## Boundary Rule

Reusable code belongs in the Gridalyn SDK. Project scripts may orchestrate a
study, but they should not become hidden platform APIs. When another workflow
needs the same behavior, move the behavior into `gridalyn` and keep the project
script as a thin wrapper.

## Preferred Entry Point

Prefer importing the module that owns the responsibility:

```python
from gridalyn import assets, foundation, operations, projects, simulation, twin

project = projects.load_project("projects/flexibility_cls")
workspace = foundation.workspace_from_path(".")
repository = twin.NetworkModelRepository.from_parquet("instances/default/digital_twin/base")
registry = operations.build_provider_registry(...)
```

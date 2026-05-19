# Public API

The public API is intended for developers who want to build new workflows,
reports, dashboards, or automation on top of Gridalyn without depending on
study-specific scripts.

Use `gridalyn.platform` as the stable Python entrypoint. This page documents the
intended stable surface without requiring generated API-doc tooling during the
normal docs build.

## Project API

```python
from gridalyn.platform import (
    init_project,
    load_project,
    plan_project,
    project_regression,
)

created = init_project("projects/my_case", name="my_case")
project = load_project(created.root)
stages = plan_project(project)
regression = project_regression(project.root)
```

Use this layer when building tooling around `project.yaml` and `workflow.yaml`.

### Project module reference

Stable imports from `gridalyn.platform.projects`:

| Symbol | Purpose |
| --- | --- |
| `CreatedProject` | Result object returned by project initialization. |
| `init_project` | Create a new project workspace. |
| `load_project` | Load `project.yaml` and related metadata. |
| `validate_project` | Validate the project contract. |
| `plan_project` | Convert project/workflow metadata into executable stages. |
| `run_workflow` | Execute a project workflow. |
| `project_status` | Summarize project artifact status. |
| `project_regression` | Run a project-local numerical regression verifier when present. |

## Network Model API

Use `gridalyn.network` when building analytics, dashboards, adapters, or
workflow stages that need network topology without reading Parquet tables
directly.

```python
from gridalyn.network import NetworkModelRepository

repo = NetworkModelRepository.from_parquet("instances/default/digital_twin/base")
model = repo.load_model()
downstream = repo.get_downstream("transformer:25")
feeder = repo.get_feeder("bus:3260")
equipment = repo.get_connected_equipment("bus:17")
integrity = repo.validate_integrity()
```

This layer is the first stable utility-network access point. It currently
supports static base-network artifacts and returns typed result objects for:

| Symbol | Purpose |
| --- | --- |
| `NetworkModelRepository` | Load and query a network model from Parquet artifacts. |
| `NetworkModel` | In-memory network tables plus count metadata. |
| `DownstreamAssets` | Buildings, loads, buses, lines, and transformers downstream of a transformer or feeder key. |
| `ConnectedEquipment` | Lines, transformers, buildings, and loads directly connected to a bus. |
| `NetworkIntegrityReport` | Endpoint, load, building, and connectivity validation summary. |

Consumers should prefer this repository over ad hoc joins against
`instances/default/digital_twin/base`. That keeps dashboards, market logic, semantic export, and
future real-data adapters aligned around the same topology contract.

## Base Twin Metadata API

Use `gridalyn.workflows.digital_twin.base_metadata` when a workflow writes or
validates a `instances/default/digital_twin/base` snapshot.

```python
from gridalyn.workflows.digital_twin.base_metadata import write_base_metadata

write_base_metadata(
    base_dir=Path("instances/default/digital_twin/base"),
    root=Path("."),
    config_path=Path("configs/grid/config.json"),
    config_hash="...",
    cache_dir=Path("projects/flexibility_cls/outputs/cache"),
)
```

The function reloads base Parquet artifacts through `NetworkModelRepository`
before writing `metadata.json`, so the manifest reflects the queryable model
rather than only the exporter’s in-memory state.

## Network Adapter API

Use `gridalyn.adapters.network` when a workflow needs to convert a source
network representation into the canonical `instances/default/digital_twin/base` tables.

```python
from pathlib import Path

from gridalyn.adapters.network import (
    SyntheticPandapowerAdapter,
    describe_network_source_adapter,
)
from gridalyn.adapters.registry import default_network_adapter_registry

registry = default_network_adapter_registry()
adapter = registry.create(
    "synthetic_pandapower",
    cache_dir=Path("projects/flexibility_cls/outputs/cache"),
    config_path=Path("configs/grid/config.json"),
)
descriptor = describe_network_source_adapter(adapter)
result = adapter.export(out_dir=Path("instances/default/digital_twin/base"), root=Path("."))
```

Current adapter implementations include:

| Adapter ID | Class | Source standard | Source format |
| --- | --- | --- | --- |
| `synthetic_pandapower` | `SyntheticPandapowerAdapter` | `pandapower` | `pandapower-cache` |
| `cim_parquet` | `CimParquetAdapter` | `cim` | `cim-parquet` |

`SyntheticPandapowerAdapter` turns the cached synthetic pandapower and core
graph objects into canonical base Parquet artifacts, `metadata.json`, and a
network adapter validation report. `CimParquetAdapter` reads a lightweight
CIM-like Parquet interchange profile with these source tables:

| Source table | Role |
| --- | --- |
| `connectivity_nodes.parquet` | CIM `ConnectivityNode`-like bus nodes. |
| `ac_line_segments.parquet` | CIM `ACLineSegment`-like branches. |
| `power_transformers.parquet` | CIM `PowerTransformer`-like transformer endpoints. |
| `energy_consumers.parquet` | CIM `EnergyConsumer`-like customer/load records. |

The CIM adapter is intentionally CIM-like Parquet, not a CIM RDF/XML parser.
Future GIS, OpenDSS, DMS, or full CIM RDF adapters should implement the same
`NetworkSourceAdapter` contract and produce a `NetworkSnapshot`.

Every adapter should expose stable descriptor metadata:

| Field | Purpose |
| --- | --- |
| `adapter_id` | Stable machine ID, for example `synthetic_pandapower`. |
| `source_adapter` | Human-readable adapter implementation name. |
| `source_standard` | Source ecosystem or standard, for example `pandapower`, `cim`, or `opendss`. |
| `source_format` | Concrete input format, for example `pandapower-cache`. |
| `capabilities` | Declared behaviors such as `load_snapshot`, `export_base_parquet`, and `write_validation_report`. |

Use `gridalyn.adapters.registry` when an application should discover or resolve
adapters by ID instead of importing an implementation directly:

```python
from gridalyn.adapters.registry import default_network_adapter_registry

registry = default_network_adapter_registry()
available = registry.list_descriptors()
adapter = registry.create(
    "synthetic_pandapower",
    cache_dir=Path("projects/flexibility_cls/outputs/cache"),
    config_path=Path("configs/grid/config.json"),
)
```

For CIM-like Parquet:

```python
adapter = registry.create(
    "cim_parquet",
    source_dir=Path("path/to/cim_parquet"),
)
result = adapter.export(out_dir=Path("instances/default/digital_twin/base"), root=Path("."))
```

The CLI wrapper can resolve the same adapter:

```bash
uv run python -m gridalyn.workflows.scripts.export_digital_twin_base \
  --adapter-id cim_parquet \
  --source-dir path/to/cim_parquet \
  --out-dir instances/default/digital_twin/base
```

Use `gridalyn.adapters.validation` when writing a validation report for a custom
adapter:

```python
from gridalyn.adapters.validation import write_network_adapter_validation_report

write_network_adapter_validation_report(
    path=Path("instances/default/digital_twin/reports/network_adapter_validation_report.json"),
    base_dir=Path("instances/default/digital_twin/base"),
    root=Path("."),
    source_adapter="CustomAdapter",
    source_standard="custom",
    artifact_paths=result.artifact_paths,
    metadata_path=result.metadata_path,
)
```

## Report API

```python
from gridalyn.platform import ReportMetadata, file_reference, write_report

write_report(
    "projects/my_case/outputs/reports/sample_report.json",
    metadata=ReportMetadata(report_id="sample_report", source_domain="my_case"),
    inputs=[file_reference("projects/my_case/outputs/data/results.parquet")],
    artifacts=[],
    summary={"ready": True},
    validation={"valid": True, "errors": [], "warnings": []},
)
```

Use this layer for dashboard-consumable and publication-consumable reports.

### Report module reference

Stable imports from `gridalyn.platform.reports`:

| Symbol | Purpose |
| --- | --- |
| `ReportMetadata` | Common report metadata contract. |
| `file_reference` | Build a report input/artifact file reference. |
| `build_report` | Build a canonical report object. |
| `read_json_report` | Load a JSON report from disk. |
| `validate_report` | Validate report structure and required fields. |
| `write_manifest` | Write a report manifest. |
| `write_report` | Write a report JSON file. |

## Operations API

Use the operations API when an application or workflow needs a utility-facing
service instead of a low-level market function.

```python
from gridalyn.platform import run_flexibility_clearing_operation

events, selections, report = run_flexibility_clearing_operation(
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

The facade validates the provider registry, constraint requirements, and
method-specific impact table before calling the market clearing engine. The
returned report includes:

| Section | Purpose |
| --- | --- |
| `operation_context` | Deterministic operation ID, scenario, method, market role, ontology profile, and temporal resolution. |
| `governance` | `model_version_id` and `study_run_id` traceability. |
| `validation` | Input validation result. |
| `input_summary` | Provider, constraint, impact, and aggregator counts. |

For durable platform integrations, wrap completed operation artifacts in an
`OperationRun`. This is the canonical operation execution record for APIs,
dashboards, and audit trails:

```python
from gridalyn.platform import build_operation_run, write_operation_run

operation_run = build_operation_run(
    operation_id=report["operation_context"]["operation_id"],
    operation_type="flexibility_clearing",
    scenario_id="S4",
    network_model_version_id="model:sha256:...",
    study_run_id="run:...",
    input_artifacts={"provider_registry": "instances/default/digital_twin/flexibility/provider_registry.parquet"},
    output_artifacts={"dispatch_instructions": "projects/my_case/outputs/operations/dispatch_instructions.parquet"},
    kpi_report="projects/my_case/outputs/reports/operational_kpi_report.json",
)
write_operation_run("projects/my_case/outputs/operations/operation_run.json", operation_run)
```

Stable imports from `gridalyn.platform`:

| Symbol | Purpose |
| --- | --- |
| `AggregatorPortfolio` | Scenario-specific aggregator portfolio contract. |
| `FlexibilityOffer` | Provider offer contract. |
| `DispatchInstruction` | Provider-level cleared action contract. |
| `SettlementRecord` | Settlement line contract. |
| `OperationRun` | Canonical operation execution record with lineage, outputs, KPI, validation, and status. |
| `build_aggregator_portfolios` | Build aggregator portfolio rows from a provider registry. |
| `build_provider_offers` | Build offer-book rows from a provider registry. |
| `build_dispatch_instructions` | Promote clearing selections into dispatch instruction rows. |
| `build_settlement_records` | Build settlement rows from dispatch instructions. |
| `FlexibilityOperationContext` | Operation identity and governance scope. |
| `FlexibilityOperationValidation` | Input validation result. |
| `NetworkConstraint` | Active network constraint row contract. |
| `build_operation_context` | Build deterministic context for a clearing operation. |
| `validate_flexibility_operation_inputs` | Validate tabular operation inputs. |
| `run_flexibility_clearing_operation` | Execute validated locational flexibility clearing. |
| `build_network_constraint_set` | Normalize active network constraints from requirement tables. |
| `summarize_network_constraints` | Summarize active constraints for reports and dashboards. |
| `build_operational_kpi_report` | Build a standard mechanism-intelligence KPI report. |
| `build_operation_run` | Build a canonical operation execution record. |
| `validate_operation_run` | Validate required operation lineage and artifacts. |
| `write_operation_run` | Persist an operation execution record as JSON. |

## Time-Series IO API

Use `gridalyn.io.timeseries` when workflow code needs to read Monte Carlo
Parquet outputs without binding itself to a specific project directory. Project
scripts should pass or wrap the `data_dir` explicitly.

```python
from pathlib import Path

from gridalyn.io.timeseries import get_baseline_building_load_all

baseline_kw = get_baseline_building_load_all(
    data_dir=Path("projects/flexibility_cls/outputs/data"),
)
```

Stable imports from `gridalyn.io` include `get_baseline_building_load`,
`get_baseline_building_load_all`, `get_ev_capability_load_all`, and
`get_powerflow_ext_grid_load_all`.

## Modeling API

Use `gridalyn.modeling` for reusable asset, building, scenario-device, and
thermal-limit models. Study projects may wrap these functions to pin local
configuration, but the implementation should stay in the platform package.

```python
from gridalyn.modeling import build_thermal_forecast, thermal_forecast_metadata

forecast = build_thermal_forecast(
    336,
    resolution_minutes=5,
    s_rated_kva=15_000.0,
    theta_max=110.0,
)
metadata = thermal_forecast_metadata(forecast)
```

Stable imports include `build_asset_registry`, `summarize_asset_registry`,
`synthesize_building_model_tables`, `synthesize_scenario_device_tables`,
`build_thermal_forecast`, `build_thermal_forecast_from_ambient`, and
`thermal_forecast_metadata`.

## Semantic Graph API

Use the semantic CLI or the mapping modules under `gridalyn.semantic` to convert
digital twin artifacts into node and edge tables.

```bash
uv run gridalyn semantic build --profile north_america
```

## Flexibility API

Use `gridalyn.workflows.flexibility` and `gridalyn.interfaces.cli.flexibility` for provider
registry generation, locational clearing, surrogate scoring, and pandapower
verification.

```bash
uv run gridalyn market locational-clearing --scenario-id S4
```

## Boundary Rule

Reusable code belongs in the Gridalyn SDK. Project scripts may orchestrate a study,
but they should not become hidden platform APIs. When another workflow needs the
same behavior, move the behavior into `gridalyn` and keep the project script as
a thin wrapper.

## Stable Entry Point Reference

The preferred top-level imports are:

```python
from gridalyn.platform import (
    ReportMetadata,
    build_report,
    file_reference,
    init_project,
    load_project,
    plan_project,
    project_regression,
    project_status,
    read_json_report,
    run_workflow,
    validate_project,
    validate_report,
    write_manifest,
    write_report,
)
```

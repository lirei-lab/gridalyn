# Canonical Reports

Gridalyn now treats reports as the stable contract between simulations,
figures, dashboards, and later graph/database consumers. The raw Parquet and
JSON outputs remain available for analysis, but user-facing consumers should
prefer the canonical reports when the same information exists there.

## Why Reports Exist

Project workflows and digital twin pipelines generate many artifacts:

- stochastic load samples;
- thermal forecast and dynamic line or transformer limits;
- Soft CLS market clearing;
- Hard CLS backstop dispatch;
- settlement and economic-efficiency outputs;
- dashboard scenario summaries;
- semantic graph validation outputs.

Those artifacts are valuable, but downstream tools need a stable summary layer.
Canonical reports add a small schema so dashboards, tests, audits, and later
graph/database consumers can discover metrics, provenance, and related files
without depending on one project path or one scenario naming convention.

## Locations

Project reports live under:

```text
projects/<project>/outputs/reports/
```

Common project report files include:

- `study_run_manifest.json` -- always, one per run;
- one report per artifact-producing stage, named after the stage. In
  `ev_hosting_flex` these are `annual_mc_report.json`,
  `annual_congestion_report.json`, `curtailment_contracts_report.json`,
  `curtailment_economics_report.json`, `fleet_triage_report.json`,
  `cold_coupling_report.json`, `credibility_report.json`,
  `powerflow_validation_report.json` and their siblings.

The filenames are not fixed by the platform -- the contract fixes the report
*shape*, and each stage names its own. Read a project's `outputs/reports/`
directory for the set it actually emits.

Digital twin canonical reports live under:

```text
instances/default/digital_twin/reports/canonical/
```

Current digital twin reports include:

- `digital_twin_report_manifest.json`;
- `network_capacity_report.json`;
- `scenario_registry_report.json`;
- `semantic_graph_report.json`.

## Report Contract

Every canonical report should expose the same high-level fields. The preferred
way to create them is the public foundation SDK:

```python
from gridalyn.foundation import ReportMetadata, file_reference, write_report

write_report(
    "projects/my_case/outputs/reports/sample_report.json",
    metadata=ReportMetadata(
        report_id="sample_report",
        source_domain="my_case",
        project={"name": "my_case"},
    ),
    inputs=[file_reference("projects/my_case/inputs/raw.geojson")],
    artifacts=[],
    summary={"ready": True},
    validation={"valid": True, "errors": [], "warnings": []},
)
```

The resulting JSON follows this shape:

```json
{
  "report_id": "annual_mc_report",
  "schema_version": "1.0",
  "created_at": "2026-05-10T00:00:00Z",
  "source_domain": "ev_hosting_flex",
  "project": {},
  "inputs": [],
  "artifacts": [],
  "summary": {},
  "validation": {},
  "governance": {}
}
```

Required conventions:

- `report_id` is stable and machine-readable.
- `schema_version` changes when the report shape changes.
- `inputs` include source paths plus hashes or file sizes when practical.
- `summary` contains scalar values and compact summary tables.
- `artifacts` links figures, Parquet, JSON, or text files produced by the run.
- `validation` stores pass/fail checks and warnings.

Build a manifest that indexes several reports:

```python
from gridalyn.foundation import write_manifest

write_manifest(
    "projects/my_case/outputs/manifests/report_manifest.json",
    reports=[first_report, second_report],
    root="projects/my_case",
    report_paths={
        "stage_1": "projects/my_case/outputs/reports/stage_1.json",
        "stage_2": "projects/my_case/outputs/reports/stage_2.json",
    },
)
```

## Regeneration

Build reports through the owning project workflow:

```bash
uv run gridalyn project run projects/<project>
uv run gridalyn project verify projects/<project>
```

Build digital twin reports:

```bash
uv run python -m gridalyn.interfaces.reporting.digital_twin
```

Run consistency validation:

```bash
uv run gridalyn project verify projects/<project>
```

The reports are intentionally lightweight. They should not duplicate large time
series, power-flow traces, or probability arrays. Store those in Parquet/JSON and
reference them from the report.

## Consumer Guidance

Use canonical reports for:

- dashboard cards and scenario catalog metadata;
- external review tables and figure manifests;
- CI checks that need stable counts or pass/fail status;
- cross-pipeline provenance;
- later FalkorDB or graph ingestion metadata.

Use raw Parquet or stage JSON for:

- heavy numeric analysis;
- plotting dense time series;
- rebuilding scenario outputs;
- debugging model internals.

This split keeps the reports small enough to review while preserving the
analytical fidelity of the underlying simulation files.

## Application Contract

Reports are both human review artifacts and machine-readable contracts. The
dashboard, regression checks, publication workflows, and future services should
all be able to discover results through reports and manifests.

Applications should read:

- report manifests;
- scenario summaries;
- operation scorecards;
- validation reports;
- figure inventories;
- semantic graph manifests;
- dashboard catalogs.

They should avoid reading intermediate files unless the file is documented as
part of the application contract. See [Dashboard](../platform/dashboard.md).

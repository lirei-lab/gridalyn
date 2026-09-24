# Reading The Outputs

The `minimal_grid_project` run in
[Quickstart step 3](quickstart.md#3-run-a-shipped-study-and-check-it) wrote
these files under `projects/minimal_grid_project/outputs/`. This page reads them, so the formats
specified in [Report And Run-Manifest Schema](../reference/report-schema.md)
have a concrete example before you meet them in the abstract.

```text
outputs/
  data/
    buses.csv
    lines.csv
    loads.csv
  figures/
    minimal_voltage_profile.png
  manifests/
    project_run_manifest.json
  reports/
    minimal_grid_report.json
    project_sense_check_report.json
    regression_report.json
```

The run wrote all but the last; `regression` wrote `regression_report.json`.
The first stage, `prepare_workspace`, also creates the `operations/` and
`cache/` directories every project gets.

## The manifest — what ran, and in what order

```bash
python3 -m json.tool projects/minimal_grid_project/outputs/manifests/project_run_manifest.json
```

Three stages, in order, each with its own exit code (abridged to three keys
per stage):

```text
"stages": [
  {"id": "prepare_workspace", "status": "completed", "exit_code": 0},
  {"id": "run_minimal_powerflow", "status": "completed", "exit_code": 0},
  {"id": "validate_project_outputs", "status": "completed", "exit_code": 0}
]
```

The last stage is the study's sense check; it wrote
`project_sense_check_report.json`. The overall `"status": "completed"` is true
only because every stage exited zero — one non-zero exit anywhere would have
marked both that stage and the run `"failed"`. Under `provenance`, the manifest
records three facts the run itself does not print — which power-flow backend
solved it, which macro load model the environment selects (the LightGBM model
when its runtime and packaged weights are present, the analytical fallback
otherwise), and the declared RNG seed (abridged):

```json
"provenance": {
  "powerflow_backend": {"backend_id": "pandapower_native"},
  "macro_model": {"expected": "lgbm", "lightgbm_runtime": true},
  "seeds": {"base": 7}
}
```

Two runs on two machines can be compared on these three facts without
re-running anything. Every key the manifest carries is listed under
[Run Manifest](../reference/report-schema.md#run-manifest).

## The platform report — the run's governed summary

```bash
python3 -m json.tool projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
```

This is the platform report of the `run_minimal_powerflow` stage. Three parts
matter most for a first read:

- **`artifacts`** lists every file the stage produced, each with its byte count
  and SHA-256 — not a description of the files, a fingerprint of them.
- **`summary`** is where the actual physics landed.
- **`validation`** is the stage's own verdict: here, whether the power flow
  converged. The sense check records its verdict separately, in
  `project_sense_check_report.json`.

The `summary` and `validation`, abridged to the keys this page reads:

```json
"summary": {
  "bus_count": 5,
  "converged": true,
  "min_voltage_pu": 1.0097973462536918,
  "max_line_loading_percent": 2.834697084369379
},
"validation": {"valid": true, "errors": [], "warnings": []}
```

## The data — the network itself

```python
import pandas as pd

buses = pd.read_csv("projects/minimal_grid_project/outputs/data/buses.csv")
columns = ["bus_id", "name", "vn_kv", "vm_pu", "va_degree", "p_mw", "q_mvar"]
print(buses[columns].to_string(index=False))
```

```text
 bus_id   name  vn_kv    vm_pu  va_degree      p_mw    q_mvar
      0 bus_00  12.47 1.010000   0.000000 -0.150021 -0.037264
      1 bus_01  12.47 1.009922  -0.001496  0.029972  0.007493
      2 bus_02  12.47 1.009860  -0.002692  0.044131  0.011033
      3 bus_03  12.47 1.009821  -0.003449  0.029890  0.007473
      4 bus_04  12.47 1.009797  -0.003906  0.046008  0.011502
```

The file carries a few more columns than shown — `type`, `zone`,
`in_service`, and a GeoJSON `geo` point per bus — left out here because they
are constant or long, not because they are unimportant.

Five buses, four lines, four loads — the summary's counts and this table are
the same fact told twice, once as a number and once as rows you can open in a
spreadsheet. `vm_pu` is the solved voltage in per-unit; every bus sits at
essentially 1.01 p.u., and the lowest of them (`bus_04`, 1.009797) is exactly
the `min_voltage_pu` the report quotes.

## The figure

`outputs/figures/minimal_voltage_profile.png` plots exactly the `vm_pu` column
you just read, per bus, so the number in the report and the shape of the line
are two views of the same solve — open it and confirm the flat line matches
the tight, near-1.01 voltages above.

## Where this leads

The tables you just read are pandapower's element tables joined to its
power-flow results: `buses.csv` is the bus table plus `vm_pu`, `va_degree`,
`p_mw` and `q_mvar`, and `lines.csv` carries `from_bus`/`to_bus` with the
line results. They are a study's working output, not the network model's
canonical schema: [Twin](../components/twin.md) declares that schema, with its
own column names (`from_bus_id`, `to_bus_id`). Every study writes the same
output layout, at a larger scale.

Next: [The Studies](studies.md)

# Reading The Outputs

The [Quickstart](quickstart.md) run wrote six files under
`projects/minimal_grid_project/outputs/`. This page reads them, so the shapes
introduced in [Foundation](../components/foundation.md) and
[Twin](../components/twin.md) have a concrete example before you meet them in
the abstract.

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
```

## The manifest — what ran, and in what order

```bash
python3 -m json.tool projects/minimal_grid_project/outputs/manifests/project_run_manifest.json
```

Two stages, in order, each with its own exit code:

```text
"stages": [
  {"id": "prepare_workspace", "status": "completed", "exit_code": 0},
  {"id": "run_minimal_powerflow", "status": "completed", "exit_code": 0}
]
```

The overall `"status": "completed"` is true only because both stages exited
zero — one non-zero exit anywhere would have marked both that stage and the
run `"failed"`. Under `provenance`, three facts are recorded that the run
itself does not print: which power-flow backend actually solved it
(`"backend_id": "pandapower_native"`), which macro load model was available
(`"macro_model": {"expected": "lgbm", "lightgbm_runtime": true}`), and the
declared RNG seed (`"seeds": {"base": 7}`). Two runs on two machines can be
compared on these three facts without re-running anything.

## The report — the governed summary

```bash
python3 -m json.tool projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
```

The eight fields [Foundation](../components/foundation.md) describes are all
here — `report_id`, `schema_version`, `created_at`, `source_domain`, `inputs`,
`artifacts`, `summary`, `validation` — plus `governance` and `project`. Two
parts matter most for a first read:

- **`artifacts`** lists every file this run produced, each with its byte count
  and SHA-256 — not a description of the files, a fingerprint of them.
- **`summary`** is where the actual physics landed: `"bus_count": 5`,
  `"converged": true`, `"min_voltage_pu": 1.0097973462536918`,
  `"max_line_loading_percent": 2.834697084369379`. `"validation": {"valid":
  true, "errors": [], "warnings": []}` is what a sense check
  ([Projects](../components/projects.md)) actually decided about this run.

## The data — the network itself

```bash
head -3 projects/minimal_grid_project/outputs/data/buses.csv
```
```text
bus_id,name,vn_kv,type,zone,in_service,geo,vm_pu,va_degree,p_mw,q_mvar
0,bus_00,12.47,b,,True,"{""coordinates"":[0.0,0.0], ""type"":""Point""}",1.01,0.0,-0.15002099163838176,-0.03726438609421171
1,bus_01,12.47,b,,True,"{""coordinates"":[1.0,0.15], ""type"":""Point""}",1.0099224498179593,-0.0014955731625605326,0.029971536292357482,0.0074928840730893705
```

Five buses, four lines, four loads — the summary's counts and this table are
the same fact told twice, once as a number and once as rows you can open in a
spreadsheet. `vm_pu` is the solved voltage in per-unit; both buses shown here
sit at essentially 1.01 p.u., which is why `min_voltage_pu` in the report
reads just under 1.01 rather than something alarming.

## The figure

`outputs/figures/minimal_voltage_profile.png` plots exactly the `vm_pu` column
you just read, per bus, so the number in the report and the shape of the line
are two views of the same solve — open it and confirm the flat line matches
the tight, near-1.01 voltages above.

## Where this leads

The tables you just read (`buses`, `lines`) are the same shape
[Twin](../components/twin.md) describes for the full base — this project's
`buses.csv` is a five-row instance of the schema that page states in general.
Read [Twin](../components/twin.md) next, or [Run Demo Projects](run-demo-projects.md)
to see the same six-artifact shape scale up to a real study.

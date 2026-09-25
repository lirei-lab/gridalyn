# Write Governed Reports And Figures

Every stage that produces artifacts ends by writing one **platform report**: a
JSON envelope that names the stage's inputs and outputs by hash, carries its
headline numbers in `summary`, and states its own verdict in `validation`.
This page is the recipe for writing one from a stage script, with its figures
and, when the study samples a distribution, the uncertainty of its headline
numbers. Its fields and validation rules, and how it differs from the run
manifest the runner writes and the twin's canonical reports, are in
[Report And Run-Manifest Schema](../reference/report-schema.md).

## A Stage That Reports

A stage script that samples feeder peaks, saves the draws and a histogram, and
reports the median with its 90% interval:

```python
"""Summarize sampled feeder peaks into a platform report and a figure."""

from __future__ import annotations

import random

import matplotlib.pyplot as plt

from gridalyn.foundation import build_uncertainty, estimate_from_samples
from gridalyn.projects.scripting import project_script

SEED = 7


def main() -> int:
    script = project_script()
    rng = random.Random(SEED)
    peaks_kw = [round(rng.gauss(42.0, 3.0), 3) for _ in range(200)]

    samples = script.write_json("outputs/data/peak_samples.json", {"peaks_kw": peaks_kw})

    figure = script.figures_dir / "peak_distribution.png"
    fig, ax = plt.subplots(figsize=(6.0, 3.5))
    ax.hist(peaks_kw, bins=20)
    ax.set_xlabel("Feeder peak (kW)")
    ax.set_ylabel("Draws")
    fig.tight_layout()
    fig.savefig(figure, dpi=160)
    plt.close(fig)

    estimate = estimate_from_samples(
        "peak_kw_median", peaks_kw, level=0.90, method="monte_carlo", seed=SEED
    )
    script.write_report(
        "peak_summary_report",
        artifacts=[samples, script.file_reference(figure)],
        summary={"peak_kw_median": estimate.point, "draws": len(peaks_kw)},
        validation={"valid": True, "errors": [], "warnings": []},
        uncertainty=build_uncertainty([estimate]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Declare the stage and everything it writes in the study's `workflow.yaml`:

```yaml
    - id: summarize_peaks
      needs:
        - prepare_inputs
      command: "{python} scripts/summarize_peaks.py"
      outputs:
        - outputs/data/peak_samples.json
        - outputs/figures/peak_distribution.png
        - outputs/reports/peak_summary_report.json
```

and run the study:

```bash
uv run gridalyn project run projects/my_case
```

[Build Your Own Project](build-your-own-project.md) covers creating the study
this stage lives in.

## What `script.write_report` Does

`project_script()` returns the stage's `ProjectScript`; its `write_report`
is the sanctioned way to satisfy the report contract.

- **It stamps the identity.** `report_id` is the argument; `source_domain` and
  `project.name` are the study's name from `project.yaml`.
- **It picks the path.** The report goes to
  `outputs/reports/<report_id>.json` unless you pass `path=`.
- **It validates before writing.** A payload that breaks the contract raises
  `ValueError` and nothing reaches disk.

Omitted arguments take the defaults listed under
[Fields](../reference/report-schema.md#fields). Write the report through this
call rather than assembling the JSON yourself.
`tests/test_report_contract.py` classifies every direct JSON write in the
repository, and a hand-written `*_report.json` that describes its run's own
inputs and artifacts fails it. The reverse also holds: a manifest, catalog or
other JSON artifact with its own contract is not a report, and wrapping it in
a report envelope breaks its own consumers.

## Provenance: `file_reference`

`script.file_reference(path)` returns the record a report lists under `inputs`
or `artifacts`: the path relative to the study directory with its size and
SHA-256, or `exists: false` for a missing file, so a missing input is recorded
rather than hidden ([File Records](../reference/report-schema.md#file-records)).

`script.write_json(relative, payload)` writes deterministic JSON (sorted keys,
two-space indent, trailing newline) and returns the same record for the file it
wrote. Pass that record straight into `artifacts=`; do not wrap it again.

The report the stage above writes, abridged:

```json
{
  "artifacts": [
    {
      "bytes": 2402,
      "path": "outputs/data/peak_samples.json",
      "sha256": "739d084cb502dc5ccad4bc5dd48444259ee906ded5923cd7dceecc41540a6e4e"
    },
    {
      "bytes": 18985,
      "path": "outputs/figures/peak_distribution.png",
      "sha256": "297f5176d0118c1bd916497724904bde924e47f49d74097341f71b5c6354b46c"
    }
  ],
  "report_id": "peak_summary_report",
  "source_domain": "my_case",
  "summary": {
    "draws": 200,
    "peak_kw_median": 42.4645
  },
  "uncertainty": {
    "peak_kw_median": {
      "interval": [
        36.8896,
        46.3333
      ],
      "level": 0.9,
      "method": "monte_carlo",
      "n": 200,
      "point": 42.4645,
      "seed": 7
    }
  }
}
```

## Uncertainty: Optional, And Strict When Present

A study that draws its headline number from a distribution should report the
interval rather than one realization. The block is optional; when present it
is validated, and it is kept only for numbers the study can defend.

Build it from the study's own draws, never by hand:

- `estimate_from_samples(metric, samples, *, level=0.90, method="monte_carlo",
  point=None, seed=None, note="")` takes the interval at the symmetric tails
  of `level`, with the same linear-interpolation percentile as
  `numpy.percentile`. `point` defaults to the sample median.
- `build_uncertainty([estimate, ...])` turns the estimates into the block,
  keyed by metric.

Both are importable from `gridalyn.foundation.platform`. The block must pass
the [uncertainty rules](../reference/report-schema.md#rules). Each entry must
qualify a number the report's `summary` carries, so put `estimate.point` in the
summary under the same metric name, as the stage above does.
Pass the `seed` when the study fixes one: it is what makes the interval
reproducible rather than merely reported. `build_uncertainty([])` raises, so a
stage with nothing to report omits `uncertainty=` entirely. An estimate that
names a metric the summary does not carry is refused at write time. Here, a
summary that reports `peak_kw_max` while the estimate qualifies
`peak_kw_median`:

```text
peak_summary_report: invalid uncertainty block: uncertainty.peak_kw_median qualifies a metric the summary does not carry (summary keys: peak_kw_max)
```

When a study cannot defend its interval, it leaves the block out and says why
in `validation.warnings`. `projects/measured_shadow_feeder/scripts/compare_peaks.py`
does this when its median falls outside its own bootstrap interval.

## Figures

- **Write them to `script.figures_dir`**, which is the study's
  `outputs/figures/`. Study outputs are gitignored: a figure belongs to the
  study that generated it, and presentation material links to it rather than
  carrying its own copy of the plotting code.
- **Plotting is headless.** `project_script()` switches matplotlib to the Agg
  backend and points `MPLCONFIGDIR` at the study's `outputs/cache/matplotlib`,
  so a stage never opens a window or hangs a CI runner. Close each figure after
  saving it.
- **List each figure in the report's `artifacts`** with
  `script.file_reference(figure)`, so the report fingerprints the exact image
  it describes.
- **Declare it under the stage's `outputs:`.** The runner fails a stage that
  exits zero without producing a declared output, and at the end of a run it
  records the size and SHA-256 of every figure, data file and report the study
  wrote in the run manifest's `artifacts`.

Large regenerated artifacts follow the [Artifact Policy](../reference/artifact-policy.md).

## Canonical Reports Of The Twin

A stage never writes the twin's canonical reports: `gridalyn twin build`
does, and [Canonical Reports Of The Twin](../reference/report-schema.md#canonical-reports-of-the-twin)
says what they hold, when regenerating them is refused because inputs are
missing, and how to regenerate them without rewriting tracked files.

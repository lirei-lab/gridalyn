# Feed Measured Data

The SDK ships the measured-state ingest *path*, not measured data. Feeding a
deployment's own meter or SCADA export through that path is what makes the
deployment a digital **shadow** rather than a digital model, and only for the
quantities it measures. The observation contract itself, its two producers and
the rule for what a measurement does and does not make measured, are defined
in [Twin](../components/twin.md); this guide is the recipe.

## What You Need

Two inputs, and the ingest refuses to run without either.

**A tidy measurement export.** One row per datum, with the columns
`timestamp`, `entity_id`, `quantity` and `value`, as CSV or Parquet:

- every `timestamp` carries its UTC offset. A naive timestamp is refused rather
  than localized, because the observation's `as_of` is stamped from the datum;
- `quantity` is one the contract supports: `active_power_mw` (load-positive) or
  `voltage_pu`. The unit is in the name, so a meter reading in kW or W is
  converted by you, in the open, before it becomes a row;
- each `(timestamp, entity_id, quantity)` appears once.

**A declared entity join.** Which measured entity sits on which bus of the
network model, as `entity_id` and `bus_id`. Only the operator of the observed
system knows this, and the ingest never infers it: an entity missing from the
join is an error naming the entity. Declare it one of two ways:

- as a table, `entity_join.csv` (or `.parquet`), read with
  `EntityJoin.from_frame`;
- off the semantic graph, when the graph is built with the `metering`
  capability: `query_metered_buses` follows usage point → `METERS` → load →
  `CONNECTED_TO` → bus. [Twin](../components/twin.md) shows that path end to
  end.

The same column lists and quantity set are published in every instance's
dashboard catalog under `observation.measured`, written from
`ObservationPublication` (`resolve_observation_publication`), so an operator
can read the contract off their own twin.

## Ingest

`load_measurements` reads the export, `EntityJoin` holds the join, and
`read_measured_observations` emits one `NetworkObservation` per instant with
`provenance="measured"`:

```python
import tempfile
from pathlib import Path

import pandas as pd

from gridalyn.twin import EntityJoin, load_measurements, read_measured_observations
from gridalyn.twin.observation import resolve_observation_publication

observations_dir = Path(tempfile.mkdtemp()) / "observations"
observations_dir.mkdir()

# The operator's export: tidy rows, tz-aware timestamps, kW converted to MW.
pd.DataFrame(
    {
        "timestamp": ["2019-01-17T07:00-05:00"] * 2 + ["2019-01-17T07:15-05:00"] * 2,
        "entity_id": ["meter-a", "meter-b"] * 2,
        "quantity": "active_power_mw",
        "value": [0.0042, 0.0031, 0.0045, 0.0029],
    }
).to_csv(observations_dir / "ami_export.csv", index=False)

# The declared join: which meter sits on which bus. Never inferred.
pd.DataFrame({"entity_id": ["meter-a", "meter-b"], "bus_id": ["12", "17"]}).to_csv(
    observations_dir / "entity_join.csv", index=False
)

rows = load_measurements(observations_dir / "ami_export.csv")
join = EntityJoin.from_frame(pd.read_csv(observations_dir / "entity_join.csv"))
for observation in read_measured_observations(rows, join=join):
    print(
        observation.provenance,
        observation.as_of,
        observation.bus_ids.tolist(),
        round(observation.total_active_power_mw, 4),
    )

print(resolve_observation_publication(observations_dir).provenance)
```

```text
measured 2019-01-17 12:00:00+00:00 ['12', '17'] 0.0073
measured 2019-01-17 12:15:00+00:00 ['12', '17'] 0.0074
measured
```

`as_of` is the datum's instant expressed in UTC. Where an entity did not report
a quantity at an instant, that position holds `NaN`; where no entity reported
it, the array is empty.

## Use The Observations

**What you solve from them is simulated.** A voltage or loading computed by
power flow from measured injections comes out of a solver, so it carries
`provenance="simulated"`. The report that solves on measured data names the
ingested artifact as its input through `file_reference`, which is how a reader
traces the number back to the meter; see
[Reports And Figures](reports-and-figures.md).

**A solved operating point can be written as `current`.** The snapshot's
metadata writer, `write_base_metadata(..., operational_state="current")`, and
every source adapter's `export(..., operational_state=...)` declare a snapshot
as the network's current state, and a repository reads it back as `current`
without being told. [Twin](../components/twin.md) explains how a
snapshot's operational state is resolved.

## Attach Them To An Instance

An instance reads measured data from its observations directory,
`instances/<name>/digital_twin/observations/`
(`ArtifactLayout(...).observations`):

```text
instances/<name>/digital_twin/observations/
  ami_export.csv          # timestamp, entity_id, quantity, value
  entity_join.csv         # entity_id, bus_id
```

`resolve_observation_publication` scans that directory by suffix: a file whose
stem is `entity_join` is the join, and every other `.csv` or `.parquet` counts
as a measurement export. The instance's provenance reads `measured` only when
both halves are present; exports without a join are reported as incomplete,
with the remedy. The dashboard catalog publishes that answer under
`observation`, so every number the dashboard renders says where it came from.
Regenerate the catalog as [Open The Dashboard](open-the-dashboard.md)
describes.

The measurements belong to whoever operates the observed system. No instance
in this repository carries any, and none should: keep your exports out of
version control.

## Worked Example: `measured_shadow_feeder`

The
`measured_shadow_feeder`
study runs this whole path as a study workflow: one measured week of
per-home consumption, fed into a small feeder, solved, and compared with the
same feeder driven by the synthetic load generator.

| Stage | The step of this guide it shows |
| --- | --- |
| `build_semantic_graph` | Declares one usage point per home, so the graph carries the `metering` capability. |
| `prepare_measurements` | Reads the record in its declared stored unit (`spec.inputs.measurements.storedUnit`) and converts it to MW. |
| `ingest_measured` | Reads the entity join off the graph and runs `read_measured_observations`. |
| `solve_measured` | Solves on the measured injections (simulated results) and writes the network's `current` snapshot. |
| `compare_peaks` | Reports the measured-versus-generated residual with its uncertainty. |

```bash
uv run gridalyn project run projects/measured_shadow_feeder
```

The measured record is private metered data that cannot be redistributed, so
the study is operator-verified. Where the export is absent, the run falls back
to a generated stand-in record, labels every artifact *generated*, and states
that the deployment is not a shadow; the chain and its checks run the same
way. The study writes into its own `outputs/` rather than into an instance.
Its findings, stage-by-stage artifacts and limits are in its
README, `projects/measured_shadow_feeder/README.md`.

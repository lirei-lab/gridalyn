# Operations

## What problem this layer solves

`simulation` tells you whether the network holds up physically, including how
much headroom it has left. `operations` answers the economic question sitting
on top of that: which flexibility providers get called on, at what price, to
relieve a constraint — and how the result is settled and scored afterward.
Providers, aggregators, locational clearing, dispatch, settlement and KPIs are
a first-class platform layer here, reused across every study that needs a
market, rather than glue code duplicated per study.

## The vocabulary

- **`clearing/` is the single canonical clearing surface**, and it holds
  exactly two modules today: `selection.py` (locational SELECTION —
  `build_locational_clearing`, `select_providers_for_constraint`) and
  `allocation.py` (spatial ALLOCATION — `allocate_reduction`,
  `allocate_addition_by_headroom`, mapping an aggregate target back onto
  per-load matrices). A two-stage Soft/Hard CLS engine (`engine_mode.py`) and
  a replay chain (`replay.py`) existed here through 2026-08-15 and were
  deleted as orphans of an earlier study's retirement — they are gone from
  the surface, not merely deprecated; do not document their APIs as available.
- **`FlexibilityOffer` / `AggregatorPortfolio`** — what a provider or
  aggregator declares into a clearing round.
- **`DispatchInstruction` / `SettlementRecord`** — the output of a cleared
  round and its financial close-out (`operations/domain.py`,
  `operations/settlement.py`).
- **`NetworkConstraint` / `NetworkConstraintModel`** — the constraint contracts
  clearing relieves (`operations/constraints.py`).
- **`DERVoltageDispatchConfig` / `run_der_voltage_dispatch`** —
  voltage-constrained DER dispatch (`operations/der_voltage.py`).
- **`OperationRun`** — the governed record of one operation execution
  (`operations/runs.py`).

## The contract

`build_locational_clearing(*, requirements, providers, impact, scenario_id,
dt_h, clearing_method="surrogate", max_selected_providers_per_event=1000)`
takes three DataFrames — what the network needs relieved, who can offer it,
and the impact model connecting an offer to relief — and returns a tuple of
`(selections, events, summary)`: which providers were selected, what
constraint events resulted, and a scenario-level summary dict. Nothing about
this call depends on which study invoked it; a study supplies the three
DataFrames and reads the same three-part result every other study reads.

Settlement closes the loop: `build_settlement_records` (in
`operations/domain.py`) turns cleared selections into financial records, and
`build_operational_kpi_report` (`operations/settlement.py`) scores a run —
KPIs and settlement are the same governed step for every study, not
per-study arithmetic.

## Using it

```python
import gridalyn.operations as operations

print("build_locational_clearing" in operations.__all__)
print("build_settlement_records" in operations.__all__)
```
```text
True
True
```

## Verifying it

```bash
python3 -c "
import gridalyn.operations as o
print(sorted(n for n in o.__all__ if n.startswith('build_')))" 
ls gridalyn/operations/clearing/
```

The second command lists exactly `allocation.py`, `selection.py` and
`__init__.py` — confirming the clearing surface described above, not a
remembered one.

## Where this sits

`operations` sits on [Simulation](simulation.md): a clearing round needs a
network-impact model, which only exists once a solve or a surrogate has
produced one. What builds on `operations` is [Projects](projects.md): the
layer that drives a full study — data generation, twin, simulation and
operations, in that order — as one reproducible YAML-declared run.

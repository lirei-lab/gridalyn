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
- **Closed vocabularies** (`operations/vocabulary.py`) — `provider_type`,
  `dispatch_action`, `clearing_method`, `market_role`, `operation_type` and an
  operation run's `status` are `Literal` types with `parse_*` runtime guards.
  The frozen dataclasses refuse any other value on construction, clearing
  refuses a provider of an unknown type before it can be selected, and every
  provider type maps to exactly one dispatch action. Until 2026-09-11 these
  were free strings, and an unknown provider type was dispatched a
  `soft_cls_limit` in silence. Widening a set is a deliberate edit to that
  module, made together with the producer that writes the new value.
- **Agent interaction** (`operations/interaction/`) has three parts.
  - **Roles, kept apart from parties.** `AgentRef` names an agent, its party
    and its role, and `ROLE_ALIGNMENT` aligns each role to USEF 2021 and
    OpenADR 3.1.0.
  - **Messages.** A `Message` is content-addressed and carries a FIPA
    communicative act.
  - **Two protocols, declared as state machines:**
    - `flex_trading`: UFTP 3.1.0's `FlexRequest` → `FlexOffer` → `FlexOrder` →
      `FlexSettlement`, between a distribution operator and an aggregator.
    - `dr_program`: one OpenADR 3.1.0 `event` and its `report`s. Its states
      are `notified`, `active`, `completed`, `cancelled` and `opted_out`.

  Three things OpenADR 3.1.0 lacks are `flexint:` extensions, labelled as such:
  cancellation, opt-out, and the event window in simulated time. See
  [Standards alignment](../reference/standards-alignment.md).

## The contract

`build_locational_clearing(*, requirements, providers, impact, scenario_id,
dt_h, clearing_method="surrogate", max_selected_providers_per_event=1000)`
takes three DataFrames — what the network needs relieved, who can offer it,
and the impact model connecting an offer to relief — and returns a tuple of
`(events, selections, report)`: the constraint events, which providers were
selected to relieve them, and a scenario-level report dict. Nothing about
this call depends on which study invoked it; a study supplies the three
DataFrames and reads the same three-part result every other study reads.

Settlement closes the loop: `build_settlement_records` (in
`operations/domain.py`) turns cleared selections into financial records, and
`build_operational_kpi_report` (`operations/settlement.py`) scores a run —
KPIs and settlement are the same governed step for every study, not
per-study arithmetic.

**Conversations enforce their protocol.** A `Conversation` accepts a message
only when its protocol has a transition for it. Otherwise it raises a
`ValueError` that names:

- the conversation;
- its state and time;
- the message;
- every message that state would accept.

**Messages travel in simulated time.** `MessageBus` sends messages through a
registered channel model on the simulation `EventScheduler`, so latency and
loss are recorded properties of a run rather than accidents of it.

**The log is replayable.** `write_message_log` writes every message sent, with
its outcome, as parquet, and `build_conversation_book` replays that file into
the same conversations. `write_interaction_report` emits the governed report
only after replaying the log it references. If that log differs from the run,
the report's `validation.valid` is false.

**A cleared round can be written as messages.**
`build_flex_trading_messages(events=, offers=, dispatch=, settlement=,
operator=)` turns an already-cleared round into messages, and
`run_message_transcript` delivers them. Clearing is identical with and without
this step, because it only reads those frames.

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

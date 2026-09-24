# Operations

## What problem this layer solves

`simulation` tells you whether the network holds up physically, including how
much headroom it has left. `operations` answers the economic question sitting
on top of that: which flexibility providers get called on, at what price, to
relieve a constraint — and how the result is dispatched, settled, scored and
checked afterward. Providers, aggregators, locational clearing, dispatch,
settlement, KPIs and the messages agents exchange are a platform layer here,
reused by every study that needs a market rather than rewritten per study.

## Where to import from

| Import path | What it holds |
| --- | --- |
| `gridalyn.operations` | The facade: clearing, allocation, domain records, constraints, settlement, KPIs, verification, operation runs, DER voltage dispatch, the prosumer real-time market, and the most used interaction names. Names resolve on first access. |
| `gridalyn.operations.interaction` | All of agent interaction. `Conversation`, `ROLE_ALIGNMENT`, `DemandResponseProgram`, `DemandResponseEvent`, the payload builders and the interaction vocabularies are importable only from here, not from the facade. |
| `gridalyn.operations.vocabulary` | The closed vocabularies below, with their `parse_*` guards. Not re-exported by the facade. |

## Closed vocabularies

Each vocabulary below is a `Literal` type with a `parse_*` runtime
guard in `gridalyn/operations/vocabulary.py`. The frozen dataclasses call the
guards on construction, so an unknown value is refused whether it arrives
through typed code or a table row, with a `ValueError` naming the field, the
value found and the accepted set.

| Type | Accepted values | Carried by |
| --- | --- | --- |
| `ProviderType` | `soft_cls_building`, `hard_cls_ev` | `FlexibilityOffer`, `DispatchInstruction`, the providers frame |
| `DispatchAction` | `soft_cls_limit`, `hard_cls_interrupt` | `DispatchInstruction` |
| `ClearingMethod` | `surrogate`, `topology` | `build_locational_clearing`, `FlexibilityOperationContext`, `OperationRun` |
| `MarketRole` | `dso_flexibility_clearing` | `FlexibilityOperationContext` |
| `OperationType` | `flexibility_clearing` | `OperationRun` |
| `OperationStatus` | `completed` | `OperationRun.status` |

`DISPATCH_ACTION_BY_PROVIDER_TYPE` maps each provider type to exactly one
action: `soft_cls_building` → `soft_cls_limit`, `hard_cls_ev` →
`hard_cls_interrupt`. Clearing refuses a provider of an unknown type before it
can be selected. Widening a set is a deliberate edit to that module, made
together with the producer that writes the new value.

## Locational clearing

`gridalyn/operations/clearing/` holds two modules: `selection.py` picks
providers for each constraint event, and `allocation.py` maps an aggregate
target back onto per-load matrices.

**The selection contract.**
`build_locational_clearing(*, requirements, providers, impact, scenario_id,
dt_h, clearing_method="surrogate", max_selected_providers_per_event=1000)`
takes three DataFrames — what the network needs relieved, who can offer it,
and the impact model connecting an offer to relief — and returns
`(events, selections, report)`: one row per constraint event, one row per
selected provider, and a scenario-level report dict. The call does not depend
on which study invokes it.

| Frame | Required columns |
| --- | --- |
| `requirements` | `timestep`, `constraint_id`, `required_kw` |
| `providers` | `provider_id`, `scenario_id`, `provider_type`, `available_capacity_kw`, `base_cost_per_kw_h`, `selection_priority` |
| `impact` with `clearing_method="surrogate"` | `provider_id`, `scenario_id`, `constraint_id`, `predicted_deliverability_factor`, `predicted_relief_kw`, `selection_score` |
| `impact` with `clearing_method="topology"` | `provider_id`, `scenario_id`, `constraint_id`, `sensitivity_kw_per_kw`, `available_relief_kw` |

Each event with a positive `required_kw` clears independently. Candidates are
ranked soft building flexibility before hard EV interruption, then by offer
cost per kilowatt of relief (`base_cost_per_kw_h` divided by the
deliverability factor), then `selection_priority`, then rank score, then
`provider_id`, so the order is deterministic. A provider is selected for the
smaller of its capacity and the relief still needed; what no provider covers is
the event's `shortfall_kw`.

```python
import pandas as pd

from gridalyn.operations import build_locational_clearing

requirements = pd.DataFrame(
    {"timestep": [0], "constraint_id": ["tx_1"], "required_kw": [30.0]}
)
providers = pd.DataFrame(
    {
        "provider_id": ["bldg_a", "ev_b"],
        "scenario_id": ["s1", "s1"],
        "provider_type": ["soft_cls_building", "hard_cls_ev"],
        "available_capacity_kw": [20.0, 50.0],
        "base_cost_per_kw_h": [3.0, 10.0],
        "selection_priority": [0, 0],
    }
)
impact = pd.DataFrame(
    {
        "provider_id": ["bldg_a", "ev_b"],
        "scenario_id": ["s1", "s1"],
        "constraint_id": ["tx_1", "tx_1"],
        "predicted_deliverability_factor": [1.0, 1.0],
        "predicted_relief_kw": [20.0, 50.0],
        "selection_score": [1.0, 1.0],
    }
)
events, selections, report = build_locational_clearing(
    requirements=requirements,
    providers=providers,
    impact=impact,
    scenario_id="s1",
    dt_h=0.25,
)
print(selections[["provider_id", "provider_type", "selected_kw"]].to_string(index=False))
print(events[["required_kw", "selected_relief_kw", "shortfall_kw"]].to_string(index=False))
```
```text
provider_id     provider_type  selected_kw
     bldg_a soft_cls_building         20.0
       ev_b       hard_cls_ev         10.0
 required_kw  selected_relief_kw  shortfall_kw
        30.0                30.0           0.0
```

**The full operation.** `run_flexibility_clearing_operation` takes the same
arguments plus `model_version_id` and `study_run_id`. It builds a
`FlexibilityOperationContext`, validates the three frames with
`validate_flexibility_operation_inputs` (raising `ValueError` on failure),
clears with `build_locational_clearing`, and adds to the report the dispatch
instructions, settlement records, aggregator portfolios, network constraints
and operational KPIs derived from the result.

**Inputs and outputs around the core.** `build_constraint_requirements` turns
transformer loading above a limit into the requirements frame.
`build_provider_registry` builds the providers frame, one row per controllable
building and EV, from the asset registry and its connectivity, and
`summarize_provider_registry` describes it.
`build_network_sensitivity` builds the topology impact frame (downstream
transformer sensitivity), and `select_providers_for_constraint` ranks and picks
providers for one constraint on its own. `write_locational_clearing_outputs`
writes the events, selections and report to disk.

**Spatial allocation.** `allocate_reduction` spreads an aggregate reduction
over eligible loads in proportion to their load, and
`allocate_addition_by_headroom` spreads added EV load over eligible chargers'
headroom. `apply_spatial_cls` applies aggregate soft and hard targets to
building and EV load matrices and returns a `SpatialClsResult` with the managed
loads and the curtailed and delivered kilowatts of each kind.

## Records, dispatch and settlement

The domain records are frozen dataclasses in `gridalyn/operations/domain.py`,
each with a `build_*` function that produces a DataFrame of them:

| Record | Built by | What it is |
| --- | --- | --- |
| `FlexibilityOffer` | `build_provider_offers` | What one provider offers into a round. |
| `AggregatorPortfolio` | `build_aggregator_portfolios` | The providers an aggregator represents in a scenario. |
| `DispatchInstruction` | `build_dispatch_instructions` | A cleared selection as an instruction, with the dispatch action its provider type maps to. |
| `SettlementRecord` | `build_settlement_records` | The financial close-out of one instruction. |

`FlexibilityOperationContext` (`gridalyn/operations/contracts.py`) is the
identity and governance scope of one clearing operation — operation id,
scenario, clearing method, time step, market role, semantic profile — built by
`build_operation_context`.

Constraints live in `gridalyn/operations/constraints.py`. `NetworkConstraint`
is the record of one active constraint that flexibility can clear, and
`build_network_constraint_set` / `summarize_network_constraints` build and
summarize a set of them. `NetworkConstraintModel` is different: it is a
`typing.Protocol`, the interface a network model offers to dispatch and market
simulation — a `p_limit_kw`, a `thermal_model` and a
`probabilistic_constraint_check(p_mean_kw, p_std_kw, *, ambient_c, epsilon)`
method. Any object with those members satisfies it.

`resolve_constraint_element(constraint_id, model)` turns a constraint id into a
reference. It finds the element a `transformer:`, `line:` or `bus:` id names in
a twin `NetworkModel`, with columns found through the twin schema's declared
roles. It checks that the model declares the CIM class the prefix implies, and
it returns a `ConstraintElement` with that class and the model's
`model_version_id`. An id that names nothing, or names something else, raises a
located `ValueError`. A `FlexRequest` carries its `constraint_id` as a string;
this check keeps it a reference.

## KPIs, scorecards and verification

- **KPIs.** `build_operational_kpi_report` (`gridalyn/operations/settlement.py`)
  scores a run from its events, dispatch instructions, settlement records and
  constraints, the same way for every study.
- **Scorecard.** `build_flexibility_clearing_scorecard` compares the policies
  of one scenario — unmanaged, aggregate CLS and the clearing variants whose
  reports it is given — from their pandapower-validated reports, and
  `write_flexibility_clearing_scorecard` writes it.
- **Physical verification.** `apply_locational_selections` applies
  provider-level selections to building and EV load matrices,
  `build_locational_clearing_verification_report` compares the locational
  clearing case with the unmanaged case after both are replayed on the physical
  network, and `write_locational_verification_outputs` writes the dispatch
  artifact beside it.
- **Shadow report.** `build_shadow_report` compares an aggregate dispatch with
  the providers local selection would have picked for it, without changing the
  dispatch; `write_shadow_report` writes it.
- **Consistency.** `validate_cls_output_consistency` checks that the JSON and
  parquet artifacts of one CLS run describe the same run.

## Operation artifacts and runs

`materialize_flexibility_operation_artifacts(*, root, project_id, scenario_id,
...)` reads the provider registry and the locational clearing events and
selections from the instance's flexibility directory and writes, under the
project's `outputs/`:

- `network_constraints`, `flexibility_offers`, `dispatch_instructions` and
  `settlement_records` as parquet;
- `reports/operational_kpi_report.json`, a platform report (see
  [Report And Run-Manifest Schema](../reference/report-schema.md));
- an operations catalog and an `operation_run.json`.

`OperationRun` (`gridalyn/operations/runs.py`) is that traceable record of one
operation execution: its type, status, clearing method, input and output
artifacts, KPI report and governance ids. `build_operation_run`,
`validate_operation_run` and `write_operation_run` build, check and write it,
and `OperationRunValidation` is the check's result.

## Other operations

- **DER voltage dispatch** (`gridalyn/operations/der_voltage.py`).
  `run_der_voltage_dispatch(build_feeder, der_assets, config)` solves a
  linearized, voltage-constrained PV and battery dispatch and verifies it with
  an AC power flow at full PV output and at the optimized setpoints. It needs
  `cvxpy`, from the `ops` extra. `DERVoltageDispatchConfig` holds the voltage
  band and weights, `DERVoltageDispatchResult` the tables and both network
  observations; `summarize_der_voltage_dispatch` and
  `write_der_voltage_dispatch_figure` report it. The `der_voltage_optimization`
  study uses it.
- **Prosumer real-time market** (`gridalyn/operations/prosumer_realtime.py`).
  `run_prosumer_realtime_market(*, prosumers, build_feeder, config)` runs a
  rolling-horizon uniform-price auction for prosumer batteries: for each
  interval, `build_interval_forecast` issues a forecast,
  `clear_prosumer_interval` clears that interval's battery offers against the
  import limit, and `run_prosumer_powerflow` verifies the feeder. It returns a
  `ProsumerRealtimeMarketResult` (clearing, dispatch, forecast, offers and power
  flow tables) from a `ProsumerRealtimeMarketConfig`;
  `build_prosumer_realtime_market_summary` and
  `write_prosumer_market_dispatch_figure` report it. The
  `prosumer_battery_market` study uses it.

## Agent interaction

`gridalyn.operations.interaction` models the messages agents exchange around
flexibility and demand response.

**Roles, kept apart from parties.** `AgentRef` names an agent, the party it
acts for and the role it plays, so one utility can be a distribution operator
in one conversation and a program administrator in another. `ROLE_ALIGNMENT`
aligns each role to the standards, with a dash where a standard has no such
role:

| gridalyn role | USEF 2021 | OpenADR 3.1.0 |
| --- | --- | --- |
| `distribution_operator` | DSO | — |
| `aggregator` | AGR | VEN |
| `program_administrator` | — | BL |
| `active_customer` | Active Customer | VEN |

**Messages.** A `Message` carries a FIPA communicative act and a canonical-JSON
payload, and its id is the SHA-256 of its content, so a log row edited after it
was written is refused on load.

**Protocols are declared state machines.** A `ProtocolSpec` states which
message may follow which, between which roles, with which act and payload
fields. `PROTOCOLS` holds the two shipped protocols; both start in `idle`.

`flex_trading` is one flexibility request between a distribution operator and
one aggregator, named with UFTP 3.1.0 messages. Its states are `idle`,
`requested`, `offered`, `revoked`, `ordered`, `acknowledged` and `settled`. Payloads are
gridalyn's own offer, dispatch and settlement records, not UFTP attributes, and
the acts follow FIPA's contract-net shape. An aggregator may revise its offer
while it is `offered`. UFTP has no message that rejects an offer, so an offer
that is not ordered stays `offered`.

Version 2 adds `FlexOrderResponse`, the aggregator's acknowledgement of an
order. A lost order is the only loss the operator cannot see: a lost request or
offer leaves it short of offers it knows it lacks, while a lost order leaves it
counting on relief that is not coming. An operator that counts only acknowledged
relief holds a lower bound on it. `build_order_response_payload` references the
order by its content id. UFTP's other `…Response` messages are not modelled,
because the next message in each conversation already tells the sender what
they would. The `flex_trading_congestion` study measures the difference on a
feeder over a lossy channel.

| Message | Act | From → to | State change |
| --- | --- | --- | --- |
| `FlexRequest` | `cfp` | DSO → AGR | `idle` → `requested` |
| `FlexOffer` | `propose` | AGR → DSO | `requested` or `offered` → `offered` |
| `FlexOfferRevocation` | `cancel` | AGR → DSO | `offered` → `revoked` |
| `FlexOrder` | `accept-proposal` | DSO → AGR | `offered` → `ordered` |
| `FlexOrderResponse` | `agree` | AGR → DSO | `ordered` → `acknowledged` |
| `FlexSettlement` | `inform` | DSO → AGR | `ordered` or `acknowledged` → `settled` |

`dr_program` is one OpenADR 3.1.0 `event` between the business logic and one
VEN (an aggregator or an active customer). Its states are `idle`, `notified`,
`active`, `completed`, `cancelled` and `opted_out`. Payload fields are 3.1.0's,
verbatim. What 3.1.0 lacks — cancellation, opt-out and the event window in
simulated time — is an extension with the `flexint:` prefix, and the protocol
refuses to label it otherwise:

| Message | Act | From → to | Origin | State change |
| --- | --- | --- | --- | --- |
| `event` | `inform` | BL → VEN | OpenADR 3.1.0 | `idle` → `notified`; an update keeps `notified` |
| `report` | `inform` | VEN → BL | OpenADR 3.1.0 | accepted while `active` or `completed` |
| `flexint:EventCancellation` | `cancel` | BL → VEN | extension | `idle`, `notified` or `active` → `cancelled` |
| `flexint:OptOut` | `refuse` | VEN → BL | extension | `notified` or `active` → `opted_out` |

The event payload's `flexint:activeFrom` and `flexint:activeUntil` carry the
event window in simulated time. The conversation becomes `active` and then
`completed` as its clock passes them, and the notice the event gave is
`flexint:activeFrom` minus the time the event was sent. Over a channel that
delays or loses messages, a cancellation and an opt-out can cross: the one
delivered second is absorbed by the terminal state the first produced, and
either one delivered after `completed` is absorbed there. A cancellation can
reach a VEN that never received the event, which is why `idle` accepts it.

`DemandResponseProgram` and `DemandResponseEvent` describe a program's events
(notify, start and end times, the capacity limit, an optional cancellation),
and `build_event_payload`, `build_report_payload`,
`build_cancellation_payload` and `build_opt_out_payload` write the matching
payloads. The identifiers and versions of the standards named here are recorded
in [Standards alignment](../reference/standards-alignment.md).

**Conversations enforce their protocol.** A `Conversation` accepts a message
only when its protocol has a transition for it. Otherwise it raises a
`ValueError` that names the conversation, its state and time, the message, and
every message that state would accept. `ConversationBook` holds the
conversations of a run.

**Messages travel in simulated time.** `MessageBus` sends messages through a
registered channel model (see [Simulation](simulation.md)) on the simulation
`EventScheduler`, so latency and loss are recorded properties of a run rather
than accidents of it.

**The log is replayable.** `write_message_log` writes every message sent, with
its outcome, as parquet, and `build_conversation_book` replays that file into
the same conversations. `write_interaction_report` writes the run's platform
report only after replaying the log it references; if the log differs from the
run, the report's `validation.valid` is false.

**A run states how standard it was.** `measure_standard_conformance(log)`
counts, per protocol, the messages a run sent against the protocol's own
declarations. It reports the share whose message type comes from a standard,
and the smaller share a standard-only peer could read in full: a standard
message type can still carry `flexint:` payload fields. It also names the
standard message types the run never used. `summarize_interaction` includes it
under `standard_conformance`, so every interaction report carries it.

**A cleared round can be written as messages.**
`build_flex_trading_messages(events=, offers=, dispatch=, settlement=,
operator=)` turns an already-cleared round into `flex_trading` messages, and
`run_message_transcript` delivers them. It only reads those frames, so clearing
is identical with and without this step.

## Verifying it

```bash
uv run python - <<'EOF'
import pkgutil

import gridalyn.operations.clearing as clearing
from gridalyn.operations.interaction import PROTOCOLS
from gridalyn.operations.vocabulary import DISPATCH_ACTION_BY_PROVIDER_TYPE

print(sorted(module.name for module in pkgutil.iter_modules(clearing.__path__)))
print(DISPATCH_ACTION_BY_PROVIDER_TYPE)
for protocol_id, spec in sorted(PROTOCOLS.items()):
    print(protocol_id, spec.initial, spec.states)
EOF
```
```text
['allocation', 'selection']
{'soft_cls_building': 'soft_cls_limit', 'hard_cls_ev': 'hard_cls_interrupt'}
dr_program idle ('idle', 'notified', 'active', 'completed', 'cancelled', 'opted_out')
flex_trading idle ('idle', 'requested', 'offered', 'revoked', 'ordered', 'acknowledged', 'settled')
```

The output is the clearing modules, the provider-to-action map and both
protocols' initial and full state sets, read from the code rather than from
this page.

## Where this sits

`operations` sits on [Simulation](simulation.md): a clearing round needs a
network-impact model, which only exists once a solve or a surrogate has
produced one. What builds on `operations` is [Projects](projects.md): the
layer that drives a full study — data generation, twin, simulation and
operations, in that order — as one reproducible YAML-declared run.

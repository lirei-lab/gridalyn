"""Gates for ``gridalyn.operations.interaction``: roles, messages, protocols, log.

The acceptance criteria of the interaction layer, each pinned here:

* an illegal transition fails with a *located* error -- the conversation, its
  state, the message and what the state would have accepted;
* a message log replays deterministically: from parquet, to the same
  conversations and steps the live run produced, and a tampered log is refused;
* clearing results are identical whether or not a transcript is built from them;
* the new writes need no report-contract classification, because the only JSON
  written goes through ``write_report`` -- checked with the report-contract
  test's own scanners.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import gridalyn.operations as operations
from gridalyn.foundation.platform.reports import (
    REQUIRED_REPORT_FIELDS,
    ReportMetadata,
    validate_report,
)
from gridalyn.operations import (
    build_dispatch_instructions,
    build_operation_context,
    build_provider_offers,
    build_settlement_records,
    run_flexibility_clearing_operation,
)
from gridalyn.operations.interaction import (
    ACTIVE_FROM_FIELD,
    ACTIVE_UNTIL_FIELD,
    DR_PROGRAM_PROTOCOL,
    FLEX_TRADING_PROTOCOL,
    PERFORMATIVES,
    PROTOCOL_IDS,
    PROTOCOLS,
    ROLE_ALIGNMENT,
    ROLE_IDS,
    AgentRef,
    Conversation,
    ConversationBook,
    DeadlineTransition,
    Message,
    MessageBus,
    MessageLog,
    MessageTransition,
    MessageTypeSpec,
    ProtocolSpec,
    build_conversation_book,
    build_flex_trading_messages,
    build_message,
    load_message_log,
    run_message_transcript,
    write_interaction_report,
    write_message_log,
)
from gridalyn.operations.interaction.protocols import EXTENSION_SOURCE
from gridalyn.simulation.channels import (
    BernoulliLossChannel,
    FixedLatencyChannel,
    IdealChannel,
)
from gridalyn.simulation.scheduler import EventScheduler

REPO_ROOT = Path(__file__).resolve().parents[1]

DSO = AgentRef(agent_id="dso:1", party_id="utility:1", role="distribution_operator")
AGR = AgentRef(agent_id="agr:north", party_id="agr:north", role="aggregator")
ADMIN = AgentRef(agent_id="pa:1", party_id="utility:1", role="program_administrator")
VEN = AgentRef(agent_id="ven:07", party_id="customer:07", role="active_customer")

FLEX_ID = "flex_trading:e1:agr:north"
DR_ID = "dr_program:evt-1:ven:07"


def _flex(message_type, performative, sender, receiver, payload, *, t=0.0, cid=FLEX_ID):
    return build_message(
        conversation_id=cid,
        protocol="flex_trading",
        message_type=message_type,
        performative=performative,
        sender=sender,
        receiver=receiver,
        sent_at=t,
        payload=payload,
    )


def _request(cid=FLEX_ID, t=0.0):
    payload = {
        "event_id": "e1",
        "constraint_id": "transformer:64",
        "timestep": 0,
        "required_kw": 7.0,
    }
    return _flex("FlexRequest", "cfp", DSO, AGR, payload, t=t, cid=cid)


def _offer(cid=FLEX_ID, t=0.0, sender=AGR):
    return _flex("FlexOffer", "propose", sender, DSO, {"offers": []}, t=t, cid=cid)


def _order(cid=FLEX_ID, t=0.0):
    payload = {"instructions": []}
    return _flex("FlexOrder", "accept-proposal", DSO, AGR, payload, t=t, cid=cid)


def _settlement(cid=FLEX_ID, t=0.0):
    payload = {"settlements": []}
    return _flex("FlexSettlement", "inform", DSO, AGR, payload, t=t, cid=cid)


def _dr(message_type, performative, sender, receiver, payload, *, t, cid=DR_ID):
    return build_message(
        conversation_id=cid,
        protocol="dr_program",
        message_type=message_type,
        performative=performative,
        sender=sender,
        receiver=receiver,
        sent_at=t,
        payload=payload,
    )


def _event(t, active_from, active_until, *, receiver=VEN, cid=DR_ID):
    payload = {
        "programID": "program-winter",
        "eventName": "winter-peak",
        "intervals": [{"id": 0, "payloads": [{"type": "SIMPLE", "values": [1]}]}],
        ACTIVE_FROM_FIELD: active_from,
        ACTIVE_UNTIL_FIELD: active_until,
    }
    return _dr("event", "inform", ADMIN, receiver, payload, t=t, cid=cid)


def _report(t, *, sender=VEN, cid=DR_ID):
    payload = {
        "clientID": sender.agent_id,
        "eventID": "evt-1",
        "clientName": sender.party_id,
        "resources": [],
    }
    return _dr("report", "inform", sender, ADMIN, payload, t=t, cid=cid)


def _opt_out(t):
    payload = {"eventID": "evt-1", "clientName": VEN.party_id}
    return _dr("flexint:OptOut", "refuse", VEN, ADMIN, payload, t=t)


def _cancellation(t):
    payload = {"eventID": "evt-1"}
    return _dr("flexint:EventCancellation", "cancel", ADMIN, VEN, payload, t=t)


# --- Vocabulary and roles ---------------------------------------------------


def test_role_alignment_covers_every_role_with_verified_names_only():
    assert set(ROLE_ALIGNMENT) == set(ROLE_IDS)
    # USEF 2021 and OpenADR 3.1.0 names recorded in standards-alignment.md.
    usef_2021 = {"Active Customer", "AGR", "BRP", "DSO", "TSO", "Supplier", "ESCo"}
    for role, alignment in ROLE_ALIGNMENT.items():
        assert alignment.role == role
        assert alignment.usef is None or alignment.usef in usef_2021
        assert alignment.openadr in {None, "BL", "VEN"}
    assert ROLE_ALIGNMENT["program_administrator"].openadr == "BL"
    assert ROLE_ALIGNMENT["active_customer"].usef == "Active Customer"


def test_performatives_are_the_22_fipa_acts_as_spelled():
    assert len(PERFORMATIVES) == len(set(PERFORMATIVES)) == 22
    assert {"cfp", "accept-proposal", "reject-proposal", "not-understood"} <= set(
        PERFORMATIVES
    )


def test_agent_ref_refuses_unknown_role_and_empty_ids():
    with pytest.raises(ValueError, match="role must be one of"):
        AgentRef(agent_id="a", party_id="p", role="prosumer")
    with pytest.raises(ValueError, match="AgentRef.party_id"):
        AgentRef(agent_id="a", party_id="", role="aggregator")


def test_one_party_plays_different_roles_in_different_conversations():
    book = ConversationBook()
    book.accept(_request())
    book.accept(_event(0.0, 1.0, 2.0))
    assert DSO.party_id == ADMIN.party_id
    assert book[FLEX_ID].participants["distribution_operator"] == DSO.agent_id
    assert book[DR_ID].participants["program_administrator"] == ADMIN.agent_id


# --- Messages ---------------------------------------------------------------


def test_message_id_is_derived_from_content_only():
    first = _request()
    again = _flex(
        "FlexRequest",
        "cfp",
        DSO,
        AGR,
        {
            "required_kw": 7.0,
            "timestep": 0,
            "constraint_id": "transformer:64",
            "event_id": "e1",
        },
    )
    assert first.message_id == again.message_id
    assert first.message_id.startswith("message:sha256:")
    assert _request(t=1.0).message_id != first.message_id
    numpy = pytest.importorskip("numpy")
    with_numpy = _flex(
        "FlexRequest",
        "cfp",
        DSO,
        AGR,
        {
            "event_id": "e1",
            "constraint_id": "transformer:64",
            "timestep": numpy.int64(0),
            "required_kw": numpy.float64(7.0),
        },
    )
    assert with_numpy.message_id == first.message_id


def test_message_refuses_nan_payload_and_self_address():
    with pytest.raises(
        ValueError, match="FlexRequest in conversation .*canonical JSON"
    ):
        _flex("FlexRequest", "cfp", DSO, AGR, {"required_kw": float("nan")})
    with pytest.raises(ValueError, match="to itself"):
        _flex("FlexRequest", "cfp", DSO, DSO, {})
    with pytest.raises(ValueError, match="performative must be one of"):
        _flex("FlexRequest", "call-for-proposal", DSO, AGR, {})


def test_message_record_round_trips_and_refuses_an_edited_record():
    message = _request()
    record = message.to_record()
    assert Message.from_record(record) == message
    edited = dict(record, payload_json=record["payload_json"].replace("7.0", "9.0"))
    with pytest.raises(ValueError, match="changed after it was written"):
        Message.from_record(edited)
    payload = message.payload
    payload["required_kw"] = 0.0
    assert message.payload["required_kw"] == 7.0


# --- Protocol specs ---------------------------------------------------------


def test_shipped_protocols_are_keyed_and_end_where_the_standards_end():
    assert set(PROTOCOLS) == set(PROTOCOL_IDS)
    assert FLEX_TRADING_PROTOCOL.terminal_states == ("revoked", "settled")
    assert DR_PROGRAM_PROTOCOL.terminal_states == (
        "completed",
        "cancelled",
        "opted_out",
    )


def test_extensions_are_labelled_and_standard_names_are_verified():
    uftp_3_1_0 = {
        "FlexRequest",
        "FlexOffer",
        "FlexOfferRevocation",
        "FlexOrder",
        "FlexSettlement",
        "FlexReservationUpdate",
        "D-Prognosis",
        "Metering",
    }
    flex_types = FLEX_TRADING_PROTOCOL.message_types
    assert {spec.message_type for spec in flex_types} <= uftp_3_1_0
    assert not any(spec.is_extension for spec in flex_types)
    dr_types = {spec.message_type: spec for spec in DR_PROGRAM_PROTOCOL.message_types}
    extensions = {name for name, spec in dr_types.items() if spec.is_extension}
    assert extensions == {"flexint:EventCancellation", "flexint:OptOut"}
    assert {name for name in dr_types if name not in extensions} == {"event", "report"}
    for spec in (*flex_types, *dr_types.values()):
        assert spec.is_extension == (spec.source == EXTENSION_SOURCE)


def test_malformed_protocol_lists_every_problem():
    with pytest.raises(ValueError) as caught:
        ProtocolSpec(
            protocol_id="dr_program",
            version="test",
            standard="none",
            states=("idle", "a", "b", "orphan"),
            initial="idle",
            message_types=(
                MessageTypeSpec("flexint:Go", "OpenADR 3.1.0", ("flexint:t",)),
            ),
            transitions=(
                MessageTransition(
                    "idle",
                    "flexint:Go",
                    "inform",
                    ("aggregator",),
                    ("aggregator",),
                    "a",
                ),
                MessageTransition(
                    "idle",
                    "Undeclared",
                    "inform",
                    ("aggregator",),
                    ("aggregator",),
                    "a",
                ),
            ),
            deadline_transitions=(
                DeadlineTransition("a", "flexint:t", "b"),
                DeadlineTransition("b", "flexint:t", "a"),
            ),
        )
    text = str(caught.value)
    assert "must declare source 'flexint extension'" in text
    assert "undeclared message type" in text
    assert "deadline transitions form a cycle" in text
    assert "state 'orphan' is unreachable" in text


# --- Conversations: illegal transitions fail, located ----------------------


def test_illegal_transition_names_conversation_state_message_and_allowed():
    conversation = Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID)
    conversation.accept(_request())
    order = _order()
    with pytest.raises(ValueError) as caught:
        conversation.accept(order)
    text = str(caught.value)
    assert f"conversation {FLEX_ID!r} (flex_trading v1)" in text
    assert "is in state 'requested'" in text
    assert "cannot accept FlexOrder (accept-proposal)" in text
    assert order.message_id in text
    assert "accepts: FlexOffer (propose) aggregator -> distribution_operator" in text
    assert conversation.state == "requested"


def test_conversation_refuses_wrong_act_missing_fields_and_unknown_types():
    conversation = Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID)
    conversation.accept(_request())
    wrong_act = _flex("FlexOffer", "inform", AGR, DSO, {"offers": []})
    with pytest.raises(ValueError, match="must perform 'propose'"):
        conversation.accept(wrong_act)
    with pytest.raises(ValueError, match=r"lacks required payload field\(s\) offers"):
        conversation.accept(_flex("FlexOffer", "propose", AGR, DSO, {}))
    with pytest.raises(ValueError, match="is not a message of flex_trading"):
        conversation.accept(_flex("D-Prognosis", "inform", AGR, DSO, {}))
    assert conversation.state == "requested"


def test_a_third_agent_cannot_take_a_role_already_played():
    conversation = Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID)
    conversation.accept(_request())
    rival = AgentRef(agent_id="agr:south", party_id="agr:south", role="aggregator")
    with pytest.raises(ValueError, match="'agr:north' already plays that role"):
        conversation.accept(_offer(sender=rival))


def test_a_role_the_protocol_does_not_allow_cannot_send_even_to_the_right_receiver():
    conversation = Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID)
    conversation.accept(_request())
    # The receiver's role matches the FlexOffer transition; only the sender's
    # does not, so this refusal is the sender-role check and nothing else.
    with pytest.raises(
        ValueError, match="cannot accept FlexOffer .* from active_customer"
    ):
        conversation.accept(_offer(sender=VEN))
    assert conversation.state == "requested"


def test_terminal_state_accepts_nothing_and_time_only_moves_forward():
    conversation = Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID)
    for message in (_request(), _offer(), _order(), _settlement(t=1.0)):
        conversation.accept(message)
    assert conversation.state == "settled" and conversation.is_terminal
    with pytest.raises(ValueError, match="state 'settled' accepts no message"):
        conversation.accept(_settlement(t=2.0))
    with pytest.raises(ValueError, match="before its clock"):
        conversation.advance_to(0.5)
    with pytest.raises(ValueError, match="received at 1.0, before it was sent at 3.0"):
        Conversation(FLEX_TRADING_PROTOCOL, FLEX_ID).accept(_request(t=3.0), at=1.0)


# --- dr_program: time-driven states -----------------------------------------


def test_event_becomes_active_then_completed_as_the_clock_passes_its_window():
    conversation = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    assert conversation.accept(_event(0.0, 2.0, 4.0)) == "notified"
    conversation.advance_to(1.999)
    assert conversation.state == "notified"
    conversation.advance_to(2.0)
    assert conversation.state == "active"
    assert conversation.accept(_report(3.0)) == "active"
    conversation.advance_to(5.0)
    assert conversation.state == "completed"
    assert conversation.accept(_report(6.0)) == "completed"
    triggers = [step.trigger for step in conversation.steps]
    assert triggers[1] == f"deadline:{ACTIVE_FROM_FIELD}"
    assert triggers[3] == f"deadline:{ACTIVE_UNTIL_FIELD}"
    assert [step.at for step in conversation.steps] == [0.0, 2.0, 3.0, 4.0, 6.0]


def test_an_event_announced_after_its_start_is_active_on_arrival():
    conversation = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    assert conversation.accept(_event(5.0, 3.0, 10.0)) == "active"
    assert conversation.steps[-1].at == 5.0


def test_an_event_update_moves_its_window():
    conversation = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    conversation.accept(_event(0.0, 2.0, 4.0))
    conversation.accept(_event(1.0, 6.0, 8.0))
    conversation.advance_to(5.0)
    assert conversation.state == "notified"
    assert conversation.deadlines[ACTIVE_FROM_FIELD] == 6.0


def test_opt_out_and_cancellation_end_the_event():
    opted = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    opted.accept(_event(0.0, 2.0, 4.0))
    assert opted.accept(_opt_out(1.0)) == "opted_out"
    running = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    running.accept(_event(0.0, 2.0, 4.0))
    assert running.accept(_opt_out(3.0)) == "opted_out"
    cancelled = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    cancelled.accept(_event(0.0, 2.0, 4.0))
    assert cancelled.accept(_cancellation(2.5)) == "cancelled"


def test_version_2_absorbs_the_races_of_a_lossy_channel():
    # Found by projects/dr_agent_interaction: over a lossy channel a sender acts
    # on what it knows, so these messages arrive in states version 1 refused.
    assert DR_PROGRAM_PROTOCOL.version == "2"
    never_notified = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    assert never_notified.accept(_cancellation(1.0)) == "cancelled"
    opt_out_first = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    opt_out_first.accept(_event(0.0, 2.0, 4.0))
    assert opt_out_first.accept(_opt_out(3.0)) == "opted_out"
    assert opt_out_first.accept(_cancellation(3.0)) == "opted_out"
    cancellation_first = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    cancellation_first.accept(_event(0.0, 2.0, 4.0))
    assert cancellation_first.accept(_cancellation(3.0)) == "cancelled"
    assert cancellation_first.accept(_opt_out(3.5)) == "cancelled"
    late = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    late.accept(_event(0.0, 2.0, 4.0))
    assert late.accept(_cancellation(4.5)) == "completed"
    assert late.accept(_opt_out(5.0)) == "completed"


def test_version_2_still_refuses_what_no_race_explains():
    unaware = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    with pytest.raises(ValueError, match="is in state 'idle'"):
        unaware.accept(_opt_out(1.0))
    cancelled = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    cancelled.accept(_event(0.0, 2.0, 4.0))
    cancelled.accept(_cancellation(1.0))
    with pytest.raises(ValueError, match="is in state 'cancelled'"):
        cancelled.accept(_event(1.5, 2.0, 4.0))
    notified = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    notified.accept(_event(0.0, 2.0, 4.0))
    with pytest.raises(ValueError, match="is in state 'notified'"):
        notified.accept(_report(1.0))


def test_a_deadline_must_be_a_number():
    conversation = Conversation(DR_PROGRAM_PROTOCOL, DR_ID)
    with pytest.raises(ValueError, match="a deadline must be a number"):
        conversation.accept(_event(0.0, "soon", 4.0))
    assert conversation.state == "idle"


# --- Bus and channels -------------------------------------------------------


def _dr_round(channel, *, n=60, until=4.0):
    bus = MessageBus(channel=channel)
    vens = [
        AgentRef(
            agent_id=f"ven:{i:02d}",
            party_id=f"customer:{i:02d}",
            role="active_customer",
        )
        for i in range(n)
    ]
    for ven in vens:
        bus.send(
            _event(0.0, 1.0, 3.0, receiver=ven, cid=f"dr_program:evt-1:{ven.agent_id}")
        )

    def react(message, at):
        if message.message_type == "event":
            bus.send(_report(2.0, sender=message.receiver, cid=message.conversation_id))

    bus.run_until(until, react)
    return bus


def test_bus_logs_losses_and_advances_only_delivered_conversations():
    bus = _dr_round(BernoulliLossChannel(loss_probability=0.3, seed=7, latency=0.5))
    log = bus.log
    events = [entry for entry in log.entries if entry.message.message_type == "event"]
    delivered_events = [entry for entry in events if entry.outcome == "delivered"]
    assert 0 < len(delivered_events) < len(events)
    assert log.count("lost") > 0 and log.count("in_flight") == 0
    assert len(bus.conversations) == len(delivered_events)
    assert set(bus.conversations.states().values()) == {"completed"}
    for entry in log.delivered_in_order():
        assert entry.delivered_at == entry.message.sent_at + 0.5


def test_same_seed_gives_the_same_log_and_another_seed_does_not():
    first = _dr_round(BernoulliLossChannel(loss_probability=0.3, seed=7)).log.to_frame()
    again = _dr_round(BernoulliLossChannel(loss_probability=0.3, seed=7)).log.to_frame()
    other = _dr_round(BernoulliLossChannel(loss_probability=0.3, seed=8)).log.to_frame()
    pd.testing.assert_frame_equal(first, again)
    assert list(first["outcome"]) != list(other["outcome"])


def test_deliveries_at_one_time_arrive_in_send_order():
    messages = []
    for index in range(12):
        cid = f"flex_trading:e{index}:agr:north"
        messages += [_request(cid), _offer(cid), _order(cid), _settlement(cid)]
    bus = run_message_transcript(messages)
    assert set(bus.conversations.states().values()) == {"settled"}
    arrival = [entry.message.message_id for entry in bus.log.delivered_in_order()]
    assert arrival == [message.message_id for message in messages]


def test_bus_refuses_past_sends_and_foreign_events_but_shares_a_scheduler():
    bus = MessageBus(channel=FixedLatencyChannel(latency=1.0))
    bus.send(_request(t=0.0))
    bus.run_until(5.0)
    with pytest.raises(ValueError, match="before the bus's current time 5.0"):
        bus.send(_offer(t=1.0))
    scheduler = EventScheduler()
    shared = MessageBus(scheduler=scheduler, channel=IdealChannel())
    scheduler.schedule(time=0.0, key="step:0")
    shared.send(_request())
    with pytest.raises(ValueError, match="is not a message on this bus"):
        shared.drain()
    steps = []
    scheduler.drain(lambda event: shared.deliver(event) or steps.append(event.key))
    assert shared.conversations[FLEX_ID].state == "requested"


# --- Log: deterministic replay, tamper refusal ------------------------------


def test_log_replays_from_parquet_to_the_live_conversations(tmp_path):
    bus = _dr_round(BernoulliLossChannel(loss_probability=0.3, seed=7, latency=0.5))
    path = write_message_log(tmp_path / "messages.parquet", bus.log)
    loaded = load_message_log(path)
    assert loaded.entries == bus.log.entries
    replayed = build_conversation_book(loaded, until=bus.scheduler.now)
    again = build_conversation_book(load_message_log(path), until=bus.scheduler.now)
    for key in bus.conversations:
        assert replayed[key].steps == bus.conversations[key].steps == again[key].steps
    assert list(replayed) == list(bus.conversations)


def test_a_reordered_or_renumbered_log_is_refused():
    frame = run_message_transcript([_request(), _offer()]).log.to_frame()
    swapped = frame.copy()
    swapped.loc[[0, 1], "delivery_index"] = [1, 0]
    with pytest.raises(ValueError, match="cannot accept FlexOffer"):
        build_conversation_book(MessageLog.from_frame(swapped))
    with pytest.raises(ValueError, match="numbered in send order"):
        MessageLog.from_frame(frame.iloc[[1]])
    with pytest.raises(ValueError, match="missing column"):
        MessageLog.from_frame(frame.drop(columns=["outcome"]))


# --- Clearing: transcript of a cleared round --------------------------------


def _clearing_inputs():
    providers = pd.DataFrame(
        [
            {
                "provider_id": f"provider:S4:building:{index}:soft_cls",
                "scenario_id": "S4",
                "provider_type": "soft_cls_building",
                "building_id": f"building:{index}",
                "load_id": f"load:{index}",
                "constraint_zone_id": "transformer:64",
                "available_capacity_kw": capacity,
                "base_cost_per_kw_h": cost,
                "selection_priority": 1,
                "aggregator_id": aggregator,
            }
            for index, capacity, cost, aggregator in (
                (0, 5.0, 3.0, "aggregator:S4:north"),
                (1, 4.0, 4.0, "aggregator:S4:north"),
                (3, 3.0, 9.0, "aggregator:S4:east"),
            )
        ]
    )
    requirements = pd.DataFrame(
        [
            {
                "timestep": timestep,
                "timestamp": f"2024-01-01 {19 + timestep}:00:00",
                "constraint_id": "transformer:64",
                "required_kw": 7.0,
                "overload_pctpt": 2.0,
            }
            for timestep in (0, 1)
        ]
    )
    impact = pd.DataFrame(
        [
            {
                "provider_id": f"provider:S4:building:{index}:soft_cls",
                "scenario_id": "S4",
                "provider_type": "soft_cls_building",
                "constraint_id": "transformer:64",
                "predicted_deliverability_factor": 1.0,
                "predicted_relief_kw": relief,
                "selection_score": score,
            }
            for index, relief, score in ((0, 5.0, 3.0), (1, 4.0, 2.0))
        ]
    )
    return requirements, providers, impact


def _cleared_round():
    requirements, providers, impact = _clearing_inputs()
    events, selections, report = run_flexibility_clearing_operation(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id="S4",
        dt_h=0.25,
    )
    context = build_operation_context(
        scenario_id="S4",
        clearing_method="surrogate",
        dt_h=0.25,
        requirements=requirements,
        providers=providers,
        impact=impact,
    )
    dispatch = build_dispatch_instructions(
        selections=selections, providers=providers, context=context
    )
    return {
        "events": events,
        "selections": selections,
        "report": report,
        "offers": build_provider_offers(providers, scenario_id="S4"),
        "dispatch": dispatch,
        "settlement": build_settlement_records(dispatch, dt_h=0.25),
    }


def _transcript(cleared):
    return build_flex_trading_messages(
        events=cleared["events"],
        offers=cleared["offers"],
        dispatch=cleared["dispatch"],
        settlement=cleared["settlement"],
        operator=DSO,
    )


def _without_created_at(value):
    if isinstance(value, dict):
        return {
            key: _without_created_at(item)
            for key, item in value.items()
            if key != "created_at"
        }
    if isinstance(value, list):
        return [_without_created_at(item) for item in value]
    return value


def _assert_rounds_equal(left, right, *, across_runs=False):
    for name in ("events", "selections", "offers", "dispatch", "settlement"):
        pd.testing.assert_frame_equal(left[name], right[name])
    reports = [left["report"], right["report"]]
    if across_runs:
        # The clearing report stamps its own creation time, at the top level and
        # in operation_context; two runs differ there whatever else they do.
        reports = [_without_created_at(report) for report in reports]
    texts = [json.dumps(report, sort_keys=True, default=str) for report in reports]
    assert texts[0] == texts[1]


def test_clearing_results_are_identical_with_and_without_a_transcript(tmp_path):
    without = _cleared_round()
    logged = _cleared_round()
    before = copy.deepcopy(logged)
    bus = run_message_transcript(_transcript(logged))
    path = write_message_log(tmp_path / "messages.parquet", bus.log)
    write_interaction_report(
        tmp_path / "interaction_report.json",
        log=bus.log,
        book=bus.conversations,
        log_path=path,
        metadata=ReportMetadata(
            report_id="interaction_report", source_domain="operations"
        ),
        until=bus.scheduler.now,
    )
    _assert_rounds_equal(logged, before)
    _assert_rounds_equal(logged, without, across_runs=True)
    assert len(logged["dispatch"]) > 0


def test_transcript_orders_the_selected_and_leaves_the_unselected_offer_open():
    cleared = _cleared_round()
    messages = _transcript(cleared)
    assert _transcript(_cleared_round()) == messages
    bus = run_message_transcript(messages)
    states = bus.conversations.states()
    event_ids = sorted(cleared["events"]["event_id"])
    assert states == {
        **{
            f"flex_trading:{event}:aggregator:S4:north": "settled"
            for event in event_ids
        },
        **{
            f"flex_trading:{event}:aggregator:S4:east": "offered" for event in event_ids
        },
    }
    order = next(message for message in messages if message.message_type == "FlexOrder")
    ordered_ids = [row["instruction_id"] for row in order.payload["instructions"]]
    assert set(ordered_ids) <= set(cleared["dispatch"]["instruction_id"])


def test_transcript_refuses_what_a_round_cannot_contain():
    cleared = _cleared_round()
    with pytest.raises(
        ValueError, match="requests come from a 'distribution_operator'"
    ):
        build_flex_trading_messages(**{**_frames(cleared), "operator": AGR})
    no_offers = cleared["offers"].iloc[0:0]
    with pytest.raises(ValueError, match="holds no offer of that provider"):
        build_flex_trading_messages(
            **{**_frames(cleared), "offers": no_offers, "operator": DSO}
        )
    unassigned = cleared["dispatch"].assign(aggregator_id=None)
    with pytest.raises(ValueError, match="names no aggregator_id"):
        build_flex_trading_messages(
            **{**_frames(cleared), "dispatch": unassigned, "operator": DSO}
        )


def _frames(cleared):
    return {
        name: cleared[name] for name in ("events", "offers", "dispatch", "settlement")
    }


# --- Report -----------------------------------------------------------------


def test_interaction_report_meets_the_contract_and_detects_a_log_that_differs(tmp_path):
    channel = BernoulliLossChannel(loss_probability=0.3, seed=7, latency=0.5)
    bus = _dr_round(channel)
    path = write_message_log(tmp_path / "messages.parquet", bus.log)
    metadata = ReportMetadata(
        report_id="interaction_report", source_domain="operations"
    )
    payload = write_interaction_report(
        tmp_path / "interaction_report.json",
        log=bus.log,
        book=bus.conversations,
        log_path=path,
        metadata=metadata,
        until=bus.scheduler.now,
        channel=channel.descriptor,
        root=tmp_path,
    )
    assert validate_report(payload) == []
    assert set(REQUIRED_REPORT_FIELDS) <= set(payload)
    assert payload["validation"] == {"valid": True, "errors": [], "warnings": []}
    assert payload["artifacts"][0]["path"] == "messages.parquet"
    inputs = {record["input"]: record for record in payload["inputs"]}
    assert inputs["protocol"]["protocol_id"] == "dr_program"
    assert inputs["channel_model"]["descriptor"] == channel.descriptor.as_dict()
    assert payload["summary"]["lost_message_count"] == bus.log.count("lost")
    on_disk = json.loads((tmp_path / "interaction_report.json").read_text())
    assert on_disk["summary"] == payload["summary"]

    other = _dr_round(channel, n=59)
    mismatch = write_interaction_report(
        tmp_path / "mismatch_report.json",
        log=other.log,
        book=other.conversations,
        log_path=path,
        metadata=metadata,
        until=other.scheduler.now,
    )
    assert mismatch["validation"]["valid"] is False
    errors = mismatch["validation"]["errors"]
    assert any("is not the log of this run" in error for error in errors)
    assert any("exists only in the replayed log" in error for error in errors)


def test_interaction_writes_need_no_report_contract_classification():
    from tests.test_report_contract import (
        _scan_direct_json_write_sites,
        _scan_helper_routed_write_sites,
    )

    direct = _scan_direct_json_write_sites()
    routed = _scan_helper_routed_write_sites()
    assert direct, "the scanner found no JSON write anywhere; it is not running"
    for sites in (direct, routed):
        offenders = [
            key
            for key, value in sites.items()
            if "operations/interaction" in f"{key}{value}"
        ]
        assert offenders == []


# --- Facade and import purity -----------------------------------------------


def test_operations_facade_exports_the_interaction_surface():
    from gridalyn.operations import interaction

    for name in (
        "AgentRef",
        "MessageBus",
        "build_flex_trading_messages",
        "write_interaction_report",
    ):
        assert name in operations.__all__
        assert getattr(operations, name) is getattr(interaction, name)


def test_importing_interaction_loads_no_heavy_module():
    probe = (
        "import sys, gridalyn.operations.interaction; "
        "print(','.join(sorted(m for m in ('pandapower', 'scipy', 'matplotlib', "
        "'lightsim2grid', 'cvxpy', 'osmnx') if m in sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


def test_log_entry_refuses_inconsistent_outcomes():
    entry = run_message_transcript([_request()]).log.entries[0]
    with pytest.raises(ValueError, match="is lost but carries a delivery time"):
        replace(entry, outcome="lost")
    with pytest.raises(ValueError, match="before it was sent"):
        replace(entry, delivered_at=-1.0)

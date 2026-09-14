"""The on-demand **agent_interaction** semantic capability (bd 4ky.7).

The semantic graph was an inventory of *who could* offer flexibility:
providers, offers, contracts, constraint zones. What actually *happened* --
who asked whom for what, who answered, what a demand-response event ordered --
existed only as parquet written by ``gridalyn.operations.interaction``
(bd 4ky.6). Nothing in the graph could be asked "which agents answered the
request for constraint zone T", because agents, roles and conversations were
not types.

This capability projects that message log onto the graph. It reads the log as
a table and **never imports** ``gridalyn.operations``: the semantic layer sits
below operations, and knowledge cannot flow upward as an import. Two things
are therefore restated here as data, each pinned against its source by
``tests/test_agent_interaction_capability.py`` so a drift turns red:

* :data:`ROLE_ALIGNMENT_TABLE`, the four functional roles and how each reads in
  USEF 2021 and OpenADR 3.1.0 (``operations.interaction.ROLE_ALIGNMENT``);
* :data:`REQUIRED_LOG_COLUMNS`, the columns of a message log this emitter reads
  (``operations.interaction.log.MESSAGE_LOG_COLUMNS``).

**OpenADR alignment, not OpenADR IRIs.** The OpenADR Alliance publishes no RDF
vocabulary (verified 2026-09-10, ``docs/reference/standards-alignment.md``), so
a ``openadr:`` IRI would name nothing. The program and event classes are
gridalyn's own ``flexint:`` terms whose ``aligns_with`` property states the
OpenADR 3.1.0 object they render, and whose payload fields are 3.1.0's own
spellings.

**Conversations are summarized, not replayed.** One node per conversation
carries what the log itself states -- message counts by outcome, the window it
spans, the message types exchanged -- and never a protocol state, which only a
protocol replay in ``operations`` can decide. A graph that claimed a state it
had not computed would be a graph that lies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pandas as pd

from gridalyn.twin.semantic.builder import SemanticGraphBuilder
from gridalyn.twin.semantic.records import _edge, _node, _safe_str
from gridalyn.twin.semantic.repository import _loads_json
from gridalyn.twin.semantic.vocabulary import (
    CapabilityInputs,
    RelationshipSpec,
    SemanticCapability,
)

#: Standard recorded on the nodes this capability mints itself.
FLEXINT_SOURCE = "Gridalyn_Flexint"

#: Standard recorded on the nodes that render an OpenADR 3.1.0 object.
OPENADR_SOURCE = "OpenADR_3.1.0"

#: Lineage recorded on every node and edge: the artifact they were read from.
LOG_SOURCE_TABLE = "interaction_message_log"

#: The demand-response protocol whose payloads carry OpenADR objects.
DR_PROGRAM_PROTOCOL_ID = "dr_program"

#: The negotiation protocol whose requests name a network constraint.
FLEX_TRADING_PROTOCOL_ID = "flex_trading"

#: Columns :func:`emit_interaction_log` reads. A subset of the log contract, in
#: its order; pinned against ``MESSAGE_LOG_COLUMNS`` by the capability's tests.
REQUIRED_LOG_COLUMNS: tuple[str, ...] = (
    "conversation_id",
    "protocol",
    "message_type",
    "performative",
    "sender_agent_id",
    "sender_party_id",
    "sender_role",
    "receiver_agent_id",
    "receiver_party_id",
    "receiver_role",
    "sent_at",
    "payload_json",
    "outcome",
)

#: The functional roles and their standard alignments, restated from
#: ``operations.interaction.ROLE_ALIGNMENT`` because this layer cannot import
#: it. ``None`` means the standard defines no such role.
ROLE_ALIGNMENT_TABLE: Mapping[str, Mapping[str, str | None]] = {
    "active_customer": {"usef": "Active Customer", "openadr": "VEN"},
    "aggregator": {"usef": "AGR", "openadr": "VEN"},
    "distribution_operator": {"usef": "DSO", "openadr": None},
    "program_administrator": {"usef": None, "openadr": "BL"},
}

#: OpenADR 3.1.0 event payload fields the emitter reads. ``eventName`` carries
#: the event's identifier in an ``event`` payload, while ``report``,
#: ``flexint:EventCancellation`` and ``flexint:OptOut`` payloads spell the same
#: identifier ``eventID``; both are read.
_EVENT_ID_FIELDS = ("eventName", "eventID")
_PROGRAM_ID_FIELD = "programID"
_ACTIVE_FROM_FIELD = "flexint:activeFrom"
_ACTIVE_UNTIL_FIELD = "flexint:activeUntil"
_CAPACITY_LIMIT_PAYLOAD = "flexint:IMPORT_CAPACITY_LIMIT_KW"
_CONSTRAINT_ID_FIELD = "constraint_id"

_AGENT_INTERACTION_NAMESPACES: dict[str, str] = {
    "flexint": "https://w3id.org/gridalyn/ontology/flexint#",
}

_AGENT_INTERACTION_TYPES: tuple[str, ...] = (
    "flexint:Agent",
    "flexint:Conversation",
    "flexint:DemandResponseEvent",
    "flexint:DemandResponseProgram",
    "flexint:Party",
    "flexint:Role",
)

_AGENT_INTERACTION_RELATIONSHIPS: tuple[RelationshipSpec, ...] = (
    RelationshipSpec(
        "ACTS_FOR",
        "flexint:actsFor",
        ("flexint:Agent",),
        ("flexint:Party",),
        source_cardinality=(1, 1),
        note=(
            "An agent acts for exactly one party; a party holds several agents, "
            "which is the Hydro-Quebec case the role model exists for."
        ),
    ),
    RelationshipSpec(
        "FOLLOWS_EVENT",
        "flexint:followsEvent",
        ("flexint:Conversation",),
        ("flexint:DemandResponseEvent",),
    ),
    RelationshipSpec(
        "PARTICIPATES_IN_CONVERSATION",
        "flexint:participatesInConversation",
        ("flexint:Agent",),
        ("flexint:Conversation",),
    ),
    RelationshipSpec(
        "PLAYS_ROLE",
        "flexint:playsRole",
        ("flexint:Agent",),
        ("flexint:Role",),
        note=(
            "Unconstrained on purpose: the log is the authority, and an agent "
            "observed sending under two roles is data to see, not a violation."
        ),
    ),
    RelationshipSpec(
        "SCHEDULES_EVENT",
        "flexint:schedulesEvent",
        ("flexint:DemandResponseProgram",),
        ("flexint:DemandResponseEvent",),
    ),
)


def _require_log_columns(interaction_log: pd.DataFrame) -> None:
    """Refuse a log missing a column this emitter reads, naming both sets.

    Args:
        interaction_log: The message-log table.

    Raises:
        ValueError: A required column is absent.
    """
    missing = [
        column for column in REQUIRED_LOG_COLUMNS if column not in interaction_log
    ]
    if missing:
        present = ", ".join(map(str, interaction_log.columns)) or "none"
        raise ValueError(
            f"interaction log is missing column(s) {', '.join(missing)} "
            f"(present: {present}); write one with "
            "gridalyn.operations.interaction.write_message_log"
        )


def _payload(raw: Any) -> dict[str, Any]:
    """Return a message payload, or an empty mapping when it is unreadable."""
    try:
        return _loads_json(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _text(value: Any) -> str | None:
    """Return a trimmed string, or ``None`` for a missing or blank value."""
    text = _safe_str(value)
    if text is None:
        return None
    text = text.strip()
    return text or None


def _number(value: Any) -> float | None:
    """Return a finite float, or ``None`` when the value is absent or not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN is never equal to itself


def _capacity_limit_kw(payload: Mapping[str, Any]) -> float | None:
    """Return the import cap an OpenADR ``event`` payload's intervals state."""
    intervals = payload.get("intervals")
    if not isinstance(intervals, (list, tuple)):
        return None
    for interval in intervals:
        if not isinstance(interval, Mapping):
            continue
        for entry in interval.get("payloads") or ():
            if not isinstance(entry, Mapping):
                continue
            if entry.get("type") != _CAPACITY_LIMIT_PAYLOAD:
                continue
            values = entry.get("values")
            if isinstance(values, (list, tuple)) and values:
                return _number(values[0])
    return None


def _event_id(payload: Mapping[str, Any]) -> str | None:
    """Return the event identifier under whichever field spells it."""
    for field_name in _EVENT_ID_FIELDS:
        event_id = _text(payload.get(field_name))
        if event_id is not None:
            return event_id
    return None


def _resolve_dr_objects(
    interaction_log: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Resolve each demand-response event to its program and its window.

    Only an ``event`` payload carries both the program and the event, so the
    whole log is read before any node is minted: a conversation that saw only a
    report still resolves to the same event node as the one that saw the event.

    Args:
        interaction_log: The message-log table.

    Returns:
        ``(program_by_event, event_details)``, keyed by event identifier.
    """
    program_by_event: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    for row in interaction_log.itertuples(index=False):
        if _text(row.protocol) != DR_PROGRAM_PROTOCOL_ID:
            continue
        payload = _payload(row.payload_json)
        event_id = _event_id(payload)
        if event_id is None:
            continue
        detail = details.setdefault(event_id, {})
        program_id = _text(payload.get(_PROGRAM_ID_FIELD))
        if program_id is not None:
            program_by_event.setdefault(event_id, program_id)
        for key, field_name in (
            ("active_from_minute", _ACTIVE_FROM_FIELD),
            ("active_until_minute", _ACTIVE_UNTIL_FIELD),
        ):
            value = _number(payload.get(field_name))
            if value is not None:
                detail.setdefault(key, value)
        capacity = _capacity_limit_kw(payload)
        if capacity is not None:
            detail.setdefault("capacity_limit_kw", capacity)
    return program_by_event, details


def _event_node_id(event_id: str, program_id: str | None) -> str:
    """Return the node id of a demand-response event, program-scoped when known."""
    return f"dr-event:{program_id}:{event_id}" if program_id else f"dr-event:{event_id}"


def _agent_rows(interaction_log: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Collect each agent seen in the log, with its party and the roles it played."""
    agents: dict[str, dict[str, Any]] = {}
    for row in interaction_log.itertuples(index=False):
        for agent_id, party_id, role in (
            (row.sender_agent_id, row.sender_party_id, row.sender_role),
            (row.receiver_agent_id, row.receiver_party_id, row.receiver_role),
        ):
            name = _text(agent_id)
            if name is None:
                continue
            agent = agents.setdefault(name, {"parties": set(), "roles": set()})
            party = _text(party_id)
            if party is not None:
                agent["parties"].add(party)
            played = _text(role)
            if played is not None:
                agent["roles"].add(played)
    return agents


def _conversation_rows(
    interaction_log: pd.DataFrame,
    program_by_event: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Summarize each conversation from the messages the log records for it."""
    conversations: dict[str, dict[str, Any]] = {}
    for row in interaction_log.itertuples(index=False):
        key = _text(row.conversation_id)
        if key is None:
            continue
        summary = conversations.setdefault(
            key,
            {
                "protocol": _text(row.protocol),
                "message_count": 0,
                "delivered_message_count": 0,
                "lost_message_count": 0,
                "in_flight_message_count": 0,
                "message_types": set(),
                "performatives": set(),
                "agents": set(),
                "sent_at": [],
                "event_id": None,
                "constraint_id": None,
            },
        )
        summary["message_count"] += 1
        outcome = _text(row.outcome)
        if outcome in {"delivered", "lost", "in_flight"}:
            summary[f"{outcome}_message_count"] += 1
        for value, bucket in (
            (row.message_type, "message_types"),
            (row.performative, "performatives"),
            (row.sender_agent_id, "agents"),
            (row.receiver_agent_id, "agents"),
        ):
            text = _text(value)
            if text is not None:
                summary[bucket].add(text)
        sent_at = _number(row.sent_at)
        if sent_at is not None:
            summary["sent_at"].append(sent_at)
        payload = _payload(row.payload_json)
        if summary["protocol"] == DR_PROGRAM_PROTOCOL_ID:
            summary["event_id"] = summary["event_id"] or _event_id(payload)
        if summary["protocol"] == FLEX_TRADING_PROTOCOL_ID:
            summary["constraint_id"] = summary["constraint_id"] or _text(
                payload.get(_CONSTRAINT_ID_FIELD)
            )
    for summary in conversations.values():
        event_id = summary["event_id"]
        summary["program_id"] = program_by_event.get(event_id) if event_id else None
    return conversations


def _emit_roles(builder: SemanticGraphBuilder, roles: set[str]) -> None:
    """Emit one node per role the log used, carrying its standard alignments."""
    for role in sorted(roles):
        alignment = ROLE_ALIGNMENT_TABLE.get(role, {})
        builder.add_node(
            _node(
                f"role:{role}",
                ["Role", "FunctionalRole"],
                "flexint:Role",
                FLEXINT_SOURCE,
                LOG_SOURCE_TABLE,
                role,
                name=role,
                properties={
                    "role": role,
                    "usef_role": alignment.get("usef"),
                    "openadr_client": alignment.get("openadr"),
                    "aligned": bool(alignment),
                },
            )
        )


def _emit_agents(
    builder: SemanticGraphBuilder, agents: Mapping[str, Mapping[str, Any]]
) -> None:
    """Emit agent and party nodes, and the edges to the party and role of each."""
    parties: dict[str, int] = {}
    for _agent_id, agent in sorted(agents.items()):
        for party in agent["parties"]:
            parties[party] = parties.get(party, 0) + 1
    for party_id, agent_count in sorted(parties.items()):
        builder.add_node(
            _node(
                f"party:{party_id}",
                ["Party"],
                "flexint:Party",
                FLEXINT_SOURCE,
                LOG_SOURCE_TABLE,
                party_id,
                name=party_id,
                properties={"party_id": party_id, "agent_count": agent_count},
            )
        )
    for agent_id, agent in sorted(agents.items()):
        roles = sorted(agent["roles"])
        agent_parties = sorted(agent["parties"])
        builder.add_node(
            _node(
                f"agent:{agent_id}",
                ["Agent"],
                "flexint:Agent",
                FLEXINT_SOURCE,
                LOG_SOURCE_TABLE,
                agent_id,
                name=agent_id,
                properties={
                    "agent_id": agent_id,
                    "party_id": agent_parties[0] if agent_parties else None,
                    "roles": ";".join(roles),
                },
            )
        )
        for party_id in agent_parties:
            builder.add_edge(
                _edge(
                    f"agent:{agent_id}",
                    "ACTS_FOR",
                    f"party:{party_id}",
                    "flexint:actsFor",
                    FLEXINT_SOURCE,
                    LOG_SOURCE_TABLE,
                    agent_id,
                )
            )
        for role in roles:
            builder.add_edge(
                _edge(
                    f"agent:{agent_id}",
                    "PLAYS_ROLE",
                    f"role:{role}",
                    "flexint:playsRole",
                    FLEXINT_SOURCE,
                    LOG_SOURCE_TABLE,
                    agent_id,
                )
            )


def _emit_demand_response(
    builder: SemanticGraphBuilder,
    program_by_event: Mapping[str, str],
    event_details: Mapping[str, Mapping[str, Any]],
) -> None:
    """Emit the OpenADR-aligned program and event nodes, and the edges between."""
    events_by_program: dict[str, list[str]] = {}
    for event_id in sorted(event_details):
        program_id = program_by_event.get(event_id)
        if program_id is not None:
            events_by_program.setdefault(program_id, []).append(event_id)
    for program_id, event_ids in sorted(events_by_program.items()):
        builder.add_node(
            _node(
                f"dr-program:{program_id}",
                ["DemandResponseProgram"],
                "flexint:DemandResponseProgram",
                OPENADR_SOURCE,
                LOG_SOURCE_TABLE,
                program_id,
                name=program_id,
                properties={
                    "program_id": program_id,
                    "event_count": len(event_ids),
                    "aligns_with": "OpenADR 3.1.0 PROGRAM",
                },
            )
        )
    for event_id in sorted(event_details):
        program_id = program_by_event.get(event_id)
        detail = event_details[event_id]
        node_id = _event_node_id(event_id, program_id)
        builder.add_node(
            _node(
                node_id,
                ["DemandResponseEvent"],
                "flexint:DemandResponseEvent",
                OPENADR_SOURCE,
                LOG_SOURCE_TABLE,
                event_id,
                name=event_id,
                properties={
                    "event_id": event_id,
                    "program_id": program_id,
                    "aligns_with": "OpenADR 3.1.0 EVENT",
                    **{key: detail[key] for key in sorted(detail)},
                },
            )
        )
        if program_id is not None:
            builder.add_edge(
                _edge(
                    f"dr-program:{program_id}",
                    "SCHEDULES_EVENT",
                    node_id,
                    "flexint:schedulesEvent",
                    OPENADR_SOURCE,
                    LOG_SOURCE_TABLE,
                    event_id,
                )
            )


def _emit_conversations(
    builder: SemanticGraphBuilder,
    conversations: Mapping[str, Mapping[str, Any]],
    program_by_event: Mapping[str, str],
    event_details: Mapping[str, Mapping[str, Any]],
) -> None:
    """Emit one summary node per conversation, with its participants and event."""
    for conversation_id, summary in sorted(conversations.items()):
        node_id = f"conversation:{conversation_id}"
        sent_at = sorted(summary["sent_at"])
        builder.add_node(
            _node(
                node_id,
                ["Conversation"],
                "flexint:Conversation",
                FLEXINT_SOURCE,
                LOG_SOURCE_TABLE,
                conversation_id,
                name=conversation_id,
                properties={
                    "conversation_id": conversation_id,
                    "protocol": summary["protocol"],
                    "message_count": summary["message_count"],
                    "delivered_message_count": summary["delivered_message_count"],
                    "lost_message_count": summary["lost_message_count"],
                    "in_flight_message_count": summary["in_flight_message_count"],
                    "message_types": ";".join(sorted(summary["message_types"])),
                    "performatives": ";".join(sorted(summary["performatives"])),
                    "participant_count": len(summary["agents"]),
                    "first_sent_at_minute": sent_at[0] if sent_at else None,
                    "last_sent_at_minute": sent_at[-1] if sent_at else None,
                    "event_id": summary["event_id"],
                    "program_id": summary["program_id"],
                    "constraint_id": summary["constraint_id"],
                },
            )
        )
        for agent_id in sorted(summary["agents"]):
            builder.add_edge(
                _edge(
                    f"agent:{agent_id}",
                    "PARTICIPATES_IN_CONVERSATION",
                    node_id,
                    "flexint:participatesInConversation",
                    FLEXINT_SOURCE,
                    LOG_SOURCE_TABLE,
                    conversation_id,
                )
            )
        event_id = summary["event_id"]
        if event_id is not None and event_id in event_details:
            builder.add_edge(
                _edge(
                    node_id,
                    "FOLLOWS_EVENT",
                    _event_node_id(event_id, program_by_event.get(event_id)),
                    "flexint:followsEvent",
                    FLEXINT_SOURCE,
                    LOG_SOURCE_TABLE,
                    conversation_id,
                )
            )


def emit_interaction_log(
    builder: SemanticGraphBuilder, interaction_log: pd.DataFrame
) -> None:
    """Emit agents, parties, roles, conversations and DR objects from a log.

    Args:
        builder: Accumulator that owns node and edge identity.
        interaction_log: A message log as written by
            ``gridalyn.operations.interaction.write_message_log``; empty is a
            no-op.

    Raises:
        ValueError: The log is missing a column this emitter reads.
    """
    if interaction_log.empty:
        return
    _require_log_columns(interaction_log)
    program_by_event, event_details = _resolve_dr_objects(interaction_log)
    agents = _agent_rows(interaction_log)
    conversations = _conversation_rows(interaction_log, program_by_event)
    roles = {role for agent in agents.values() for role in agent["roles"]}
    _emit_roles(builder, roles)
    _emit_agents(builder, agents)
    _emit_demand_response(builder, program_by_event, event_details)
    _emit_conversations(builder, conversations, program_by_event, event_details)


def extend_graph_with_agent_interaction(
    builder: SemanticGraphBuilder, interaction_log: pd.DataFrame
) -> None:
    """Apply the agent-interaction layer to a model-first semantic graph.

    An absent log is an empty one: a project that declares the capability but
    has run no protocol still builds a valid graph, exactly as the flexibility
    capability treats an absent provider registry.

    Args:
        builder: Accumulator that owns node and edge identity.
        interaction_log: The message log; empty is a no-op.
    """
    if interaction_log.empty:
        return
    emit_interaction_log(builder, interaction_log)


def _extend_from_inputs(
    builder: SemanticGraphBuilder, inputs: CapabilityInputs
) -> None:
    """Adapt the declared extender signature to the log this layer reads."""
    extend_graph_with_agent_interaction(builder, inputs.interaction_log)


def agent_interaction_profile_extensions() -> dict[str, Any]:
    """Return the agent-interaction slice of the semantic profile as plain data.

    Derived from :data:`AGENT_INTERACTION_CAPABILITY`, so this view and the
    declaration cannot drift.
    """
    capability = AGENT_INTERACTION_CAPABILITY
    return {
        "namespaces": dict(capability.namespaces),
        "primary_standards": {
            concern: list(standards)
            for concern, standards in capability.primary_standards.items()
        },
        "allowed_semantic_types": list(capability.semantic_types),
        "relationship_types": sorted(spec.name for spec in capability.relationships),
    }


# ---------------------------------------------------------------------------
# Repository queries
# ---------------------------------------------------------------------------
def query_conversations_for_constraint(
    repository: Any,
    constraint_id: str,
) -> tuple[dict[str, Any], ...]:
    """Return the conversations that negotiated a named network constraint.

    The log states the constraint a request names; it does not state which
    constraint-zone node models it. The join is therefore made on the
    ``constraint_id`` property, the same way the flexibility layer resolves a
    zone, rather than by minting a zone id this layer cannot know.

    Args:
        repository: A :class:`~gridalyn.twin.semantic.SemanticGraphRepository`.
        constraint_id: The constraint the request named, e.g. ``transformer:64``.

    Returns:
        The matching conversation records, ordered by node id.
    """
    conversations = repository.nodes.loc[
        repository.nodes["semantic_type"] == "flexint:Conversation"
    ]
    matched = [
        str(row["node_id"])
        for _, row in conversations.iterrows()
        if str(_loads_json(row["properties"]).get("constraint_id"))
        == str(constraint_id)
    ]
    records = (repository.get_node(node_id) for node_id in sorted(matched))
    return tuple(record for record in records if record is not None)


def query_agents_answering_constraint(
    repository: Any,
    constraint_id: str,
    *,
    performative: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return the agents that took part in a constraint's conversations.

    This is the question the graph could not answer before this capability:
    *which agents answered the request for constraint zone T*.

    Args:
        repository: A :class:`~gridalyn.twin.semantic.SemanticGraphRepository`.
        constraint_id: The constraint the request named.
        performative: Keep only agents whose conversations carry this FIPA act,
            e.g. ``propose`` for the ones that actually answered; ``None``
            keeps every participant.

    Returns:
        The matching agent records, ordered by node id.
    """
    agent_ids: set[str] = set()
    for conversation in query_conversations_for_constraint(repository, constraint_id):
        acts = str(conversation["properties"].get("performatives") or "").split(";")
        if performative is not None and performative not in acts:
            continue
        agent_ids.update(
            repository.neighbors(
                conversation["node_id"],
                "PARTICIPATES_IN_CONVERSATION",
                direction="in",
            )
        )
    records = (repository.get_node(agent_id) for agent_id in sorted(agent_ids))
    return tuple(record for record in records if record is not None)


AGENT_INTERACTION_CAPABILITY = SemanticCapability(
    capability_id="agent_interaction",
    namespaces=_AGENT_INTERACTION_NAMESPACES,
    primary_standards={
        "agent_interaction": ("gridalyn flexint", "FIPA ACL"),
        "demand_response": ("OpenADR 3.1.0",),
        "role_model": ("USEF 2021",),
    },
    semantic_types=_AGENT_INTERACTION_TYPES,
    relationships=_AGENT_INTERACTION_RELATIONSHIPS,
    extend=_extend_from_inputs,
)

"""Interaction protocols as declarative state machines, and the conversations running them.

A :class:`ProtocolSpec` states which message may follow which, between which
roles, with which communicative act and which payload fields -- as data, so a
protocol can be read, documented and checked without running it. A
:class:`Conversation` is one instance of a protocol between concrete agents: it
accepts a message only when the spec has a transition for it, and otherwise
raises a ``ValueError`` naming the conversation, its state, the message and
what the state would have accepted.

**Two kinds of transition.** Most protocols advance only on messages. Some
standards also advance on *time*: an OpenADR event becomes active at its start
and completes at its end without any message saying so. A
:class:`DeadlineTransition` covers that: a message's payload carries a
simulated time under a declared field, and the conversation moves when its
clock passes it. Deadline transitions must change state and may not form a
cycle, so advancing the clock always terminates.

**Extensions are labelled.** A message type whose name starts with
``flexint:`` is gridalyn's own, and its declared ``source`` must say so; a
standard message type may not carry that prefix. That keeps "OpenADR 3.1.0
has no cancellation message" visible in the protocol itself.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from gridalyn.operations.interaction.messages import Message
from gridalyn.operations.interaction.vocabulary import (
    Performative,
    ProtocolId,
    RoleId,
    parse_performative,
    parse_protocol_id,
    parse_role,
)

#: Prefix of gridalyn's own message types and payload fields.
EXTENSION_PREFIX = "flexint:"

#: The ``source`` every extension message type declares.
EXTENSION_SOURCE = "flexint extension"


@dataclass(frozen=True)
class MessageTypeSpec:
    """A message a protocol exchanges.

    Attributes:
        message_type: The name messages carry, e.g. ``FlexRequest``.
        source: Where the name comes from, e.g. ``"UFTP 3.1.0"``, or
            :data:`EXTENSION_SOURCE` for gridalyn's own.
        required_fields: Payload fields this protocol requires. They are what
            the protocol needs to run, not a restatement of the standard's
            schema.
    """

    message_type: str
    source: str
    required_fields: tuple[str, ...] = ()

    @property
    def is_extension(self) -> bool:
        """Return whether this is gridalyn's own message type."""
        return self.message_type.startswith(EXTENSION_PREFIX)

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view for reports."""
        return {
            "message_type": self.message_type,
            "source": self.source,
            "extension": self.is_extension,
            "required_fields": list(self.required_fields),
        }


@dataclass(frozen=True)
class MessageTransition:
    """A state change caused by accepting one kind of message.

    Attributes:
        source: State the conversation must be in.
        message_type: Message that causes the change.
        performative: The act that message must perform.
        sender_roles: Roles allowed to send it.
        receiver_roles: Roles allowed to receive it.
        target: State the conversation moves to; may equal ``source``.
    """

    source: str
    message_type: str
    performative: Performative
    sender_roles: tuple[RoleId, ...]
    receiver_roles: tuple[RoleId, ...]
    target: str

    def describe(self) -> str:
        """Return a one-line reading, as used in refusal messages."""
        senders = "|".join(self.sender_roles)
        receivers = "|".join(self.receiver_roles)
        return f"{self.message_type} ({self.performative}) {senders} -> {receivers}"

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view for reports."""
        return {
            "source": self.source,
            "message_type": self.message_type,
            "performative": self.performative,
            "sender_roles": list(self.sender_roles),
            "receiver_roles": list(self.receiver_roles),
            "target": self.target,
        }


@dataclass(frozen=True)
class DeadlineTransition:
    """A state change caused by the conversation's clock passing a deadline.

    Attributes:
        source: State the conversation must be in.
        deadline: Payload field holding the deadline, in simulated time. The
            latest accepted message carrying the field sets it.
        target: State the conversation moves to; must differ from ``source``.
    """

    source: str
    deadline: str
    target: str

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view for reports."""
        return {"source": self.source, "deadline": self.deadline, "target": self.target}


def _duplicates(values: tuple[str, ...]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


@dataclass(frozen=True)
class ProtocolSpec:
    """A protocol: its states, messages and transitions, checked on construction.

    Attributes:
        protocol_id: The protocol's id.
        version: This spec's version; bumped when the state machine changes.
        standard: The standard the protocol is aligned to.
        states: Every state, in reading order.
        initial: The state a new conversation starts in.
        message_types: Every message the protocol exchanges.
        transitions: Message-driven transitions.
        deadline_transitions: Time-driven transitions.
    """

    protocol_id: ProtocolId
    version: str
    standard: str
    states: tuple[str, ...]
    initial: str
    message_types: tuple[MessageTypeSpec, ...]
    transitions: tuple[MessageTransition, ...]
    deadline_transitions: tuple[DeadlineTransition, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a malformed protocol, listing every problem found.

        Raises:
            ValueError: Naming the protocol and each problem.
        """
        parse_protocol_id(self.protocol_id)
        problems = [
            *self._state_problems(),
            *self._message_type_problems(),
            *self._transition_problems(),
            *self._deadline_problems(),
            *self._reachability_problems(),
        ]
        if problems:
            raise ValueError(
                f"protocol {self.protocol_id!r} v{self.version} is malformed: "
                + "; ".join(problems)
            )

    def _state_problems(self) -> Iterator[str]:
        if not self.states:
            yield "it declares no state"
        for state in _duplicates(self.states):
            yield f"state {state!r} is declared twice"
        if self.initial not in self.states:
            yield f"initial state {self.initial!r} is not a declared state"

    def _message_type_problems(self) -> Iterator[str]:
        names = tuple(spec.message_type for spec in self.message_types)
        for name in _duplicates(names):
            yield f"message type {name!r} is declared twice"
        for spec in self.message_types:
            if spec.is_extension != (spec.source == EXTENSION_SOURCE):
                yield (
                    f"message type {spec.message_type!r} has source {spec.source!r}; "
                    f"a name starting {EXTENSION_PREFIX!r} is an extension and must "
                    f"declare source {EXTENSION_SOURCE!r}, and only such a name may"
                )

    def _transition_problems(self) -> Iterator[str]:
        declared = {spec.message_type for spec in self.message_types}
        keys: set[tuple[str, str, str, str]] = set()
        for transition in self.transitions:
            label = f"transition {transition.source!r} --{transition.message_type}-->"
            for state in (transition.source, transition.target):
                if state not in self.states:
                    yield f"{label} names undeclared state {state!r}"
            if transition.message_type not in declared:
                yield f"{label} names undeclared message type"
            yield from _vocabulary_problems(label, transition)
            for sender in transition.sender_roles:
                for receiver in transition.receiver_roles:
                    key = (transition.source, transition.message_type, sender, receiver)
                    if key in keys:
                        yield f"{label} repeats {sender} -> {receiver}"
                    keys.add(key)

    def _deadline_problems(self) -> Iterator[str]:
        fields = {name for spec in self.message_types for name in spec.required_fields}
        for transition in self.deadline_transitions:
            label = (
                f"deadline transition {transition.source!r} --{transition.deadline}-->"
            )
            for state in (transition.source, transition.target):
                if state not in self.states:
                    yield f"{label} names undeclared state {state!r}"
            if transition.source == transition.target:
                yield f"{label} does not change state"
            if transition.deadline not in fields:
                yield f"{label} reads a field no message type requires"
        if _has_cycle(self.deadline_transitions):
            yield "its deadline transitions form a cycle"

    def _reachability_problems(self) -> Iterator[str]:
        edges: dict[str, set[str]] = {}
        for edge in self._edges():
            edges.setdefault(edge.source, set()).add(edge.target)
        reached = {self.initial}
        frontier = [self.initial]
        while frontier:
            for target in edges.get(frontier.pop(), set()) - reached:
                reached.add(target)
                frontier.append(target)
        for state in self.states:
            if state not in reached:
                yield f"state {state!r} is unreachable from {self.initial!r}"

    @property
    def terminal_states(self) -> tuple[str, ...]:
        """Return the states no transition leaves, in declaration order."""
        leaving = {edge.source for edge in self._edges() if edge.target != edge.source}
        return tuple(state for state in self.states if state not in leaving)

    def _edges(self) -> tuple[MessageTransition | DeadlineTransition, ...]:
        return (*self.transitions, *self.deadline_transitions)

    def message_type_spec(self, message_type: str) -> MessageTypeSpec | None:
        """Return the declared message type, or ``None``."""
        for spec in self.message_types:
            if spec.message_type == message_type:
                return spec
        return None

    def transitions_from(self, state: str) -> tuple[MessageTransition, ...]:
        """Return the message transitions leaving ``state``, in declaration order."""
        return tuple(edge for edge in self.transitions if edge.source == state)

    def find_transition(
        self, state: str, message_type: str, sender_role: str, receiver_role: str
    ) -> MessageTransition | None:
        """Return the transition that accepts this message in ``state``, or ``None``."""
        for edge in self.transitions_from(state):
            if (
                edge.message_type == message_type
                and sender_role in edge.sender_roles
                and receiver_role in edge.receiver_roles
            ):
                return edge
        return None

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the whole protocol, for reports."""
        return {
            "protocol_id": self.protocol_id,
            "version": self.version,
            "standard": self.standard,
            "states": list(self.states),
            "initial": self.initial,
            "terminal_states": list(self.terminal_states),
            "message_types": [spec.as_dict() for spec in self.message_types],
            "transitions": [edge.as_dict() for edge in self.transitions],
            "deadline_transitions": [
                edge.as_dict() for edge in self.deadline_transitions
            ],
        }


def _vocabulary_problems(label: str, transition: MessageTransition) -> Iterator[str]:
    try:
        parse_performative(transition.performative)
    except ValueError as exc:
        yield f"{label}: {exc}"
    for side, roles in (
        ("sender_roles", transition.sender_roles),
        ("receiver_roles", transition.receiver_roles),
    ):
        if not roles:
            yield f"{label} declares no {side}"
        for role in roles:
            try:
                parse_role(role)
            except ValueError as exc:
                yield f"{label} {side}: {exc}"


def _has_cycle(transitions: tuple[DeadlineTransition, ...]) -> bool:
    edges: dict[str, set[str]] = {}
    for edge in transitions:
        edges.setdefault(edge.source, set()).add(edge.target)
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(state: str) -> bool:
        if state in done:
            return False
        if state in visiting:
            return True
        visiting.add(state)
        found = any(visit(target) for target in sorted(edges.get(state, set())))
        visiting.discard(state)
        done.add(state)
        return found

    return any(visit(state) for state in sorted(edges))


@dataclass(frozen=True)
class ConversationStep:
    """One state change in a conversation's history.

    Attributes:
        at: Simulated time of the change.
        source: State before.
        target: State after.
        trigger: The accepted message's id, or ``deadline:<field>``.
    """

    at: float
    source: str
    target: str
    trigger: str


def _finite(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite simulated time; found {value!r}")
    return number


class Conversation:
    """One run of a protocol between concrete agents."""

    def __init__(self, protocol: ProtocolSpec, conversation_id: str) -> None:
        """Start a conversation in the protocol's initial state.

        Args:
            protocol: The protocol this conversation follows.
            conversation_id: Identifier every message in it carries.

        Raises:
            ValueError: ``conversation_id`` is empty.
        """
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError(
                f"conversation_id must be a non-empty string; found {conversation_id!r}"
            )
        self._protocol = protocol
        self._conversation_id = conversation_id
        self._state = protocol.initial
        self._clock: float | None = None
        self._participants: dict[str, str] = {}
        self._deadlines: dict[str, float] = {}
        self._steps: list[ConversationStep] = []
        self._deadline_fields = frozenset(
            edge.deadline for edge in protocol.deadline_transitions
        )

    @property
    def protocol(self) -> ProtocolSpec:
        """Return the protocol this conversation follows."""
        return self._protocol

    @property
    def conversation_id(self) -> str:
        """Return the conversation's identifier."""
        return self._conversation_id

    @property
    def state(self) -> str:
        """Return the current state."""
        return self._state

    @property
    def clock(self) -> float | None:
        """Return the simulated time the conversation last moved to, if any."""
        return self._clock

    @property
    def is_terminal(self) -> bool:
        """Return whether no transition leaves the current state."""
        return self._state in self._protocol.terminal_states

    @property
    def participants(self) -> Mapping[str, str]:
        """Return the agent bound to each role so far, keyed by role."""
        return MappingProxyType(dict(self._participants))

    @property
    def deadlines(self) -> Mapping[str, float]:
        """Return each deadline field's current value."""
        return MappingProxyType(dict(self._deadlines))

    @property
    def steps(self) -> tuple[ConversationStep, ...]:
        """Return every state change so far, in order."""
        return tuple(self._steps)

    def _describe(self) -> str:
        return (
            f"conversation {self._conversation_id!r} "
            f"({self._protocol.protocol_id} v{self._protocol.version})"
        )

    def advance_to(self, time: float) -> int:
        """Move the clock to ``time``, firing every deadline transition due by then.

        Args:
            time: Simulated time to advance to.

        Returns:
            How many deadline transitions fired.

        Raises:
            ValueError: ``time`` is not finite or lies before the clock.
        """
        at = _finite(time, "time")
        if self._clock is not None and at < self._clock:
            raise ValueError(
                f"{self._describe()} cannot move to time {at}, before its clock "
                f"{self._clock}; deliver its messages in time order"
            )
        fired = self._fire_deadlines(at)
        self._clock = at
        return fired

    def _fire_deadlines(self, at: float) -> int:
        fired = 0
        due = self._due_deadline(at)
        while due is not None:
            edge, deadline = due
            when = deadline if self._clock is None else max(deadline, self._clock)
            trigger = f"deadline:{edge.deadline}"
            self._steps.append(
                ConversationStep(when, self._state, edge.target, trigger)
            )
            self._state = edge.target
            fired += 1
            due = self._due_deadline(at)
        return fired

    def _due_deadline(self, at: float) -> tuple[DeadlineTransition, float] | None:
        due = [
            (self._deadlines[edge.deadline], index, edge)
            for index, edge in enumerate(self._protocol.deadline_transitions)
            if edge.source == self._state
            and edge.deadline in self._deadlines
            and self._deadlines[edge.deadline] <= at
        ]
        if not due:
            return None
        deadline, _, edge = min(due, key=lambda item: (item[0], item[1]))
        return edge, deadline

    def accept(self, message: Message, *, at: float | None = None) -> str:
        """Advance on a received message, or refuse it with a located error.

        The clock first advances to the receipt time, so a deadline that passed
        before the message arrived has already moved the conversation. A
        deadline the message itself sets in the past fires as soon as the
        message is accepted: an event announced after its start is active on
        arrival.

        Args:
            message: The message received.
            at: Simulated receipt time; defaults to ``message.sent_at``.

        Returns:
            The state after the message and any deadline it made due.

        Raises:
            ValueError: The message belongs to another conversation or protocol,
                arrives before it was sent or before the clock, has no transition
                from the current state, uses the wrong performative, lacks a
                required payload field, or comes from an agent other than the
                one already playing its role.
        """
        received_at = message.sent_at if at is None else _finite(at, "at")
        self._require_membership(message)
        if received_at < message.sent_at:
            raise ValueError(
                f"{self._describe()}: {message.message_type} {message.message_id} is "
                f"received at {received_at}, before it was sent at {message.sent_at}"
            )
        self.advance_to(received_at)
        edge = self._protocol.find_transition(
            self._state,
            message.message_type,
            message.sender.role,
            message.receiver.role,
        )
        if edge is None:
            raise ValueError(self._refusal(message, received_at))
        payload = message.payload
        self._require_act_and_fields(message, edge, payload)
        bindings = self._pending_bindings(message)
        deadlines = self._pending_deadlines(message, payload)
        self._participants.update(bindings)
        self._deadlines.update(deadlines)
        self._steps.append(
            ConversationStep(received_at, self._state, edge.target, message.message_id)
        )
        self._state = edge.target
        self._fire_deadlines(received_at)
        return self._state

    def _require_membership(self, message: Message) -> None:
        if message.conversation_id != self._conversation_id:
            raise ValueError(
                f"{self._describe()} was given message {message.message_id} of "
                f"conversation {message.conversation_id!r}"
            )
        if message.protocol != self._protocol.protocol_id:
            raise ValueError(
                f"{self._describe()} was given message {message.message_id} of "
                f"protocol {message.protocol!r}"
            )

    def _refusal(self, message: Message, received_at: float) -> str:
        head = (
            f"{self._describe()} is in state {self._state!r} at time {received_at} and "
            f"cannot accept {message.message_type} ({message.performative}) from "
            f"{message.sender.role} {message.sender.agent_id!r} to "
            f"{message.receiver.role} {message.receiver.agent_id!r} "
            f"(message {message.message_id})"
        )
        if self._protocol.message_type_spec(message.message_type) is None:
            declared = ", ".join(
                spec.message_type for spec in self._protocol.message_types
            )
            return (
                f"{head}: {message.message_type!r} is not a message of "
                f"{self._protocol.protocol_id} (declared: {declared})"
            )
        allowed = self._protocol.transitions_from(self._state)
        if not allowed:
            return f"{head}: state {self._state!r} accepts no message"
        return f"{head}; state {self._state!r} accepts: " + ", ".join(
            edge.describe() for edge in allowed
        )

    def _require_act_and_fields(
        self, message: Message, edge: MessageTransition, payload: Mapping[str, Any]
    ) -> None:
        if message.performative != edge.performative:
            raise ValueError(
                f"{self._describe()}: {message.message_type} {message.message_id} "
                f"performs {message.performative!r}, but in state {edge.source!r} "
                f"it must perform {edge.performative!r}"
            )
        spec = self._protocol.message_type_spec(message.message_type)
        required = spec.required_fields if spec is not None else ()
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError(
                f"{self._describe()}: {message.message_type} {message.message_id} "
                f"lacks required payload field(s) {', '.join(missing)} (present: "
                f"{', '.join(sorted(payload)) or 'none'})"
            )

    def _pending_bindings(self, message: Message) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for agent in (message.sender, message.receiver):
            bound = self._participants.get(agent.role, bindings.get(agent.role))
            if bound is not None and bound != agent.agent_id:
                raise ValueError(
                    f"{self._describe()}: {message.message_type} "
                    f"{message.message_id} names {agent.agent_id!r} as "
                    f"{agent.role}, but {bound!r} already plays that role in this "
                    "conversation"
                )
            bindings[agent.role] = agent.agent_id
        return bindings

    def _pending_deadlines(
        self, message: Message, payload: Mapping[str, Any]
    ) -> dict[str, float]:
        deadlines: dict[str, float] = {}
        for name in sorted(self._deadline_fields & set(payload)):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(
                    f"{self._describe()}: {message.message_type} "
                    f"{message.message_id} carries {name} = {value!r}; a deadline "
                    "must be a number in simulated time"
                )
            deadlines[name] = _finite(value, name)
        return deadlines


__all__ = [
    "EXTENSION_PREFIX",
    "EXTENSION_SOURCE",
    "Conversation",
    "ConversationStep",
    "DeadlineTransition",
    "MessageTransition",
    "MessageTypeSpec",
    "ProtocolSpec",
]

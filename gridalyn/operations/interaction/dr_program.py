"""The ``dr_program`` protocol: one OpenADR 3.1.0 event between a program and one VEN.

A conversation is one event's life as seen between the program administrator
(the business logic publishing events) and one VEN -- an aggregator or an
active customer:

.. code-block:: text

    idle --event--> notified --(activeFrom)--> active --(activeUntil)--> completed
                    |  ^ event (update)        |  ^ report                 ^ report
                    |--flexint:OptOut--------> opted_out <--flexint:OptOut-|
                    '--flexint:EventCancellation--> cancelled <------------'
    idle --flexint:EventCancellation--> cancelled

``event`` and ``report`` are OpenADR 3.1.0 object names, and their payloads use
that release's field names verbatim (``programID``, ``intervals``,
``clientID``, ``eventID``, ``clientName``, ``resources``). Three things this
protocol needs are **not in OpenADR 3.1.0**, and are extensions carrying the
``flexint:`` prefix:

* **cancellation** -- 3.1.0 deletes the event, or moves its start to
  ``0001-01-01`` with duration ``PT0S``; ``flexint:EventCancellation`` names
  that act as a message;
* **opt-out** -- 3.1.0 has it only as the ``IDLE_OPTED_OUT`` /
  ``RUNNING_OPTED_OUT`` values of an ``OPERATING_STATE`` report payload;
  ``flexint:OptOut`` names the act;
* **the activation window in simulated time** -- an OpenADR
  ``intervalPeriod`` is a wall-clock ISO 8601 start and duration. The event
  payload's ``flexint:activeFrom`` and ``flexint:activeUntil`` carry the same
  window in simulated time, and the conversation becomes ``active`` and then
  ``completed`` as its clock passes them. The notice an event gave is
  ``flexint:activeFrom`` minus the ``sent_at`` of the event message; 3.1.0 has
  no lead-time field either.

**Version 2: messages that cross.** Over a channel that loses or delays
messages, a sender acts on what it knows, not on what the receiver has seen.
Version 1 refused every such message, so the first study to run the protocol
over a lossy channel (``projects/dr_agent_interaction``) could not finish a day.
Version 2 defines the three races instead:

* a cancellation of an event the VEN never received ends the conversation
  ``cancelled`` from ``idle``;
* an opt-out and a cancellation that cross in flight are both valid, and the
  one delivered second is absorbed by the terminal state the first produced;
* an opt-out or a cancellation delivered after the event has ``completed`` is
  moot, and ``completed`` absorbs it.

Every other refusal of version 1 stands.

Enrolment in a program is not part of this protocol: it is follow-up work.
"""

from __future__ import annotations

from gridalyn.operations.interaction.protocols import (
    EXTENSION_SOURCE,
    DeadlineTransition,
    MessageTransition,
    MessageTypeSpec,
    ProtocolSpec,
)
from gridalyn.operations.interaction.vocabulary import RoleId

#: Source declared by the OpenADR message types.
OPENADR_SOURCE = "OpenADR 3.1.0"

#: Event payload field: simulated time the event becomes active.
ACTIVE_FROM_FIELD = "flexint:activeFrom"

#: Event payload field: simulated time the event completes.
ACTIVE_UNTIL_FIELD = "flexint:activeUntil"

_ADMINISTRATOR: tuple[RoleId, ...] = ("program_administrator",)
_VEN: tuple[RoleId, ...] = ("aggregator", "active_customer")
_CANCELLATION = "flexint:EventCancellation"
_OPT_OUT = "flexint:OptOut"


def _cancel(source: str, target: str) -> MessageTransition:
    return MessageTransition(
        source, _CANCELLATION, "cancel", _ADMINISTRATOR, _VEN, target
    )


def _opt_out(source: str, target: str) -> MessageTransition:
    return MessageTransition(source, _OPT_OUT, "refuse", _VEN, _ADMINISTRATOR, target)


DR_PROGRAM_PROTOCOL = ProtocolSpec(
    protocol_id="dr_program",
    version="2",
    standard=(
        "OpenADR 3.1.0 event and report objects; cancellation, opt-out and the "
        "simulated-time activation window are flexint extensions"
    ),
    states=("idle", "notified", "active", "completed", "cancelled", "opted_out"),
    initial="idle",
    message_types=(
        MessageTypeSpec(
            "event",
            OPENADR_SOURCE,
            ("programID", "intervals", ACTIVE_FROM_FIELD, ACTIVE_UNTIL_FIELD),
        ),
        MessageTypeSpec(
            "report", OPENADR_SOURCE, ("clientID", "eventID", "clientName", "resources")
        ),
        MessageTypeSpec(_CANCELLATION, EXTENSION_SOURCE, ("eventID",)),
        MessageTypeSpec(_OPT_OUT, EXTENSION_SOURCE, ("eventID", "clientName")),
    ),
    transitions=(
        MessageTransition("idle", "event", "inform", _ADMINISTRATOR, _VEN, "notified"),
        MessageTransition(
            "notified", "event", "inform", _ADMINISTRATOR, _VEN, "notified"
        ),
        _cancel("notified", "cancelled"),
        _cancel("active", "cancelled"),
        _opt_out("notified", "opted_out"),
        _opt_out("active", "opted_out"),
        MessageTransition("active", "report", "inform", _VEN, _ADMINISTRATOR, "active"),
        MessageTransition(
            "completed", "report", "inform", _VEN, _ADMINISTRATOR, "completed"
        ),
        # Version 2: the races of a lossy, delaying channel.
        _cancel("idle", "cancelled"),
        _cancel("opted_out", "opted_out"),
        _cancel("completed", "completed"),
        _opt_out("cancelled", "cancelled"),
        _opt_out("completed", "completed"),
    ),
    deadline_transitions=(
        DeadlineTransition("notified", ACTIVE_FROM_FIELD, "active"),
        DeadlineTransition("active", ACTIVE_UNTIL_FIELD, "completed"),
    ),
)

__all__ = [
    "ACTIVE_FROM_FIELD",
    "ACTIVE_UNTIL_FIELD",
    "DR_PROGRAM_PROTOCOL",
    "OPENADR_SOURCE",
]

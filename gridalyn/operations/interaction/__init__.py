"""Agent interaction for flexibility and demand response: roles, messages, protocols.

* :mod:`~gridalyn.operations.interaction.vocabulary` -- roles, FIPA acts and
  protocol ids as closed vocabularies.
* :mod:`~gridalyn.operations.interaction.roles` -- functional roles apart from
  parties, aligned to USEF 2021 and OpenADR 3.1.0.
* :mod:`~gridalyn.operations.interaction.messages` -- frozen, content-addressed
  messages.
* :mod:`~gridalyn.operations.interaction.protocols` -- protocols as declarative
  state machines, and conversations that enforce them.
* :mod:`~gridalyn.operations.interaction.flex_trading` and
  :mod:`~gridalyn.operations.interaction.dr_program` -- the two shipped
  protocols; the first also writes a cleared round as messages.
* :mod:`~gridalyn.operations.interaction.bus` -- messages through a channel
  model in simulated time.
* :mod:`~gridalyn.operations.interaction.log` -- the parquet message log, its
  replay, and the governed report.

Imports eagerly: the package needs only ``pandas``, ``numpy`` and the standard
library, all base dependencies, so importing it pulls no optional dependency.
"""

from __future__ import annotations

from gridalyn.operations.interaction.bus import (
    DeliveryHandler,
    MessageBus,
    run_message_transcript,
)
from gridalyn.operations.interaction.conversations import (
    PROTOCOLS,
    ConversationBook,
    resolve_protocol,
)
from gridalyn.operations.interaction.dr_program import (
    ACTIVE_FROM_FIELD,
    ACTIVE_UNTIL_FIELD,
    DR_PROGRAM_PROTOCOL,
)
from gridalyn.operations.interaction.flex_trading import (
    FLEX_TRADING_PROTOCOL,
    build_flex_trading_messages,
)
from gridalyn.operations.interaction.log import (
    MESSAGE_LOG_COLUMNS,
    LogEntry,
    MessageLog,
    build_conversation_book,
    load_message_log,
    summarize_interaction,
    write_interaction_report,
    write_message_log,
)
from gridalyn.operations.interaction.messages import Message, build_message
from gridalyn.operations.interaction.program import (
    DemandResponseEvent,
    DemandResponseProgram,
    build_cancellation_payload,
    build_event_payload,
    build_opt_out_payload,
    build_report_payload,
    measure_reported_kwh,
)
from gridalyn.operations.interaction.protocols import (
    Conversation,
    ConversationStep,
    DeadlineTransition,
    MessageTransition,
    MessageTypeSpec,
    ProtocolSpec,
)
from gridalyn.operations.interaction.roles import (
    ROLE_ALIGNMENT,
    AgentRef,
    RoleAlignment,
)
from gridalyn.operations.interaction.vocabulary import (
    PERFORMATIVES,
    PROTOCOL_IDS,
    ROLE_IDS,
    Performative,
    ProtocolId,
    RoleId,
)

__all__ = [
    "ACTIVE_FROM_FIELD",
    "ACTIVE_UNTIL_FIELD",
    "DR_PROGRAM_PROTOCOL",
    "FLEX_TRADING_PROTOCOL",
    "MESSAGE_LOG_COLUMNS",
    "PERFORMATIVES",
    "PROTOCOLS",
    "PROTOCOL_IDS",
    "ROLE_ALIGNMENT",
    "ROLE_IDS",
    "AgentRef",
    "Conversation",
    "ConversationBook",
    "ConversationStep",
    "DeadlineTransition",
    "DeliveryHandler",
    "DemandResponseEvent",
    "DemandResponseProgram",
    "LogEntry",
    "Message",
    "MessageBus",
    "MessageLog",
    "MessageTransition",
    "MessageTypeSpec",
    "Performative",
    "ProtocolId",
    "ProtocolSpec",
    "RoleAlignment",
    "RoleId",
    "build_cancellation_payload",
    "build_conversation_book",
    "build_event_payload",
    "build_flex_trading_messages",
    "build_message",
    "build_opt_out_payload",
    "build_report_payload",
    "load_message_log",
    "measure_reported_kwh",
    "resolve_protocol",
    "run_message_transcript",
    "summarize_interaction",
    "write_interaction_report",
    "write_message_log",
]

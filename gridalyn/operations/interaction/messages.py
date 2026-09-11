"""Messages between agents: frozen, content-addressed, canonical JSON payloads.

A :class:`Message` is the unit a conversation advances on and the unit a
message log records. Two properties make a log replayable:

* **The payload is canonical JSON** -- sorted keys, no whitespace, no ``NaN``
  -- held as a string, so a message is immutable all the way down and
  serializes the same way on every machine.
* **The id is the content.** ``message_id`` is the SHA-256 of every other field,
  computed on construction and never passed in. A log row whose stored id does
  not match its content was edited after it was written, and
  :meth:`Message.from_record` refuses it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from gridalyn.operations.interaction.roles import AgentRef
from gridalyn.operations.interaction.vocabulary import (
    Performative,
    ProtocolId,
    parse_performative,
    parse_protocol_id,
    parse_role,
)

#: Flat columns :meth:`Message.to_record` writes, in order.
MESSAGE_RECORD_FIELDS: tuple[str, ...] = (
    "message_id",
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
)


def _plain(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(
        f"a payload value of type {type(value).__name__} is not JSON; convert it "
        "to str, int, float, bool, None, a list or a dict"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_plain,
    )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string; found {value!r}")
    return value


@dataclass(frozen=True)
class Message:
    """One message from one agent to another, inside one conversation.

    Build messages with :func:`build_message`, which canonicalizes a payload
    mapping; constructing one directly requires ``payload_json`` to already be
    a JSON object.

    Attributes:
        conversation_id: The conversation this message belongs to.
        protocol: The protocol that conversation follows.
        message_type: The protocol's name for the message, e.g. ``FlexOrder``.
        performative: The FIPA communicative act the message performs.
        sender: The agent sending it, with the role it sends in.
        receiver: The agent it is addressed to, with the role it receives in.
        sent_at: Simulated time the message is sent.
        payload_json: The payload as canonical JSON.
        message_id: SHA-256 of every field above; derived, never passed.
    """

    conversation_id: str
    protocol: ProtocolId
    message_type: str
    performative: Performative
    sender: AgentRef
    receiver: AgentRef
    sent_at: float
    payload_json: str = "{}"
    message_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate every field, canonicalize the payload and derive the id.

        Raises:
            ValueError: A field is empty or outside its vocabulary, the time is
                not finite, an agent addresses itself, or the payload is not a
                JSON object.
        """
        _require_text(self.conversation_id, "conversation_id")
        _require_text(self.message_type, "message_type")
        parse_protocol_id(self.protocol)
        parse_performative(self.performative)
        sent_at = float(self.sent_at)
        if not math.isfinite(sent_at):
            raise ValueError(f"sent_at must be finite; found {self.sent_at!r}")
        if self.sender.agent_id == self.receiver.agent_id:
            raise ValueError(
                f"{self.message_type} in conversation {self.conversation_id!r} is "
                f"addressed by agent {self.sender.agent_id!r} to itself"
            )
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"{self.message_type} in conversation {self.conversation_id!r}: "
                f"payload_json is not JSON ({exc})"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"{self.message_type} in conversation {self.conversation_id!r}: "
                f"the payload must be a JSON object, found {type(payload).__name__}"
            )
        object.__setattr__(self, "sent_at", sent_at)
        object.__setattr__(self, "payload_json", _canonical_json(payload))
        digest = hashlib.sha256(_canonical_json(self._identity()).encode("utf-8"))
        object.__setattr__(self, "message_id", f"message:sha256:{digest.hexdigest()}")

    def _identity(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "protocol": self.protocol,
            "message_type": self.message_type,
            "performative": self.performative,
            "sender": self.sender.as_dict(),
            "receiver": self.receiver.as_dict(),
            "sent_at": self.sent_at,
            "payload": json.loads(self.payload_json),
        }

    @property
    def payload(self) -> dict[str, Any]:
        """Return a fresh copy of the payload; mutating it changes nothing."""
        return dict(json.loads(self.payload_json))

    def to_record(self) -> dict[str, Any]:
        """Return the message as one flat row, in :data:`MESSAGE_RECORD_FIELDS`."""
        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "protocol": self.protocol,
            "message_type": self.message_type,
            "performative": self.performative,
            "sender_agent_id": self.sender.agent_id,
            "sender_party_id": self.sender.party_id,
            "sender_role": self.sender.role,
            "receiver_agent_id": self.receiver.agent_id,
            "receiver_party_id": self.receiver.party_id,
            "receiver_role": self.receiver.role,
            "sent_at": self.sent_at,
            "payload_json": self.payload_json,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Message:
        """Rebuild a message from a row :meth:`to_record` wrote.

        Args:
            record: A mapping carrying every field in
                :data:`MESSAGE_RECORD_FIELDS`.

        Returns:
            The message, with its id re-derived from its content.

        Raises:
            ValueError: A field is missing or invalid, or the stored id does not
                match the content -- the row was edited after it was written.
        """
        missing = [name for name in MESSAGE_RECORD_FIELDS if name not in record]
        if missing:
            raise ValueError(
                f"message record is missing {', '.join(missing)} (present fields: "
                f"{', '.join(sorted(map(str, record))) or 'none'})"
            )
        message = cls(
            conversation_id=record["conversation_id"],
            protocol=parse_protocol_id(record["protocol"]),
            message_type=record["message_type"],
            performative=parse_performative(record["performative"]),
            sender=AgentRef(
                agent_id=record["sender_agent_id"],
                party_id=record["sender_party_id"],
                role=parse_role(record["sender_role"]),
            ),
            receiver=AgentRef(
                agent_id=record["receiver_agent_id"],
                party_id=record["receiver_party_id"],
                role=parse_role(record["receiver_role"]),
            ),
            sent_at=record["sent_at"],
            payload_json=record["payload_json"],
        )
        if message.message_id != record["message_id"]:
            raise ValueError(
                f"message record {record['message_id']!r} does not match its content "
                f"(recomputed {message.message_id!r}); the record was changed after "
                "it was written"
            )
        return message


def build_message(
    *,
    conversation_id: str,
    protocol: ProtocolId,
    message_type: str,
    performative: Performative,
    sender: AgentRef,
    receiver: AgentRef,
    sent_at: float,
    payload: Mapping[str, Any] | None = None,
) -> Message:
    """Build a message, serializing ``payload`` to canonical JSON.

    Numpy scalars are accepted and written as plain numbers.

    Returns:
        The message, with its content-derived id.

    Raises:
        ValueError: The payload holds ``NaN``/infinity or a value JSON cannot
            carry, or any field is invalid; the message names the message type
            and conversation.
    """
    try:
        payload_json = _canonical_json(dict(payload or {}))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{message_type} in conversation {conversation_id!r}: the payload is "
            f"not canonical JSON ({exc})"
        ) from exc
    return Message(
        conversation_id=conversation_id,
        protocol=protocol,
        message_type=message_type,
        performative=performative,
        sender=sender,
        receiver=receiver,
        sent_at=sent_at,
        payload_json=payload_json,
    )


__all__ = ["MESSAGE_RECORD_FIELDS", "Message", "build_message"]

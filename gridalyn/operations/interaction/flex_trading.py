"""The ``flex_trading`` protocol, and the transcript of a cleared round in its terms.

A conversation is one flexibility request between a distribution operator and
one aggregator, named with UFTP 3.1.0 message names between the USEF 2021 DSO
and AGR roles:

.. code-block:: text

    idle --FlexRequest--> requested --FlexOffer--> offered --FlexOrder--> ordered
                                                   | ^ FlexOffer (revised)   |
                                                   '--FlexOfferRevocation--> revoked
                                                          ordered --FlexSettlement--> settled

The communicative acts follow FIPA's contract-net shape: ``cfp``, ``propose``,
``accept-proposal``, then ``inform``. UFTP has no message rejecting an offer --
an offer that is not ordered simply expires -- so a conversation whose offer
was not ordered ends a round in ``offered``, which is not a terminal state, and
the report counts it as open rather than inventing a rejection. UFTP's
``…Response`` acknowledgements are not modelled: whether a message arrived is
the channel model's question, not the protocol's.

**Payloads are gridalyn's own records**, not UFTP's XML attributes: a
``FlexOffer`` carries :class:`~gridalyn.operations.domain.FlexibilityOffer`
dicts, a ``FlexOrder`` :class:`~gridalyn.operations.domain.DispatchInstruction`
dicts and a ``FlexSettlement``
:class:`~gridalyn.operations.domain.SettlementRecord` dicts.

:func:`build_flex_trading_messages` reads the outputs of a round that has
already cleared and writes them as messages. It reads those frames and changes
nothing: clearing is identical whether or not a transcript is built.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any

import pandas as pd

from gridalyn.operations.domain import (
    DispatchInstruction,
    FlexibilityOffer,
    SettlementRecord,
)
from gridalyn.operations.interaction.messages import Message, build_message
from gridalyn.operations.interaction.protocols import (
    MessageTransition,
    MessageTypeSpec,
    ProtocolSpec,
)
from gridalyn.operations.interaction.roles import AgentRef
from gridalyn.operations.interaction.vocabulary import Performative, RoleId

#: Source declared by every flex_trading message type.
UFTP_SOURCE = "UFTP 3.1.0"

_DSO: tuple[RoleId, ...] = ("distribution_operator",)
_AGR: tuple[RoleId, ...] = ("aggregator",)

FLEX_TRADING_PROTOCOL = ProtocolSpec(
    protocol_id="flex_trading",
    version="1",
    standard="UFTP 3.1.0 message names between the USEF 2021 DSO and AGR roles",
    states=("idle", "requested", "offered", "revoked", "ordered", "settled"),
    initial="idle",
    message_types=(
        MessageTypeSpec(
            "FlexRequest",
            UFTP_SOURCE,
            ("event_id", "constraint_id", "timestep", "required_kw"),
        ),
        MessageTypeSpec("FlexOffer", UFTP_SOURCE, ("offers",)),
        MessageTypeSpec("FlexOfferRevocation", UFTP_SOURCE, ("offer_ids",)),
        MessageTypeSpec("FlexOrder", UFTP_SOURCE, ("instructions",)),
        MessageTypeSpec("FlexSettlement", UFTP_SOURCE, ("settlements",)),
    ),
    transitions=(
        MessageTransition("idle", "FlexRequest", "cfp", _DSO, _AGR, "requested"),
        MessageTransition("requested", "FlexOffer", "propose", _AGR, _DSO, "offered"),
        MessageTransition("offered", "FlexOffer", "propose", _AGR, _DSO, "offered"),
        MessageTransition(
            "offered", "FlexOfferRevocation", "cancel", _AGR, _DSO, "revoked"
        ),
        MessageTransition(
            "offered", "FlexOrder", "accept-proposal", _DSO, _AGR, "ordered"
        ),
        MessageTransition("ordered", "FlexSettlement", "inform", _DSO, _AGR, "settled"),
    ),
)

_EVENT_COLUMNS = ("event_id", "scenario_id", "timestep", "constraint_id", "required_kw")


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        present = ", ".join(map(str, frame.columns)) or "none"
        raise ValueError(
            f"{label} is missing column(s) {', '.join(missing)} (present: {present})"
        )


def _missing_to_none(value: Any) -> Any:
    if value is None:
        return None
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return None
    return value


def _record_rows(
    frame: pd.DataFrame, record_type: type[Any], label: str, id_field: str
) -> list[dict[str, Any]]:
    names = [item.name for item in fields(record_type)]
    _require_columns(frame, names, label)
    rows: list[dict[str, Any]] = []
    for row in frame[names].to_dict("records"):
        values = {name: _missing_to_none(row[name]) for name in names}
        try:
            rows.append(record_type(**values).to_dict())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} row {values[id_field]!r}: {exc}") from exc
    return rows


@dataclass(frozen=True)
class _RoundBooks:
    operator: AgentRef
    offers_by_zone: Mapping[str, list[dict[str, Any]]]
    offers_by_provider: Mapping[str, dict[str, Any]]
    instructions_by_event: Mapping[str, list[dict[str, Any]]]
    settlements_by_instruction: Mapping[str, dict[str, Any]]

    def event_messages(self, event: Mapping[str, Any]) -> list[Message]:
        event_id = str(event["event_id"])
        instructions = self.instructions_by_event.get(event_id, [])
        for row in instructions:
            if row["aggregator_id"] is None:
                raise ValueError(
                    f"dispatch instruction {row['instruction_id']!r} for event "
                    f"{event_id!r} names no aggregator_id; a FlexOrder is addressed "
                    "to an aggregator, so give the provider one in the provider "
                    "registry"
                )
        zone_offers = self.offers_by_zone.get(str(event["constraint_id"]), [])
        aggregators = sorted(
            {row["aggregator_id"] for row in zone_offers}
            | {row["aggregator_id"] for row in instructions}
        )
        messages: list[Message] = []
        for aggregator_id in aggregators:
            own = [row for row in instructions if row["aggregator_id"] == aggregator_id]
            messages.extend(self._conversation(event, aggregator_id, own))
        return messages

    def _offers(
        self,
        constraint_id: str,
        aggregator_id: str,
        instructions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        chosen = {
            row["offer_id"]: row
            for row in self.offers_by_zone.get(constraint_id, [])
            if row["aggregator_id"] == aggregator_id
        }
        for instruction in instructions:
            offer = self.offers_by_provider.get(instruction["provider_id"])
            if offer is None or offer["aggregator_id"] != aggregator_id:
                raise ValueError(
                    f"dispatch instruction {instruction['instruction_id']!r} orders "
                    f"provider {instruction['provider_id']!r} from aggregator "
                    f"{aggregator_id!r}, but the offer book holds no offer of that "
                    "provider from that aggregator; a FlexOrder can only accept an "
                    "offer that was made -- build the book with "
                    "build_provider_offers from the same provider registry"
                )
            chosen[offer["offer_id"]] = offer
        return [chosen[offer_id] for offer_id in sorted(chosen)]

    def _conversation(
        self,
        event: Mapping[str, Any],
        aggregator_id: str,
        instructions: list[dict[str, Any]],
    ) -> list[Message]:
        event_id = str(event["event_id"])
        constraint_id = str(event["constraint_id"])
        aggregator = AgentRef(
            agent_id=aggregator_id, party_id=aggregator_id, role="aggregator"
        )
        conversation_id = f"flex_trading:{event_id}:{aggregator_id}"
        sent_at = float(int(event["timestep"]))
        ordered = sorted(instructions, key=lambda row: str(row["instruction_id"]))
        settlements = [
            self.settlements_by_instruction[row["instruction_id"]]
            for row in ordered
            if row["instruction_id"] in self.settlements_by_instruction
        ]

        def compose(
            message_type: str,
            performative: Performative,
            to_aggregator: bool,
            payload: Mapping[str, Any],
        ) -> Message:
            sender, receiver = (
                (self.operator, aggregator)
                if to_aggregator
                else (aggregator, self.operator)
            )
            return build_message(
                conversation_id=conversation_id,
                protocol="flex_trading",
                message_type=message_type,
                performative=performative,
                sender=sender,
                receiver=receiver,
                sent_at=sent_at,
                payload=payload,
            )

        request = {
            "event_id": event_id,
            "scenario_id": str(event["scenario_id"]),
            "constraint_id": constraint_id,
            "timestep": int(event["timestep"]),
            "required_kw": float(event["required_kw"]),
        }
        offers = self._offers(constraint_id, aggregator_id, ordered)
        messages = [
            compose("FlexRequest", "cfp", True, request),
            compose("FlexOffer", "propose", False, {"offers": offers}),
        ]
        if ordered:
            messages.append(
                compose("FlexOrder", "accept-proposal", True, {"instructions": ordered})
            )
        if ordered and settlements:
            messages.append(
                compose("FlexSettlement", "inform", True, {"settlements": settlements})
            )
        return messages


def build_flex_trading_messages(
    *,
    events: pd.DataFrame,
    offers: pd.DataFrame,
    dispatch: pd.DataFrame,
    settlement: pd.DataFrame,
    operator: AgentRef,
) -> list[Message]:
    """Write a cleared round as ``flex_trading`` messages, in causal order.

    One conversation per event and aggregator: every aggregator holding an
    offer in the event's constraint zone, or ordered for the event, receives a
    ``FlexRequest`` and answers with a ``FlexOffer``. An aggregator with
    dispatch instructions for the event then receives a ``FlexOrder``, and a
    ``FlexSettlement`` when settlement records exist for them. Every message is
    sent at the event's timestep. Events are taken in ``(timestep, event_id)``
    order and aggregators in id order, so the same round always gives the same
    messages.

    Args:
        events: Clearing events (``build_locational_clearing``).
        offers: The offer book (``build_provider_offers``).
        dispatch: Dispatch instructions (``build_dispatch_instructions``).
        settlement: Settlement records (``build_settlement_records``).
        operator: The distribution operator requesting flexibility.

    Returns:
        The messages, ready for :func:`run_message_transcript`.

    Raises:
        ValueError: ``operator`` is not a distribution operator, a frame lacks
            a column, a row is not a valid record, an instruction names no
            aggregator, or an instruction orders a provider that has no offer
            from that aggregator.
    """
    if operator.role != "distribution_operator":
        raise ValueError(
            f"operator {operator.agent_id!r} plays {operator.role!r}; flex_trading "
            "requests come from a 'distribution_operator'"
        )
    _require_columns(events, _EVENT_COLUMNS, "events")
    offers_by_zone: dict[str, list[dict[str, Any]]] = {}
    offers_by_provider: dict[str, dict[str, Any]] = {}
    for row in _record_rows(offers, FlexibilityOffer, "offers", "offer_id"):
        offers_by_provider[row["provider_id"]] = row
        if row["constraint_zone_id"] is not None:
            offers_by_zone.setdefault(row["constraint_zone_id"], []).append(row)
    instructions_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in _record_rows(
        dispatch, DispatchInstruction, "dispatch", "instruction_id"
    ):
        instructions_by_event.setdefault(row["event_id"], []).append(row)
    books = _RoundBooks(
        operator=operator,
        offers_by_zone=offers_by_zone,
        offers_by_provider=offers_by_provider,
        instructions_by_event=instructions_by_event,
        settlements_by_instruction={
            row["instruction_id"]: row
            for row in _record_rows(
                settlement, SettlementRecord, "settlement", "settlement_id"
            )
        },
    )
    event_rows = sorted(
        events[list(_EVENT_COLUMNS)].to_dict("records"),
        key=lambda row: (int(row["timestep"]), str(row["event_id"])),
    )
    messages: list[Message] = []
    for event in event_rows:
        messages.extend(books.event_messages(event))
    return messages


__all__ = ["FLEX_TRADING_PROTOCOL", "UFTP_SOURCE", "build_flex_trading_messages"]

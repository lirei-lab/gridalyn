"""The shipped protocols by id, and a book of the conversations running them.

The protocol set is closed, like the ``ProtocolId`` vocabulary it keys: a
protocol is not resolvable unless it is listed in :data:`PROTOCOLS`, because a
conversation's legality must not depend on what happens to be installed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType

from gridalyn.operations.interaction.dr_program import DR_PROGRAM_PROTOCOL
from gridalyn.operations.interaction.flex_trading import FLEX_TRADING_PROTOCOL
from gridalyn.operations.interaction.messages import Message
from gridalyn.operations.interaction.protocols import Conversation, ProtocolSpec

#: Every shipped protocol, keyed by id.
PROTOCOLS: Mapping[str, ProtocolSpec] = MappingProxyType(
    {spec.protocol_id: spec for spec in (DR_PROGRAM_PROTOCOL, FLEX_TRADING_PROTOCOL)}
)


def resolve_protocol(protocol_id: str) -> ProtocolSpec:
    """Return the shipped protocol with this id.

    Raises:
        KeyError: The id names no shipped protocol; the message lists them.
    """
    try:
        return PROTOCOLS[protocol_id]
    except KeyError:
        known = ", ".join(sorted(PROTOCOLS))
        raise KeyError(f"unknown protocol {protocol_id!r} (known: {known})") from None


class ConversationBook:
    """Every conversation seen so far, created on its first accepted message."""

    def __init__(self) -> None:
        """Start with no conversation."""
        self._conversations: dict[str, Conversation] = {}

    def accept(self, message: Message, *, at: float | None = None) -> Conversation:
        """Advance the message's conversation, starting it if this is its first.

        A first message the protocol refuses starts nothing.

        Args:
            message: The message received.
            at: Simulated receipt time; defaults to ``message.sent_at``.

        Returns:
            The conversation, after the message.

        Raises:
            ValueError: The conversation refuses the message (see
                :meth:`Conversation.accept`).
        """
        conversation = self._conversations.get(message.conversation_id)
        if conversation is None:
            conversation = Conversation(
                resolve_protocol(message.protocol), message.conversation_id
            )
        conversation.accept(message, at=at)
        self._conversations[message.conversation_id] = conversation
        return conversation

    def advance_to(self, time: float) -> int:
        """Advance every conversation's clock to ``time``.

        Returns:
            How many deadline transitions fired, across all conversations.

        Raises:
            ValueError: ``time`` lies before some conversation's clock.
        """
        return sum(self[key].advance_to(time) for key in self)

    def states(self) -> dict[str, str]:
        """Return each conversation's state, keyed by conversation id, sorted."""
        return {key: self[key].state for key in self}

    def __contains__(self, conversation_id: object) -> bool:
        """Return whether a conversation with this id has started."""
        return conversation_id in self._conversations

    def __getitem__(self, conversation_id: str) -> Conversation:
        """Return the conversation with this id.

        Raises:
            KeyError: No such conversation has started.
        """
        try:
            return self._conversations[conversation_id]
        except KeyError:
            raise KeyError(
                f"no conversation {conversation_id!r} has started "
                f"({len(self._conversations)} have)"
            ) from None

    def __iter__(self) -> Iterator[str]:
        """Iterate over conversation ids in sorted order."""
        return iter(sorted(self._conversations))

    def __len__(self) -> int:
        """Return how many conversations have started."""
        return len(self._conversations)


__all__ = ["PROTOCOLS", "ConversationBook", "resolve_protocol"]

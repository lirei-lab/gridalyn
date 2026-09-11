"""A message bus: agents' messages through a channel model, in simulated time.

The bus joins the two simulation pieces agent interaction runs on --
:class:`~gridalyn.simulation.scheduler.EventScheduler` and a
:class:`~gridalyn.simulation.channels.ChannelModel` -- with the protocols
here. Sending asks the channel whether and when a message arrives; a lost
message is logged and never scheduled. Delivering hands the message to its
conversation *before* the receiver's handler runs, so a handler always sees the
conversation already advanced, and a message the protocol refuses stops the
run with the conversation's located error.

**Ordering.** Deliveries at the same simulated time arrive in send order: the
scheduler key is the send sequence, not the message id. The channel still draws
from the message id, so which messages are lost does not depend on send order.

**Sharing a scheduler.** Agents that also schedule their own events (steps,
timers) run the scheduler themselves with a handler that calls
:meth:`MessageBus.deliver` first; :meth:`MessageBus.run_until` and
:meth:`MessageBus.drain` refuse any event that is not one of their messages.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from gridalyn.operations.interaction.conversations import ConversationBook
from gridalyn.operations.interaction.log import LogEntry, LogOutcome, MessageLog
from gridalyn.operations.interaction.messages import Message
from gridalyn.simulation.channels import ChannelModel, Delivery, IdealChannel
from gridalyn.simulation.scheduler import (
    DEFAULT_DRAIN_LIMIT,
    EventScheduler,
    ScheduledEvent,
)

#: Called with each delivered message and its arrival time.
DeliveryHandler = Callable[[Message, float], None]


@dataclass(frozen=True, eq=False)
class _Envelope:
    bus: MessageBus
    sequence: int


class MessageBus:
    """Send messages through a channel and deliver them in simulated time."""

    def __init__(
        self,
        *,
        channel: ChannelModel | None = None,
        scheduler: EventScheduler | None = None,
        conversations: ConversationBook | None = None,
        priority: int = 0,
    ) -> None:
        """Create a bus.

        Args:
            channel: Channel every message crosses; ideal when omitted.
            scheduler: Scheduler deliveries are placed on; a new one at time 0
                when omitted.
            conversations: Book delivered messages advance; a new one when
                omitted.
            priority: Scheduler priority of deliveries, against other events
                at the same time.
        """
        self._channel: ChannelModel = channel if channel is not None else IdealChannel()
        self._scheduler = scheduler if scheduler is not None else EventScheduler()
        self._book = conversations if conversations is not None else ConversationBook()
        self._priority = int(priority)
        self._messages: list[Message] = []
        self._outcomes: list[LogOutcome] = []
        self._delivered_at: list[float | None] = []
        self._delivery_index: list[int | None] = []
        self._delivered = 0

    @property
    def channel(self) -> ChannelModel:
        """Return the channel messages cross."""
        return self._channel

    @property
    def scheduler(self) -> EventScheduler:
        """Return the scheduler deliveries are placed on."""
        return self._scheduler

    @property
    def conversations(self) -> ConversationBook:
        """Return the conversations delivered messages have advanced."""
        return self._book

    @property
    def log(self) -> MessageLog:
        """Return every message sent so far, with its outcome."""
        return MessageLog(
            tuple(
                LogEntry(
                    sequence=sequence,
                    message=message,
                    outcome=self._outcomes[sequence],
                    delivered_at=self._delivered_at[sequence],
                    delivery_index=self._delivery_index[sequence],
                )
                for sequence, message in enumerate(self._messages)
            )
        )

    def send(self, message: Message) -> Delivery:
        """Send a message: ask the channel, log it, and schedule its arrival.

        Args:
            message: The message; ``sent_at`` may not precede the scheduler's
                current time.

        Returns:
            The channel's verdict.

        Raises:
            ValueError: The message is sent in the past, or the channel
                delivers it before it was sent.
        """
        if message.sent_at < self._scheduler.now:
            raise ValueError(
                f"{message.message_type} {message.message_id} in conversation "
                f"{message.conversation_id!r} is sent at {message.sent_at}, before "
                f"the bus's current time {self._scheduler.now}; an agent can only "
                "send now or later"
            )
        delivery = self._channel.transmit(
            key=message.message_id,
            sender=message.sender.agent_id,
            receiver=message.receiver.agent_id,
            sent_at=message.sent_at,
        )
        sequence = len(self._messages)
        if delivery.deliver_at is not None and delivery.deliver_at < message.sent_at:
            raise ValueError(
                f"channel {self._channel.descriptor.channel_model_id!r} delivers "
                f"{message.message_id} at {delivery.deliver_at}, before it was sent "
                f"at {message.sent_at}"
            )
        self._messages.append(message)
        self._delivered_at.append(None)
        self._delivery_index.append(None)
        if delivery.deliver_at is None:
            self._outcomes.append("lost")
            return delivery
        self._outcomes.append("in_flight")
        self._scheduler.schedule(
            time=delivery.deliver_at,
            key=f"message:{sequence:012d}",
            payload=_Envelope(self, sequence),
            priority=self._priority,
        )
        return delivery

    def deliver(
        self, event: ScheduledEvent, handler: DeliveryHandler | None = None
    ) -> bool:
        """Deliver ``event`` if it is one of this bus's messages.

        Args:
            event: An event popped from the scheduler.
            handler: Called with the message and its arrival time, after its
                conversation has accepted it.

        Returns:
            Whether the event was a message of this bus.

        Raises:
            ValueError: The message's conversation refuses it.
        """
        envelope = event.payload
        if not isinstance(envelope, _Envelope) or envelope.bus is not self:
            return False
        sequence = envelope.sequence
        message = self._messages[sequence]
        self._book.accept(message, at=event.time)
        self._outcomes[sequence] = "delivered"
        self._delivered_at[sequence] = event.time
        self._delivery_index[sequence] = self._delivered
        self._delivered += 1
        if handler is not None:
            handler(message, event.time)
        return True

    def _only_messages(
        self, handler: DeliveryHandler | None
    ) -> Callable[[ScheduledEvent], None]:
        def handle(event: ScheduledEvent) -> None:
            if not self.deliver(event, handler):
                raise ValueError(
                    f"event {event.key!r} at time {event.time} is not a message on "
                    "this bus; when agents share the scheduler, run it directly "
                    "with a handler that calls bus.deliver(event) first"
                )

        return handle

    def run_until(self, time: float, handler: DeliveryHandler | None = None) -> int:
        """Deliver every message arriving by ``time``, then advance conversations.

        Handlers may send further messages; those arriving by ``time`` are
        delivered in the same call. Every conversation ends with its clock at
        ``time``, so deadlines passed by then have fired.

        Returns:
            How many messages were delivered.
        """
        delivered = self._scheduler.run_until(time, self._only_messages(handler))
        self._book.advance_to(self._scheduler.now)
        return delivered

    def drain(
        self,
        handler: DeliveryHandler | None = None,
        *,
        limit: int = DEFAULT_DRAIN_LIMIT,
    ) -> int:
        """Deliver every scheduled message, including those handlers send.

        Every conversation ends with its clock at the time of the last event.

        Returns:
            How many messages were delivered.
        """
        delivered = self._scheduler.drain(self._only_messages(handler), limit=limit)
        self._book.advance_to(self._scheduler.now)
        return delivered


def run_message_transcript(messages: Iterable[Message]) -> MessageBus:
    """Send a fixed sequence of messages through an ideal channel and deliver them.

    For messages written after the fact -- such as
    :func:`~gridalyn.operations.interaction.flex_trading.build_flex_trading_messages`
    -- rather than by agents reacting to each other. Messages arrive in the order
    given (at equal times) and every conversation validates them.

    Args:
        messages: The messages, in causal order.

    Returns:
        The drained bus; read ``log``, ``conversations`` and ``scheduler.now``.

    Raises:
        ValueError: A conversation refuses a message.
    """
    ordered = list(messages)
    start = min((message.sent_at for message in ordered), default=0.0)
    bus = MessageBus(scheduler=EventScheduler(start_time=start))
    for message in ordered:
        bus.send(message)
    bus.drain()
    return bus


__all__ = ["DeliveryHandler", "MessageBus", "run_message_transcript"]

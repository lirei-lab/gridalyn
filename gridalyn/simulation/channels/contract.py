"""Contract for communication-channel models between simulated agents.

A channel model answers one question for one message: does it arrive, and at
what simulated time? It is a *role* in the same sense as a power-flow backend
or a surrogate: resolved by explicit ID through
:mod:`gridalyn.simulation.channels.registry`, carrying a descriptor whose
``as_dict`` is written verbatim wherever a run records what it used -- so two
runs that differ only in communication are distinguishable from their records.

**Determinism is a property of the message, not of call order.** Stochastic
models draw from the seed and the message's identity (key, sender, receiver)
only; transmitting the same messages in another order produces the same
deliveries. That is what makes a channel reproducible inside a discrete-event
simulation whose handlers run in a data-dependent order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: Zero latency, no loss. The default: it reproduces a synchronous step loop.
IDEAL_CHANNEL_ID = "ideal"

#: Every message delayed by the same latency; none lost.
FIXED_LATENCY_CHANNEL_ID = "fixed_latency"

#: Each message lost independently with a fixed probability.
BERNOULLI_LOSS_CHANNEL_ID = "bernoulli_loss"

#: A fixed set of silent endpoints, chosen once; every message to or from one is
#: lost. Reproduces a communication-failure sweep that removes an exact count.
FIXED_OUTAGE_CHANNEL_ID = "fixed_outage"

#: The channel used when a caller names none.
DEFAULT_CHANNEL_MODEL_ID = IDEAL_CHANNEL_ID


@dataclass(frozen=True)
class ChannelModelDescriptor:
    """Identity and parameters of a channel model.

    Attributes:
        channel_model_id: Stable ID a caller resolves the model by.
        name: Human-readable description for reports and manifests.
        parameters: What this instance was constructed with, including its
            seed when it draws randomness -- the record of *which* channel ran.
        contract_version: Version of this contract the model implements.
    """

    channel_model_id: str
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the descriptor for provenance."""
        return {
            "channel_model_id": self.channel_model_id,
            "name": self.name,
            "parameters": dict(self.parameters),
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class Delivery:
    """The outcome of transmitting one message.

    Attributes:
        deliver_at: Simulated time the message arrives, or ``None`` when lost.
    """

    deliver_at: float | None

    @property
    def delivered(self) -> bool:
        """Return whether the message arrives at all."""
        return self.deliver_at is not None


@runtime_checkable
class ChannelModel(Protocol):
    """Decide whether, and when, a message between two agents arrives."""

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        """Return what a run records about this channel."""

    def transmit(
        self, *, key: str, sender: str, receiver: str, sent_at: float
    ) -> Delivery:
        """Return the delivery of one message.

        Args:
            key: Stable message identifier; stochastic models draw from it.
            sender: Identifier of the sending agent.
            receiver: Identifier of the receiving agent.
            sent_at: Simulated time the message is sent.
        """


def describe_channel_model(factory: Any) -> ChannelModelDescriptor:
    """Return the descriptor a channel-model factory declares.

    Args:
        factory: A channel-model class carrying a ``DESCRIPTOR`` attribute.

    Returns:
        The declared descriptor.

    Raises:
        TypeError: ``factory`` declares no usable ``DESCRIPTOR``; the message
            names the factory and what to add.
    """
    descriptor = getattr(factory, "DESCRIPTOR", None)
    if not isinstance(descriptor, ChannelModelDescriptor):
        name = getattr(factory, "__name__", type(factory).__name__)
        found = type(descriptor).__name__ if descriptor is not None else "nothing"
        raise TypeError(
            f"channel-model factory {name} declares no descriptor (found "
            f"{found}); add a class attribute DESCRIPTOR: ChannelModelDescriptor, "
            "or pass descriptor=... to ChannelModelRegistry.register"
        )
    return descriptor


__all__ = [
    "BERNOULLI_LOSS_CHANNEL_ID",
    "DEFAULT_CHANNEL_MODEL_ID",
    "FIXED_LATENCY_CHANNEL_ID",
    "FIXED_OUTAGE_CHANNEL_ID",
    "IDEAL_CHANNEL_ID",
    "ChannelModel",
    "ChannelModelDescriptor",
    "Delivery",
    "describe_channel_model",
]

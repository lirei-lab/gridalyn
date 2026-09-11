"""The channel models gridalyn ships.

Four, chosen from what the repository's studies already model by hand
(measured 2026-09-11):

* :class:`IdealChannel` -- what every study assumes today. ``ev_hosting_flex``
  decides and acts within the same step, with no latency and no loss, and
  ``run_policy_episode`` applies a decision at the next step. An ideal channel
  must therefore reproduce a synchronous loop exactly.
* :class:`FixedLatencyChannel` -- the smallest departure from ideal.
* :class:`BernoulliLossChannel` -- independent per-message loss.
* :class:`FixedOutageChannel` -- ``admm_thermal_consensus`` removes an *exact*
  ``round(fraction * N)`` agents for a whole solve, as nested prefixes of one
  seeded permutation. Independent per-message loss cannot reproduce that
  count, so it is its own model.

**The randomness contract**, written down because the repository has no shared
seed-derivation convention: a message's uniform draw is the first
``numpy.random.default_rng([seed, h]).random()``, where ``h`` is the first 8
bytes (big-endian) of the SHA-256 of ``key``, ``sender`` and ``receiver`` joined
by the unit separator ``\\x1f``. The draw depends on the seed and the message
identity only, never on how many messages were transmitted before it.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

import numpy as np

from gridalyn.simulation.channels.contract import (
    BERNOULLI_LOSS_CHANNEL_ID,
    FIXED_LATENCY_CHANNEL_ID,
    FIXED_OUTAGE_CHANNEL_ID,
    IDEAL_CHANNEL_ID,
    ChannelModelDescriptor,
    Delivery,
)

_UNIT_SEPARATOR = "\x1f"


def _require_latency(latency: float) -> float:
    value = float(latency)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(
            f"latency must be a finite, non-negative time; found {latency!r}"
        )
    return value


def _require_fraction(value: float, label: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{label} must lie in [0, 1]; found {value!r}")
    return number


def _require_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be a non-negative int; found {seed!r}")
    return seed


def _message_uniform(seed: int, key: str, sender: str, receiver: str) -> float:
    identity = _UNIT_SEPARATOR.join((key, sender, receiver)).encode("utf-8")
    digest = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big")
    return float(np.random.default_rng([seed, digest]).random())


class IdealChannel:
    """Deliver every message at the time it is sent."""

    DESCRIPTOR = ChannelModelDescriptor(
        channel_model_id=IDEAL_CHANNEL_ID,
        name="ideal channel: zero latency, no loss",
    )

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        """Return the ideal channel's descriptor; it has no parameters."""
        return self.DESCRIPTOR

    def transmit(
        self, *, key: str, sender: str, receiver: str, sent_at: float
    ) -> Delivery:
        """Deliver the message at ``sent_at``."""
        return Delivery(deliver_at=float(sent_at))


class FixedLatencyChannel:
    """Deliver every message after the same latency."""

    DESCRIPTOR = ChannelModelDescriptor(
        channel_model_id=FIXED_LATENCY_CHANNEL_ID,
        name="fixed latency, no loss",
        parameters={"latency": 0.0},
    )

    def __init__(self, latency: float = 0.0) -> None:
        """Build the channel.

        Args:
            latency: Simulated time every message takes to arrive.

        Raises:
            ValueError: ``latency`` is negative or not finite.
        """
        self._latency = _require_latency(latency)
        self._descriptor = ChannelModelDescriptor(
            channel_model_id=FIXED_LATENCY_CHANNEL_ID,
            name=self.DESCRIPTOR.name,
            parameters={"latency": self._latency},
        )

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        """Return the descriptor, recording the latency."""
        return self._descriptor

    def transmit(
        self, *, key: str, sender: str, receiver: str, sent_at: float
    ) -> Delivery:
        """Deliver the message ``latency`` after ``sent_at``."""
        return Delivery(deliver_at=float(sent_at) + self._latency)


class BernoulliLossChannel:
    """Lose each message independently with probability ``loss_probability``."""

    DESCRIPTOR = ChannelModelDescriptor(
        channel_model_id=BERNOULLI_LOSS_CHANNEL_ID,
        name="independent per-message loss",
        parameters={"loss_probability": 0.0, "seed": 0, "latency": 0.0},
    )

    def __init__(
        self, loss_probability: float, seed: int, latency: float = 0.0
    ) -> None:
        """Build the channel.

        Args:
            loss_probability: Probability each message is lost, in ``[0, 1]``.
            seed: Non-negative seed of the per-message draws.
            latency: Simulated time a delivered message takes to arrive.

        Raises:
            ValueError: A parameter lies outside its domain.
        """
        self._loss_probability = _require_fraction(loss_probability, "loss_probability")
        self._seed = _require_seed(seed)
        self._latency = _require_latency(latency)
        self._descriptor = ChannelModelDescriptor(
            channel_model_id=BERNOULLI_LOSS_CHANNEL_ID,
            name=self.DESCRIPTOR.name,
            parameters={
                "loss_probability": self._loss_probability,
                "seed": self._seed,
                "latency": self._latency,
            },
        )

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        """Return the descriptor, recording probability, seed and latency."""
        return self._descriptor

    def transmit(
        self, *, key: str, sender: str, receiver: str, sent_at: float
    ) -> Delivery:
        """Lose the message when its draw falls below ``loss_probability``."""
        if _message_uniform(self._seed, key, sender, receiver) < self._loss_probability:
            return Delivery(deliver_at=None)
        return Delivery(deliver_at=float(sent_at) + self._latency)


class FixedOutageChannel:
    """Silence an exact, seeded subset of endpoints for the channel's lifetime.

    The silent endpoints are ``endpoints[i]`` for ``i`` in the first
    ``round(outage_fraction * len(endpoints))`` entries of
    ``numpy.random.default_rng(seed).permutation(len(endpoints))``. With one
    seed, a larger fraction silences a superset of a smaller one.
    """

    DESCRIPTOR = ChannelModelDescriptor(
        channel_model_id=FIXED_OUTAGE_CHANNEL_ID,
        name="fixed outage: exact seeded subset of silent endpoints",
        parameters={"outage_fraction": 0.0, "seed": 0, "latency": 0.0},
    )

    def __init__(
        self,
        endpoints: Sequence[str],
        outage_fraction: float,
        seed: int,
        latency: float = 0.0,
    ) -> None:
        """Build the channel.

        Args:
            endpoints: Every agent the channel connects, in a stable order; the
                permutation indexes this order.
            outage_fraction: Share of endpoints silenced, in ``[0, 1]``.
            seed: Non-negative seed of the permutation.
            latency: Simulated time a delivered message takes to arrive.

        Raises:
            ValueError: A parameter lies outside its domain, or ``endpoints``
                repeats an identifier.
        """
        names = [str(endpoint) for endpoint in endpoints]
        if len(set(names)) != len(names):
            raise ValueError("endpoints must not repeat an identifier")
        self._fraction = _require_fraction(outage_fraction, "outage_fraction")
        self._seed = _require_seed(seed)
        self._latency = _require_latency(latency)
        silent_count = int(round(self._fraction * len(names)))
        order = np.random.default_rng(self._seed).permutation(len(names))
        self._silent = tuple(names[int(index)] for index in order[:silent_count])
        self._silent_set = frozenset(self._silent)
        self._descriptor = ChannelModelDescriptor(
            channel_model_id=FIXED_OUTAGE_CHANNEL_ID,
            name=self.DESCRIPTOR.name,
            parameters={
                "endpoint_count": len(names),
                "outage_fraction": self._fraction,
                "silent_count": silent_count,
                "seed": self._seed,
                "latency": self._latency,
            },
        )

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        """Return the descriptor, recording counts, fraction, seed and latency."""
        return self._descriptor

    @property
    def silent_endpoints(self) -> tuple[str, ...]:
        """Return the silenced endpoints, in permutation order."""
        return self._silent

    def transmit(
        self, *, key: str, sender: str, receiver: str, sent_at: float
    ) -> Delivery:
        """Lose any message whose sender or receiver is silent."""
        if sender in self._silent_set or receiver in self._silent_set:
            return Delivery(deliver_at=None)
        return Delivery(deliver_at=float(sent_at) + self._latency)


__all__ = [
    "BernoulliLossChannel",
    "FixedLatencyChannel",
    "FixedOutageChannel",
    "IdealChannel",
]

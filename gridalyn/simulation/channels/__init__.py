"""Communication-channel models between simulated agents: contract, models, registry.

Imports eagerly: the whole package needs only ``numpy`` and the standard
library, so importing it can pull no optional dependency -- the behavioural
rule ``tests/test_import_hygiene.py`` enforces -- and a lazy map would add
indirection for no import cost saved.
"""

from __future__ import annotations

from gridalyn.simulation.channels.contract import (
    BERNOULLI_LOSS_CHANNEL_ID,
    DEFAULT_CHANNEL_MODEL_ID,
    FIXED_LATENCY_CHANNEL_ID,
    FIXED_OUTAGE_CHANNEL_ID,
    IDEAL_CHANNEL_ID,
    ChannelModel,
    ChannelModelDescriptor,
    Delivery,
    describe_channel_model,
)
from gridalyn.simulation.channels.models import (
    BernoulliLossChannel,
    FixedLatencyChannel,
    FixedOutageChannel,
    IdealChannel,
)
from gridalyn.simulation.channels.registry import (
    ChannelModelRegistration,
    ChannelModelRegistry,
    UnknownChannelModelError,
    default_channel_model_registry,
    register_channel_model_extension,
    resolve_channel_model,
)

__all__ = [
    "BERNOULLI_LOSS_CHANNEL_ID",
    "DEFAULT_CHANNEL_MODEL_ID",
    "FIXED_LATENCY_CHANNEL_ID",
    "FIXED_OUTAGE_CHANNEL_ID",
    "IDEAL_CHANNEL_ID",
    "BernoulliLossChannel",
    "ChannelModel",
    "ChannelModelDescriptor",
    "ChannelModelRegistration",
    "ChannelModelRegistry",
    "Delivery",
    "FixedLatencyChannel",
    "FixedOutageChannel",
    "IdealChannel",
    "UnknownChannelModelError",
    "default_channel_model_registry",
    "describe_channel_model",
    "register_channel_model_extension",
    "resolve_channel_model",
]

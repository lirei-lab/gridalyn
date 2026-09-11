"""Registry for channel models, resolved by explicit ID only.

The fourth component registry, and deliberately the same mechanism as
:mod:`gridalyn.simulation.backends.registry`: a frozen registration pairing a
descriptor with a factory, ``register(..., replace=False, source=..., version=...)``,
``get_descriptor``, ``registration_source``, ``registration_version``,
``list_descriptors()`` sorted by ID, ``create(id, **kwargs)`` and a located error
enumerating the available IDs. ``tests/test_registry_parity.py`` holds it to that.

**There is no discovery.** A channel that is not explicitly registered is not
resolvable, because an ambient plugin would change which messages arrive
without appearing in any record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.foundation.platform.extensions import (
    SUPPORTED_CONTRACT_VERSIONS,
    ExtensionSource,
    UnsupportedContractVersionError,
)
from gridalyn.simulation.channels.contract import (
    DEFAULT_CHANNEL_MODEL_ID,
    ChannelModel,
    ChannelModelDescriptor,
    describe_channel_model,
)
from gridalyn.simulation.channels.models import (
    BernoulliLossChannel,
    FixedLatencyChannel,
    FixedOutageChannel,
    IdealChannel,
)


class UnknownChannelModelError(KeyError):
    """Raised when a requested channel model is not registered."""


@dataclass(frozen=True)
class ChannelModelRegistration:
    """Factory, descriptor and registration source for a channel model.

    Attributes:
        descriptor: What the registry records about the model.
        factory: Callable producing a model instance.
        source: ``"core"`` for the shipped models, ``"host"`` when registered
            through :func:`register_channel_model_extension`.
        version: Optional semantic version recorded by a host extension.
    """

    descriptor: ChannelModelDescriptor
    factory: Callable[..., ChannelModel]
    source: ExtensionSource = "core"
    version: str | None = None


class ChannelModelRegistry:
    """Resolve channel models by stable, explicitly registered ID."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registrations: dict[str, ChannelModelRegistration] = {}

    def register(
        self,
        factory: Callable[..., ChannelModel],
        *,
        descriptor: ChannelModelDescriptor | None = None,
        replace: bool = False,
        source: ExtensionSource = "core",
        version: str | None = None,
    ) -> None:
        """Register a channel-model factory under its descriptor's ID.

        Args:
            factory: Callable returning a :class:`ChannelModel`.
            descriptor: Descriptor to register under. Defaults to the one the
                factory declares.
            replace: Allow overwriting an already-registered ID.
            source: ``"core"`` for shipped models, ``"host"`` for a host
                extension; only :data:`ExtensionSource` values are accepted.
            version: Optional semantic version when an extension supplies one.

        Raises:
            UnsupportedContractVersionError: The descriptor declares a contract
                version this engine does not support.
            ValueError: ``source`` is unknown, or the ID is taken and
                ``replace`` is false.
        """
        model_descriptor = descriptor or describe_channel_model(factory)
        model_id = model_descriptor.channel_model_id
        if model_descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"channel model {model_id!r} declares contract version "
                f"{model_descriptor.contract_version!r}, but this engine supports "
                f"only: {supported}; upgrade or pin the extension to a supported "
                "contract version"
            )
        valid_sources: tuple[ExtensionSource, ...] = ("core", "host", "entry_point")
        if source not in valid_sources:
            raise ValueError(
                f"channel model {model_id!r} declares unknown source {source!r} "
                f"(expected one of: {', '.join(valid_sources)})"
            )
        if model_id in self._registrations and not replace:
            raise ValueError(
                f"channel model already registered: {model_id} "
                "(pass replace=True to override it deliberately)"
            )
        self._registrations[model_id] = ChannelModelRegistration(
            descriptor=model_descriptor,
            factory=factory,
            source=source,
            version=version,
        )

    def get_descriptor(self, channel_model_id: str) -> ChannelModelDescriptor:
        """Return descriptor metadata for a registered channel model.

        Args:
            channel_model_id: The registered ID.
        """
        return self._registration(channel_model_id).descriptor

    def registration_source(self, channel_model_id: str) -> ExtensionSource:
        """Return the source a channel model was registered under.

        Args:
            channel_model_id: The registered ID.
        """
        return self._registration(channel_model_id).source

    def registration_version(self, channel_model_id: str) -> str | None:
        """Return the semantic version an extension recorded, if any.

        Args:
            channel_model_id: The registered ID.
        """
        return self._registration(channel_model_id).version

    def list_descriptors(self) -> list[ChannelModelDescriptor]:
        """Return registered descriptors sorted by channel-model ID."""
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def create(self, channel_model_id: str, **kwargs: Any) -> ChannelModel:
        """Instantiate a registered channel model.

        Args:
            channel_model_id: The registered ID; no discovery, no fallback.
            **kwargs: Parameters forwarded to the model factory.

        Raises:
            UnknownChannelModelError: ``channel_model_id`` is not registered.
        """
        return self._registration(channel_model_id).factory(**kwargs)

    def _registration(self, channel_model_id: str) -> ChannelModelRegistration:
        try:
            return self._registrations[channel_model_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none registered"
            raise UnknownChannelModelError(
                f"unknown channel model: {channel_model_id!r} (available channel "
                f"models: {available}); channel models resolve by explicit ID "
                "only -- register one with ChannelModelRegistry.register before "
                "resolving it"
            ) from exc


_DEFAULT_CHANNEL_MODEL_REGISTRY: ChannelModelRegistry | None = None


def default_channel_model_registry() -> ChannelModelRegistry:
    """Return the shared default registry of channel models.

    Built once and cached, so an extension registered through
    :func:`register_channel_model_extension` stays resolvable on the default
    path. Building it registers the shipped models and constructs none.
    """
    global _DEFAULT_CHANNEL_MODEL_REGISTRY
    if _DEFAULT_CHANNEL_MODEL_REGISTRY is None:
        registry = ChannelModelRegistry()
        registry.register(IdealChannel)
        registry.register(FixedLatencyChannel)
        registry.register(BernoulliLossChannel)
        registry.register(FixedOutageChannel)
        _DEFAULT_CHANNEL_MODEL_REGISTRY = registry
    return _DEFAULT_CHANNEL_MODEL_REGISTRY


def register_channel_model_extension(
    factory: Callable[..., ChannelModel],
    *,
    descriptor: ChannelModelDescriptor,
    replace: bool = False,
    version: str | None = None,
    registry: ChannelModelRegistry | None = None,
) -> None:
    """Register an external channel model (host API).

    The registration is recorded with ``source="host"`` and the given
    ``version``, so a record can name the extension that served the role.

    Args:
        factory: Callable returning a :class:`ChannelModel`.
        descriptor: Descriptor declaring the model's identity and contract
            version.
        replace: Allow overwriting an already-registered ID.
        version: Optional semantic version of the extension.
        registry: Registry to register into; defaults to the shared default.
    """
    (registry or default_channel_model_registry()).register(
        factory,
        descriptor=descriptor,
        replace=replace,
        source="host",
        version=version,
    )


def resolve_channel_model(
    channel_model_id: str = DEFAULT_CHANNEL_MODEL_ID,
    **parameters: Any,
) -> ChannelModel:
    """Resolve one channel model from the default registry by explicit ID.

    Args:
        channel_model_id: Registered ID; defaults to the ideal channel.
        **parameters: Parameters forwarded to the model factory.
    """
    return default_channel_model_registry().create(channel_model_id, **parameters)


__all__ = [
    "ChannelModelRegistration",
    "ChannelModelRegistry",
    "UnknownChannelModelError",
    "default_channel_model_registry",
    "register_channel_model_extension",
    "resolve_channel_model",
]

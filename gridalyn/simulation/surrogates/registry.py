"""Registry for surrogates, resolved by explicit ID only.

Modelled on :mod:`gridalyn.twin.adapters.registry`: a frozen registration
pairing a descriptor with a factory, ``register(..., replace=False)``,
``get_descriptor``, ``list_descriptors()`` sorted by ID,
``create(surrogate_id, **kwargs)`` and a located error enumerating the
available IDs.

Two rules are enforced here rather than left to convention:

* **No discovery.** No ``entry_points``, no plugin scan, no environment
  variable. A surrogate that is not explicitly registered is not resolvable,
  because an ambient plugin would change screening results without appearing
  in any governed artifact -- the failure mode that forced
  ``provenance.macro_model`` into existence.
* **No unbounded surrogate.** ``register`` refuses a descriptor whose
  ``error_bound`` is ``None``. A fast estimate whose accuracy is unknown
  cannot be traced from a market or screening decision back to a physical
  claim, so it does not belong in the registry at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.simulation.analytics.network_impact.physics_model import (
    NetworkImpactPhysicsLookupSurrogate,
)
from gridalyn.simulation.analytics.network_impact.surrogate import (
    NetworkImpactTabularSurrogate,
)
from gridalyn.simulation.surrogates.contract import (
    Surrogate,
    SurrogateDescriptor,
    describe_surrogate,
)

#: The surrogate resolved when a caller names none. The deterministic
#: topology surrogate is the one whose artifacts the flexibility pipeline
#: already writes, so it is the compatible default -- not the accurate one.
#: Its stated bound is roughly two hundred times looser than the
#: physics-fitted alternative; read ``descriptor.error_bound`` before using it
#: for anything beyond screening.
DEFAULT_SURROGATE_ID = NetworkImpactTabularSurrogate.DESCRIPTOR.surrogate_id


class UnknownSurrogateError(KeyError):
    """Raised when a requested surrogate is not registered."""


class UnboundedSurrogateError(ValueError):
    """Raised when a surrogate is registered without a stated error bound."""


@dataclass(frozen=True)
class SurrogateRegistration:
    """Factory and descriptor for a registered surrogate."""

    descriptor: SurrogateDescriptor
    factory: Callable[..., Surrogate]


class SurrogateRegistry:
    """Resolve surrogates by stable, explicitly registered ID."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registrations: dict[str, SurrogateRegistration] = {}

    def register(
        self,
        factory: Callable[..., Surrogate],
        *,
        descriptor: SurrogateDescriptor | None = None,
        replace: bool = False,
    ) -> None:
        """Register a surrogate factory under its descriptor's ID.

        Args:
            factory: Callable returning a
                :class:`~gridalyn.simulation.surrogates.contract.Surrogate`.
            descriptor: Descriptor to register under. Defaults to the one the
                factory declares.
            replace: Allow overwriting an already-registered ID.

        Raises:
            UnboundedSurrogateError: If the descriptor states no error bound.
            ValueError: If the ID is taken and ``replace`` is false. The
                message names the ID and the flag that would permit it.
        """
        surrogate_descriptor = descriptor or describe_surrogate(factory)
        surrogate_id = surrogate_descriptor.surrogate_id
        if surrogate_descriptor.error_bound is None:
            raise UnboundedSurrogateError(
                f"surrogate {surrogate_id!r} declares no error bound; every "
                "registered surrogate must state one, because a screening or "
                "market decision taken on its estimate has to be traceable to "
                "a known accuracy. Set SurrogateDescriptor.error_bound to a "
                "measured ErrorBound, or to unmeasured_error_bound(...) with a "
                "located reason if it cannot be measured"
            )
        if surrogate_id in self._registrations and not replace:
            raise ValueError(
                f"surrogate already registered: {surrogate_id} "
                "(pass replace=True to override it deliberately)"
            )
        self._registrations[surrogate_id] = SurrogateRegistration(
            descriptor=surrogate_descriptor,
            factory=factory,
        )

    def get_descriptor(self, surrogate_id: str) -> SurrogateDescriptor:
        """Return descriptor metadata for a registered surrogate.

        Args:
            surrogate_id: The registered ID.

        Returns:
            The registered descriptor, including its stated error bound.
        """
        return self._registration(surrogate_id).descriptor

    def list_descriptors(self) -> list[SurrogateDescriptor]:
        """Return registered surrogate descriptors sorted by surrogate ID.

        Returns:
            One descriptor per registration, ordered by ID so callers and
            reports see a stable sequence.
        """
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def create(self, surrogate_id: str, **kwargs: Any) -> Surrogate:
        """Instantiate a registered surrogate.

        Args:
            surrogate_id: The registered ID; no discovery, no fallback.
            **kwargs: Settings forwarded to the surrogate factory.

        Returns:
            A ready-to-use surrogate.

        Raises:
            UnknownSurrogateError: If ``surrogate_id`` is not registered.
        """
        return self._registration(surrogate_id).factory(**kwargs)

    def _registration(self, surrogate_id: str) -> SurrogateRegistration:
        try:
            return self._registrations[surrogate_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none registered"
            raise UnknownSurrogateError(
                f"unknown surrogate: {surrogate_id!r} "
                f"(available surrogates: {available}); surrogates resolve by "
                "explicit ID only -- register one with "
                "SurrogateRegistry.register before resolving it"
            ) from exc


def default_surrogate_registry() -> SurrogateRegistry:
    """Build the default registry of surrogates.

    Returns:
        A fresh registry holding exactly the surrogates this repository ships:
        the deterministic topology surrogate behind
        ``network_impact_predictions.parquet``, and the physics-fitted lookup
        behind ``network_impact_physics_predictions.parquet``. Fresh per call,
        so a test registering into one cannot pollute another.
    """
    registry = SurrogateRegistry()
    registry.register(NetworkImpactTabularSurrogate)
    registry.register(NetworkImpactPhysicsLookupSurrogate)
    return registry


def resolve_surrogate(
    surrogate_id: str = DEFAULT_SURROGATE_ID,
    **settings: Any,
) -> Surrogate:
    """Resolve one surrogate from the default registry by explicit ID.

    Args:
        surrogate_id: Registered surrogate ID.
        **settings: Settings forwarded to the surrogate factory.

    Returns:
        A ready-to-use surrogate.
    """
    return default_surrogate_registry().create(surrogate_id, **settings)


def registered_error_bounds() -> dict[str, dict[str, Any]]:
    """Return every registered surrogate's stated error bound, by ID.

    Returns:
        A plain-JSON mapping suitable for embedding in a verification report,
        so a report states the accuracy of every surrogate it could have used
        rather than only the one it did.
    """
    return {
        descriptor.surrogate_id: descriptor.as_dict()
        for descriptor in default_surrogate_registry().list_descriptors()
    }


__all__ = [
    "DEFAULT_SURROGATE_ID",
    "SurrogateRegistration",
    "SurrogateRegistry",
    "UnboundedSurrogateError",
    "UnknownSurrogateError",
    "default_surrogate_registry",
    "registered_error_bounds",
    "resolve_surrogate",
]

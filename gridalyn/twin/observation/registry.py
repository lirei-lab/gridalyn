"""Registry of observation producers, resolved by explicit ID.

Two real producers of one contract register here on day one:

``"powerflow"``
    :func:`gridalyn.twin.observation.contract.observe_network` -- reads
    observed state off a solved network's result tables and stamps
    ``provenance="simulated"``.
``"measured-ingest"``
    :func:`gridalyn.twin.observation.ingest.read_measured_observations` --
    reads tidy ``(timestamp, entity_id, quantity, value)`` measurement rows
    against a user-declared entity-to-bus join and stamps
    ``provenance="measured"`` with ``as_of`` from the datum.

**Why this registry exists now and did not exist in Phase 11.** Phase 11
declined to build it and pinned the refusal with
``test_no_state_producer_registry_was_built``, whose docstring recorded the
superseded reason: "``twin/observation`` ships a contract and no registry,
deliberately. The absence is the decision, so it is asserted rather than left
to be rediscovered." One producer plus a placeholder is the speculative
abstraction plan 10-03 declined for this same contract. Phase 12's measured
ingest is the second *real* producer, so the ``>=2``-consumer rule is now
satisfied by construction rather than by argument, and MILESTONE-6 is
near-directive about the consequence: "Phase 11 correctly declined a registry
for a single implementation; this milestone must not decline one for two."

**Shape.** Modeled on :mod:`gridalyn.twin.adapters.registry`: a frozen
descriptor per registration, lookup by stable ID, duplicate registration
without ``replace=True`` is a ``ValueError``, and an unknown ID is a located
error listing the available IDs. One deliberate divergence from that model:
observation producers are *functions*, not instantiable adapter classes, so
:meth:`ObservationProducerRegistry.resolve` returns the registered callable
itself where ``NetworkAdapterRegistry.create`` instantiates a class. The
registry hands back the real producers, never wrappers, so ``resolve`` is the
identity of the function that was registered.

**Explicit IDs only.** No ``entry_points``, no ``importlib.metadata``
discovery, no ambient plugin loading -- Phase 10's recorded rule: ambient
plugins change results without appearing in provenance. The rule is pinned by
an AST scan over this module's import nodes in
``tests/test_observation_producer_registry.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gridalyn.foundation.platform.extensions import (
    SUPPORTED_CONTRACT_VERSIONS,
    UnsupportedContractVersionError,
)
from gridalyn.twin.observation.contract import (
    NetworkObservation,
    ObservationProvenance,
    observe_network,
)
from gridalyn.twin.observation.ingest import read_measured_observations

#: What a registered producer is: a plain callable that yields the contract's
#: objects. The two shipped producers differ in cardinality --
#: ``observe_network`` returns one observation, ``read_measured_observations``
#: returns one per instant -- so the alias admits both.
ObservationProducer = Callable[..., NetworkObservation | tuple[NetworkObservation, ...]]

#: Stable ID of the simulated producer.
POWERFLOW_PRODUCER_ID = "powerflow"

#: Stable ID of the measured producer.
MEASURED_INGEST_PRODUCER_ID = "measured-ingest"


class UnknownObservationProducerError(KeyError):
    """Raised when a requested observation producer is not registered."""


@dataclass(frozen=True)
class ObservationProducerDescriptor:
    """Identity and provenance metadata for a registered producer.

    Attributes:
        producer_id: Stable ID the producer resolves by. Explicit and
            declared at registration -- never discovered from an entry point.
        provenance: The :data:`ObservationProvenance` every observation this
            producer emits carries, so a caller can pick a producer by where
            its values come from before resolving it.
        summary: One human-readable sentence naming the producer's source.
    """

    producer_id: str
    provenance: ObservationProvenance
    summary: str
    contract_version: str = "1"


@dataclass(frozen=True)
class ObservationProducerRegistration:
    """Callable and descriptor for a registered observation producer."""

    descriptor: ObservationProducerDescriptor
    producer: ObservationProducer


class ObservationProducerRegistry:
    """Look up observation producers by stable, explicit ID.

    Producers are functions, not instantiable adapters, so
    :meth:`resolve` replaces the adapter registry's ``create``: it returns
    the registered callable itself rather than calling a factory.
    """

    def __init__(self) -> None:
        """Start with no registrations; nothing is discovered ambiently."""
        self._registrations: dict[str, ObservationProducerRegistration] = {}

    def register(
        self,
        producer: ObservationProducer,
        *,
        descriptor: ObservationProducerDescriptor,
        replace: bool = False,
    ) -> None:
        """Register an observation producer under its descriptor's ID.

        Args:
            producer: The producer callable, handed back verbatim by
                :meth:`resolve`.
            descriptor: Identity and provenance metadata. Keyword-only and
                required: producers are plain functions, so there is nothing
                to derive a descriptor from.
            replace: Allow overwriting an existing registration. Defaults to
                ``False`` so a duplicate ID fails loudly.

        Raises:
            ValueError: If the ID is already registered and ``replace`` is
                ``False``.
        """
        producer_id = descriptor.producer_id
        if descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"observation producer {producer_id!r} declares contract "
                f"version {descriptor.contract_version!r}, but this engine "
                f"supports only: {supported}; upgrade or pin the extension to "
                "a supported contract version"
            )
        if producer_id in self._registrations and not replace:
            raise ValueError(
                f"Observation producer already registered: {producer_id}. "
                "Pass replace=True to overwrite it deliberately."
            )
        self._registrations[producer_id] = ObservationProducerRegistration(
            descriptor=descriptor,
            producer=producer,
        )

    def get_descriptor(self, producer_id: str) -> ObservationProducerDescriptor:
        """Return descriptor metadata for a registered producer.

        Args:
            producer_id: Stable ID of the producer.

        Returns:
            The descriptor supplied at registration.

        Raises:
            UnknownObservationProducerError: If no producer carries the ID;
                the message lists the available IDs.
        """
        return self._registration(producer_id).descriptor

    def list_descriptors(self) -> list[ObservationProducerDescriptor]:
        """Return registered producer descriptors sorted by producer ID.

        Returns:
            The descriptors, in ascending ``producer_id`` order.
        """
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def resolve(self, producer_id: str) -> ObservationProducer:
        """Return the registered producer callable itself.

        This is the deliberate divergence from
        ``NetworkAdapterRegistry.create``: producers are functions rather
        than instantiable adapters, so there is no factory to call -- the
        registry hands back the real producer, never a wrapper.

        Args:
            producer_id: Stable ID of the producer.

        Returns:
            The callable registered under ``producer_id``, identical to the
            object passed to :meth:`register`.

        Raises:
            UnknownObservationProducerError: If no producer carries the ID;
                the message lists the available IDs.
        """
        return self._registration(producer_id).producer

    def _registration(self, producer_id: str) -> ObservationProducerRegistration:
        """Return the registration for an ID, or raise a located error.

        Args:
            producer_id: Stable ID of the producer.

        Returns:
            The registration.

        Raises:
            UnknownObservationProducerError: Naming the unknown ID and every
                available one.
        """
        try:
            return self._registrations[producer_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none"
            raise UnknownObservationProducerError(
                f"Unknown observation producer: {producer_id}. "
                f"Available producers: {available}"
            ) from exc


_DEFAULT_OBSERVATION_PRODUCER_REGISTRY: ObservationProducerRegistry | None = None


def default_observation_producer_registry() -> ObservationProducerRegistry:
    """Return the shared default registry holding the two shipped producers.

    Built once and cached so external producers registered via
    :func:`register_observation_producer_extension` stay resolvable through
    the default path. Resolves ``"powerflow"`` to
    :func:`gridalyn.twin.observation.contract.observe_network` and
    ``"measured-ingest"`` to
    :func:`gridalyn.twin.observation.ingest.read_measured_observations`.
    """
    global _DEFAULT_OBSERVATION_PRODUCER_REGISTRY
    if _DEFAULT_OBSERVATION_PRODUCER_REGISTRY is None:
        registry = ObservationProducerRegistry()
        registry.register(
            observe_network,
            descriptor=ObservationProducerDescriptor(
                producer_id=POWERFLOW_PRODUCER_ID,
                provenance="simulated",
                summary=(
                    "Reads observed state off a solved network's result tables "
                    "(res_bus / res_line); one observation per solved operating "
                    "point."
                ),
            ),
        )
        registry.register(
            read_measured_observations,
            descriptor=ObservationProducerDescriptor(
                producer_id=MEASURED_INGEST_PRODUCER_ID,
                provenance="measured",
                summary=(
                    "Reads tidy (timestamp, entity_id, quantity, value) "
                    "measurement rows against a declared entity-to-bus join; one "
                    "observation per instant, as_of stamped from the datum."
                ),
            ),
        )
        _DEFAULT_OBSERVATION_PRODUCER_REGISTRY = registry
    return _DEFAULT_OBSERVATION_PRODUCER_REGISTRY


def register_observation_producer_extension(
    producer: ObservationProducer,
    *,
    descriptor: ObservationProducerDescriptor,
    replace: bool = False,
    registry: ObservationProducerRegistry | None = None,
) -> None:
    """Register an external observation producer (host API).

    A third-party producer conforms to the observation contract, carries an
    :class:`ObservationProducerDescriptor` with a supported
    ``contract_version``, and registers it here — no edit to gridalyn's
    codebase required. Defaults to the shared default registry.
    """
    (registry or default_observation_producer_registry()).register(
        producer, descriptor=descriptor, replace=replace
    )


__all__ = [
    "MEASURED_INGEST_PRODUCER_ID",
    "POWERFLOW_PRODUCER_ID",
    "ObservationProducer",
    "ObservationProducerDescriptor",
    "ObservationProducerRegistration",
    "ObservationProducerRegistry",
    "UnknownObservationProducerError",
    "default_observation_producer_registry",
    "register_observation_producer_extension",
]

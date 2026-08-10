"""Contract for pluggable voltage-control policies.

Before this module, ``VoltageControlEnvironment`` fused the network build, the
solver, the observation extraction and the control decision into 138 lines,
and the repository's control logic was four unconnected paradigms (RL,
sensitivity dispatch, market clearing, replay/forecast) with no shared
interface between any pair of them.

A :class:`Policy` is the seam that lets a controller be swapped without
touching the environment: it consumes a :class:`~gridalyn.simulation.
observation.contract.NetworkObservation` (10-03) plus the battery state of
charge and the step index, and returns a battery action in MW. It does not
see a solved ``pandapowerNet`` and does not decide *how* power flow was
solved -- that is the backend's job (10-01) -- so a policy is reusable across
whichever backend the environment was constructed with.

Resolution is by explicit ID only -- see :mod:`gridalyn.simulation.policies.
registry`. There is deliberately no ``entry_points`` discovery, for the same
reason :mod:`gridalyn.simulation.backends.registry` refuses it: an ambient
plugin would change a controller's decisions without appearing in the run
manifest.

**Deliberate non-goal.** This contract does not include a Gymnasium
``reset``/``step``/``space`` wrapper. It does not foreclose one either --
consuming an observation and returning a scalar action is exactly what such a
wrapper would call internally -- but building the wrapper itself is out of
scope for this phase and was not requested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

from gridalyn.simulation.observation.contract import NetworkObservation

#: The tabular Q-learning policy trained per-repository in
#: ``simulation.control.tabular_voltage`` (paradigm 1).
TABULAR_RL_POLICY_ID = "tabular_rl"

#: The local finite-difference voltage-sensitivity policy adapted from
#: ``operations.der_voltage``'s multi-DER dispatch technique to a single
#: controlled bus and a single battery (paradigm 2).
SENSITIVITY_DISPATCH_POLICY_ID = "sensitivity_dispatch"


@dataclass(frozen=True)
class PolicyDescriptor:
    """Identity of a registered voltage-control policy.

    Attributes:
        policy_id: Stable ID a caller resolves the policy by.
        name: Human-readable description for reports and manifests.
        paradigm: Which of the repository's control paradigms this policy
            implements -- e.g. ``"reinforcement_learning"`` or
            ``"sensitivity_dispatch"`` -- so a manifest can record which
            control approach a run actually used.
    """

    policy_id: str
    name: str
    paradigm: str

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the descriptor for provenance.

        Returns:
            A ``dict`` with only str values, embeddable in a run manifest
            without a custom encoder.
        """
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "paradigm": self.paradigm,
        }


@runtime_checkable
class Policy(Protocol):
    """A single way to decide a voltage-control battery action.

    Implementations must expose ``descriptor`` (what will be recorded) and
    ``decide`` (the only place a control decision is made). A policy is
    constructed already knowing which bus it controls -- it is not handed a
    ``bus_id`` on every call -- so the same ``decide`` signature works for a
    trained Q-table lookup and for a physics-derived sensitivity law alike.
    """

    @property
    def descriptor(self) -> PolicyDescriptor:
        """Return what will be recorded in a run's control provenance.

        Declared read-only: implementations expose it as a ``property`` so a
        consumer cannot rebind the record of which policy decided an action --
        the same discipline :class:`gridalyn.simulation.backends.contract.
        PowerFlowBackend.descriptor` uses.
        """

    def decide(
        self,
        observation: NetworkObservation,
        *,
        soc_mwh: float,
        step: int,
    ) -> float:
        """Return the battery action in MW for this step.

        Args:
            observation: The controller's view of the solved network for
                this step, built through the 10-03 observation contract.
            soc_mwh: Current battery state of charge in MWh.
            step: Zero-based step index within the episode.

        Returns:
            A requested battery action in MW (positive discharges, negative
            charges). The environment still applies its own state-of-charge
            feasibility clamp -- a policy's job is to *decide*, not to
            enforce physical limits it does not own.
        """


def voltage_at_bus(observation: NetworkObservation, bus_id: int) -> float:
    """Return the observed voltage magnitude at one specific bus.

    Shared by every :class:`Policy` implementation that decides from a single
    controlled bus, so the bus lookup has one implementation instead of being
    re-derived per policy.

    Args:
        observation: A solved-network observation from :func:`gridalyn.
            simulation.observation.contract.observe_network`.
        bus_id: The bus identifier to look up; matched against
            ``observation.bus_ids``, not against array position.

    Returns:
        The per-unit voltage magnitude at ``bus_id``.

    Raises:
        ValueError: If ``bus_id`` is not present in the observation. Names
            the requested ID and the observed set, since a silent ``nan``
            here would read as a converged-but-wrong voltage.
    """
    matches = np.where(observation.bus_ids == bus_id)[0]
    if matches.size == 0:
        raise ValueError(
            f"bus_id {bus_id} not present in observation "
            f"(observed bus_ids: {sorted(int(b) for b in observation.bus_ids)})"
        )
    return float(observation.bus_voltage_pu[int(matches[0])])


def describe_policy(factory: Any) -> PolicyDescriptor:
    """Return the descriptor a policy factory declares.

    Args:
        factory: A policy class or callable carrying a ``DESCRIPTOR``
            attribute of type :class:`PolicyDescriptor`.

    Returns:
        The declared descriptor.

    Raises:
        TypeError: If ``factory`` declares no usable ``DESCRIPTOR``. The
            message names the factory and what to add, because a factory
            without a descriptor cannot be recorded in provenance.
    """
    descriptor = getattr(factory, "DESCRIPTOR", None)
    if not isinstance(descriptor, PolicyDescriptor):
        name = getattr(factory, "__name__", type(factory).__name__)
        found = type(descriptor).__name__ if descriptor is not None else "nothing"
        raise TypeError(
            f"policy factory {name} declares no descriptor "
            f"(found {found}); add a class attribute "
            "DESCRIPTOR: PolicyDescriptor, or pass descriptor=... "
            "to PolicyRegistry.register"
        )
    return descriptor


__all__ = [
    "SENSITIVITY_DISPATCH_POLICY_ID",
    "TABULAR_RL_POLICY_ID",
    "Policy",
    "PolicyDescriptor",
    "describe_policy",
    "voltage_at_bus",
]

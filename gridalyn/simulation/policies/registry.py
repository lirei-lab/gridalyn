"""Registry for voltage-control policies, resolved by explicit ID only.

Modelled on :mod:`gridalyn.simulation.backends.registry`: a frozen
registration pairing a descriptor with a factory, ``register(...,
replace=False)``, ``get_descriptor``, ``list_descriptors()`` sorted by ID,
``create(id, **kwargs)`` and a located error enumerating the available IDs.

**There is no discovery.** No ``entry_points``, no plugin scan, no
environment-variable override. A policy that is not explicitly registered is
not resolvable, because an ambient plugin would change a controller's
decisions without appearing in a run manifest -- the same failure mode
``gridalyn.simulation.backends.registry`` refuses for power-flow solvers.

Unlike a power-flow backend, a policy factory here typically needs runtime
state (a trained Q-table, a measured sensitivity coefficient, the controlled
bus ID) that does not exist until a caller has trained or measured it.
Registering a factory constructs nothing; ``create(policy_id, **kwargs)`` is
where that state is bound in, exactly as ``PowerFlowBackendRegistry.create``
forwards settings to a backend factory.

**Why ``SensitivityDispatchPolicy`` lives here, not in ``operations.
der_voltage``.** Paradigm 2's natural home is ``gridalyn.operations.
der_voltage``, which is where its multi-DER finite-difference technique
(``_voltage_sensitivity``) already lives, and where this plan's own
``files_modified`` places the adapted single-bus *measurement* helper
(:func:`gridalyn.operations.der_voltage.measure_local_voltage_sensitivity`).
But layer direction is strict-downward (``operations`` may import
``simulation``, never the reverse), and this module's
:func:`default_policy_registry` must register *both* policies from one place
that ``simulation.policies`` itself can reach -- importing the operations
module here would be the exact upward edge ``tests/test_layer_direction.py``
exists to catch. The decision splits the paradigm cleanly: *measuring* the
sensitivity needs a feeder and a solve, so it stays in ``operations``, where
that context already lives; *deciding* from an already-measured coefficient
needs nothing but the coefficient itself, so the ``Policy``-conforming class
lives here, where the registry can reach it without crossing upward. A
caller assembles the two: measure in ``operations``, decide via the policy
registered here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.foundation.platform.extensions import (
    SUPPORTED_CONTRACT_VERSIONS,
    UnsupportedContractVersionError,
)
from gridalyn.simulation.policies.contract import (
    SENSITIVITY_DISPATCH_POLICY_ID,
    Policy,
    PolicyDescriptor,
    describe_policy,
    voltage_at_bus,
)


class UnknownPolicyError(KeyError):
    """Raised when a requested policy is not registered."""


@dataclass(frozen=True)
class PolicyRegistration:
    """Factory and descriptor for a registered policy."""

    descriptor: PolicyDescriptor
    factory: Callable[..., Policy]


class PolicyRegistry:
    """Resolve voltage-control policies by stable, explicitly registered ID."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registrations: dict[str, PolicyRegistration] = {}

    def register(
        self,
        factory: Callable[..., Policy],
        *,
        descriptor: PolicyDescriptor | None = None,
        replace: bool = False,
    ) -> None:
        """Register a policy factory under its descriptor's ID.

        Args:
            factory: Callable returning a :class:`Policy`.
            descriptor: Descriptor to register under. Defaults to the one the
                factory declares.
            replace: Allow overwriting an already-registered ID.

        Raises:
            ValueError: If the ID is taken and ``replace`` is false. The
                message names the ID and the flag that would permit it.
        """
        policy_descriptor = descriptor or describe_policy(factory)
        policy_id = policy_descriptor.policy_id
        if policy_descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"policy {policy_id!r} declares contract version "
                f"{policy_descriptor.contract_version!r}, but this engine "
                f"supports only: {supported}; upgrade or pin the extension to "
                "a supported contract version"
            )
        if policy_id in self._registrations and not replace:
            raise ValueError(
                f"policy already registered: {policy_id} "
                "(pass replace=True to override it deliberately)"
            )
        self._registrations[policy_id] = PolicyRegistration(
            descriptor=policy_descriptor,
            factory=factory,
        )

    def get_descriptor(self, policy_id: str) -> PolicyDescriptor:
        """Return descriptor metadata for a registered policy.

        Args:
            policy_id: The registered ID.

        Returns:
            The registered descriptor.
        """
        return self._registration(policy_id).descriptor

    def list_descriptors(self) -> list[PolicyDescriptor]:
        """Return registered policy descriptors sorted by policy ID.

        Returns:
            One descriptor per registration, ordered by ID so callers and
            manifests see a stable sequence.
        """
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def create(self, policy_id: str, **kwargs: Any) -> Policy:
        """Instantiate a registered policy.

        Args:
            policy_id: The registered ID; no discovery, no fallback.
            **kwargs: State forwarded to the policy factory -- e.g. a trained
                Q-table for the tabular-RL policy, or a measured sensitivity
                coefficient for the sensitivity-dispatch policy.

        Returns:
            A ready-to-use policy.

        Raises:
            UnknownPolicyError: If ``policy_id`` is not registered.
        """
        return self._registration(policy_id).factory(**kwargs)

    def _registration(self, policy_id: str) -> PolicyRegistration:
        try:
            return self._registrations[policy_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none registered"
            raise UnknownPolicyError(
                f"unknown policy: {policy_id!r} "
                f"(available policies: {available}); policies resolve by "
                "explicit ID only -- register one with "
                "PolicyRegistry.register before resolving it"
            ) from exc


class SensitivityDispatchPolicy:
    """Decide a battery action from an already-measured local sensitivity.

    Paradigm 2 (sensitivity dispatch), adapted from ``operations.der_voltage``'s
    multi-DER finite-difference technique to a single controlled bus and a
    single battery. This class does not measure the sensitivity itself --
    see :func:`gridalyn.operations.der_voltage.
    measure_local_voltage_sensitivity`, which reuses the same
    finite-difference technique ``_voltage_sensitivity`` applies to the
    multi-DER case -- it only inverts an already-measured coefficient into a
    proposed action, so it needs nothing from the ``operations`` layer.
    """

    DESCRIPTOR = PolicyDescriptor(
        policy_id=SENSITIVITY_DISPATCH_POLICY_ID,
        name="Local voltage-sensitivity dispatch (finite-difference, single bus)",
        paradigm="sensitivity_dispatch",
    )

    def __init__(
        self,
        *,
        sensitivity_pu_per_mw: float,
        action_space_mw: tuple[float, ...],
        controlled_bus_id: int,
        voltage_target_pu: float,
    ) -> None:
        """Build the policy from an already-measured sensitivity coefficient.

        Args:
            sensitivity_pu_per_mw: Measured local ``dV/dP`` at the controlled
                bus for the battery, in per-unit voltage per MW injected.
            action_space_mw: The environment's discrete action choices;
                only their min/max bound the proposed continuous action.
            controlled_bus_id: The bus this policy reads voltage from.
            voltage_target_pu: The voltage this policy steers toward.

        Raises:
            ValueError: If ``sensitivity_pu_per_mw`` is zero, since the
                policy cannot invert a coefficient that carries no
                information about how injection moves voltage.
        """
        if sensitivity_pu_per_mw == 0.0:
            raise ValueError(
                "sensitivity_pu_per_mw must be non-zero -- a zero-sensitivity "
                "bus carries no information about how injection moves voltage"
            )
        self._sensitivity = float(sensitivity_pu_per_mw)
        bounds = [float(a) for a in action_space_mw]
        self._low = min(bounds)
        self._high = max(bounds)
        self._controlled_bus_id = int(controlled_bus_id)
        self._voltage_target_pu = float(voltage_target_pu)

    @property
    def descriptor(self) -> PolicyDescriptor:
        """Return this policy's descriptor.

        Returns:
            The class-level :data:`DESCRIPTOR`.
        """
        return self.DESCRIPTOR

    def decide(self, observation: Any, *, soc_mwh: float, step: int) -> float:
        """Propose the continuous battery action that steers toward target.

        Args:
            observation: The controller's view of the solved network.
            soc_mwh: Unused -- state-of-charge feasibility is the
                environment's clamp, not this policy's decision.
            step: Unused -- this policy has no time-dependent state.

        Returns:
            ``(voltage_target_pu - observed_vm) / sensitivity``, clipped to
            the action space's ``[min, max]`` bound. Unlike the tabular-RL
            policy this is a continuous value, not a discrete action-space
            entry -- the environment's own clamp still applies on top.
        """
        del soc_mwh, step
        vm = voltage_at_bus(observation, self._controlled_bus_id)
        desired_mw = (self._voltage_target_pu - vm) / self._sensitivity
        return float(min(max(desired_mw, self._low), self._high))


_DEFAULT_POLICY_REGISTRY: PolicyRegistry | None = None


def default_policy_registry() -> PolicyRegistry:
    """Return the shared default registry of voltage-control policies.

    Built once and cached so external policies registered via
    :func:`register_policy_extension` stay resolvable through the default
    path. Holds exactly the policies this repository ships, in registration
    order: the tabular-RL policy (paradigm 1) and the sensitivity-dispatch
    policy (paradigm 2). Registration constructs nothing and needs neither a
    trained Q-table nor a measured sensitivity coefficient -- those are bound
    in at :meth:`PolicyRegistry.create` time. Building this registry imports
    ``simulation.control.tabular_voltage`` (same layer) but nothing from
    ``operations`` -- see the module docstring for why.
    """
    global _DEFAULT_POLICY_REGISTRY
    if _DEFAULT_POLICY_REGISTRY is None:
        from gridalyn.simulation.control.tabular_voltage import TabularRLPolicy

        registry = PolicyRegistry()
        registry.register(TabularRLPolicy)
        registry.register(SensitivityDispatchPolicy)
        _DEFAULT_POLICY_REGISTRY = registry
    return _DEFAULT_POLICY_REGISTRY


def register_policy_extension(
    factory: Callable[..., Policy],
    *,
    descriptor: PolicyDescriptor,
    replace: bool = False,
    registry: PolicyRegistry | None = None,
) -> None:
    """Register an external voltage-control policy (host API).

    A third-party policy conforms to the :class:`Policy` contract, carries a
    :class:`PolicyDescriptor` with a supported ``contract_version``, and
    registers it here — no edit to gridalyn's codebase required. Defaults to
    the shared default registry.
    """
    (registry or default_policy_registry()).register(
        factory, descriptor=descriptor, replace=replace
    )


__all__ = [
    "PolicyRegistration",
    "PolicyRegistry",
    "SensitivityDispatchPolicy",
    "UnknownPolicyError",
    "default_policy_registry",
    "register_policy_extension",
]

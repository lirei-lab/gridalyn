"""Contract for pluggable power-flow backends.

Before this module the repository solved power flow at eleven call sites across
four layers, and those sites disagreed: three passed ``algorithm="nr",
init="auto"``, two requested ``lightsim2grid=True``, one was a bare
``pp.runpp(net)``, and the rest passed caller-supplied keywords straight
through. None of that reached the run manifest, so two runs that solved with
different engines were indistinguishable in every governed artifact.

A backend is the *single* place a solve happens. It carries a descriptor whose
``as_dict`` is written verbatim into ``provenance.powerflow_backend``, so the
engine and the settings it applied are recoverable from the manifest alone.

Resolution is by explicit ID only -- see :mod:`gridalyn.simulation.backends.
registry`. There is deliberately no ``entry_points`` discovery: an ambient
plugin would change solved results without appearing in provenance, the exact
failure mode that forced ``provenance.macro_model`` into existence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

#: Backend that calls ``pandapower.runpp`` directly. The default.
PANDAPOWER_NATIVE_BACKEND_ID = "pandapower_native"

#: Backend that routes ``pandapower.runpp`` through the lightsim2grid solver.
LIGHTSIM2GRID_BACKEND_ID = "lightsim2grid"

#: The backend used when a caller names none. Chosen because it needs no
#: optional extra, so it resolves on every supported install.
DEFAULT_POWERFLOW_BACKEND_ID = PANDAPOWER_NATIVE_BACKEND_ID


@dataclass(frozen=True)
class PowerFlowBackendDescriptor:
    """Identity, capability requirement and settings of a power-flow backend.

    Attributes:
        backend_id: Stable ID a caller resolves the backend by.
        name: Human-readable engine description for reports and manifests.
        capability: Optional-capability name this backend needs (a key of
            ``OPTIONAL_CAPABILITY_MODULES``), or ``None`` when it needs none.
        settings: Solver keywords the backend applies before any caller
            override. Recorded in provenance, so a manifest states what was
            actually asked of the solver.
    """

    backend_id: str
    name: str
    capability: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the descriptor for provenance.

        Returns:
            A ``dict`` with only str/None/JSON-native values, so it can be
            embedded in the run manifest without a custom encoder.
        """
        return {
            "backend_id": self.backend_id,
            "name": self.name,
            "capability": self.capability,
            "settings": dict(self.settings),
        }


@runtime_checkable
class PowerFlowBackend(Protocol):
    """A single, provenance-bearing way to solve a pandapower network.

    Implementations must expose ``descriptor`` (what will be recorded) and
    ``solve`` (the only place a solver call is made).
    """

    @property
    def descriptor(self) -> PowerFlowBackendDescriptor:
        """Return what will be recorded in ``provenance.powerflow_backend``.

        Declared read-only: implementations expose it as a ``property`` so a
        consumer cannot rebind the record of what a run solved with.
        """

    def solve(self, net: Any, **kwargs: Any) -> None:
        """Solve ``net`` in place, applying descriptor settings then ``kwargs``.

        Args:
            net: A pandapower network, mutated in place with ``res_*`` tables.
            **kwargs: Per-call solver keywords that override the backend's own
                settings, so a caller-parametrised site keeps its behaviour.
        """


def freeze_settings(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a read-only view of ``settings`` for a frozen descriptor.

    Args:
        settings: Solver keywords to protect from mutation by a consumer that
            reads ``descriptor.settings``.

    Returns:
        A ``MappingProxyType`` over a private copy.
    """
    return MappingProxyType(dict(settings))


def describe_powerflow_backend(factory: Any) -> PowerFlowBackendDescriptor:
    """Return the descriptor a backend factory declares.

    Args:
        factory: A backend class or callable carrying a ``DESCRIPTOR``
            attribute of type :class:`PowerFlowBackendDescriptor`.

    Returns:
        The declared descriptor.

    Raises:
        TypeError: If ``factory`` declares no usable ``DESCRIPTOR``. The
            message names the factory and what to add, because a factory
            without a descriptor cannot be recorded in provenance.
    """
    descriptor = getattr(factory, "DESCRIPTOR", None)
    if not isinstance(descriptor, PowerFlowBackendDescriptor):
        name = getattr(factory, "__name__", type(factory).__name__)
        found = type(descriptor).__name__ if descriptor is not None else "nothing"
        raise TypeError(
            f"power-flow backend factory {name} declares no descriptor "
            f"(found {found}); add a class attribute "
            "DESCRIPTOR: PowerFlowBackendDescriptor, or pass descriptor=... "
            "to PowerFlowBackendRegistry.register"
        )
    return descriptor


__all__ = [
    "DEFAULT_POWERFLOW_BACKEND_ID",
    "LIGHTSIM2GRID_BACKEND_ID",
    "PANDAPOWER_NATIVE_BACKEND_ID",
    "PowerFlowBackend",
    "PowerFlowBackendDescriptor",
    "describe_powerflow_backend",
    "freeze_settings",
]

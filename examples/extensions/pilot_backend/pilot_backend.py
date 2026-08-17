"""External power-flow backend pilot (Phase 18, 18-01).

A conformant power-flow backend extension that lives OUTSIDE the ``gridalyn``
codebase and registers through the declared host mechanism
:func:`gridalyn.simulation.backends.registry.register_powerflow_backend_extension`
— no edit to gridalyn required. It is a thin wrapper that delegates solving to
gridalyn's shipped pandapower-native backend, so the extension is real (a
working backend), not a stub: the point is that a third party can ship its own
backend and have it recorded in ``provenance.powerflow_backend`` as an
extension (``extension_id``/``extension_source="host"``).

The module follows the same convention the engine expects of any extension:
``descriptor`` (what provenance records) + ``factory`` (a callable returning
the role's component). ``register()`` is the embedding convenience — call it
from your entry script before running a study.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gridalyn.simulation.backends.contract import (
    PowerFlowBackendDescriptor,
    freeze_settings,
)
from gridalyn.simulation.backends.registry import register_powerflow_backend_extension

#: Distinct from the shipped backends (``pandapower_native``, ``lightsim2grid``).
PILOT_BACKEND_ID = "pilot_native_backend"


class PilotNativeBackend:
    """An external power-flow backend that delegates to pandapower native.

    Attributes:
        DESCRIPTOR: The class-level identity recorded in provenance; the
            instance descriptor carries the effective settings, mirroring the
            shipped ``PandapowerNativeBackend`` pattern.
    """

    DESCRIPTOR = PowerFlowBackendDescriptor(
        backend_id=PILOT_BACKEND_ID,
        name="pilot external backend (delegates to pandapower native)",
        capability=None,
        settings=freeze_settings({"algorithm": "nr", "init": "auto"}),
    )

    def __init__(self, **settings: Any) -> None:
        """Build the backend, overriding its declared default settings.

        Args:
            **settings: Solver keywords that replace the declared defaults for
                every solve this instance performs.
        """
        self._settings: dict[str, Any] = {
            **dict(self.DESCRIPTOR.settings),
            **settings,
        }

    @property
    def descriptor(self) -> PowerFlowBackendDescriptor:
        """Return this instance's descriptor, carrying its effective settings.

        Returns:
            The class descriptor with ``settings`` replaced by the settings
            this instance actually applies.
        """
        return replace(self.DESCRIPTOR, settings=freeze_settings(self._settings))

    def solve(self, net: Any, **kwargs: Any) -> None:
        """Solve ``net`` in place by delegating to the pandapower-native backend.

        Args:
            net: A pandapower network, mutated in place with ``res_*`` tables.
            **kwargs: Per-call solver keywords.
        """
        from gridalyn.simulation.backends.pandapower_native import (
            PandapowerNativeBackend,
        )

        PandapowerNativeBackend(**self._settings).solve(net, **kwargs)


def factory(**kwargs: Any) -> PilotNativeBackend:
    """Return a ready-to-solve instance of this external backend.

    Args:
        **kwargs: Settings forwarded to the backend constructor.

    Returns:
        A :class:`PilotNativeBackend` instance.
    """
    return PilotNativeBackend(**kwargs)


def register(
    registry: Any = None,
    *,
    version: str = "0.1.0",
    replace: bool = False,
) -> None:
    """Register this external backend through the declared host mechanism.

    Args:
        registry: Target backend registry; defaults to the shared default.
        version: Semantic version recorded in provenance.
        replace: Allow overwriting an already-registered ID.
    """
    register_powerflow_backend_extension(
        factory,
        descriptor=PilotNativeBackend.DESCRIPTOR,
        registry=registry,
        version=version,
        replace=replace,
    )


descriptor = PilotNativeBackend.DESCRIPTOR

__all__ = [
    "PILOT_BACKEND_ID",
    "PilotNativeBackend",
    "descriptor",
    "factory",
    "register",
]

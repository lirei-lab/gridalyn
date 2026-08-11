"""The lightsim2grid power-flow backend.

``lightsim2grid`` is a truly-optional dependency (the ``sim`` extra), so this
module imports neither it nor ``pandapower`` at module scope. The preflight
runs in ``__init__`` and raises ``MissingCapabilityError`` -- never a bare
``ImportError`` -- mirroring
:class:`gridalyn.simulation.simulators.lightsim.LightSimPowerflowAdapter`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.simulation.backends.contract import (
    LIGHTSIM2GRID_BACKEND_ID,
    PowerFlowBackendDescriptor,
    freeze_settings,
)

_CONTEXT = (
    "the 'lightsim2grid' power-flow backend "
    "(gridalyn.simulation.backends, resolved by explicit backend_id)"
)


class LightSim2GridBackend:
    """Solve a pandapower network through the lightsim2grid C++ KLU solver."""

    DESCRIPTOR = PowerFlowBackendDescriptor(
        backend_id=LIGHTSIM2GRID_BACKEND_ID,
        name="pandapower runpp via lightsim2grid (C++/Eigen KLU)",
        capability="sim",
        settings=freeze_settings({"lightsim2grid": True}),
    )

    def __init__(self, **settings: Any) -> None:
        """Build the backend after checking the ``sim`` capability.

        Args:
            **settings: Solver keywords that replace the declared defaults for
                every solve this instance performs.

        Raises:
            MissingCapabilityError: If the ``sim`` extra is not installed. The
                message names this backend and the ``pip install`` that fixes
                it, so the failure is actionable at resolution time rather
                than at solve time.
        """
        require_capabilities("sim", context=_CONTEXT)
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
        """Solve ``net`` in place through lightsim2grid.

        Args:
            net: A pandapower network, mutated in place with ``res_*`` tables.
            **kwargs: Per-call solver keywords; they override the backend
                settings. ``pandapower.runpp`` forwards ``lightsim2grid=True``
                to the lightsim2grid solver hook.
        """
        import pandapower as pp

        pp.runpp(net, **{**self._settings, **kwargs})


__all__ = ["LightSim2GridBackend"]

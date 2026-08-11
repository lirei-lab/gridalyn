"""The default power-flow backend: ``pandapower.runpp`` called directly.

``pandapower`` is imported inside :meth:`PandapowerNativeBackend.solve`, never
at module scope. A module-scope ``import pandapower`` puts ``lightsim2grid``
into ``sys.modules`` on its own (measured, Phase 1), which would make this
package leak a truly-optional dependency at import.

Default settings are ``algorithm="nr", init="auto"``. These are pandapower's
own defaults, so stating them explicitly changes no solved value -- it makes
the previously-implicit configuration visible in the run manifest and ends the
disagreement between the call sites that stated them and the ones that did not.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gridalyn.simulation.backends.contract import (
    PANDAPOWER_NATIVE_BACKEND_ID,
    PowerFlowBackendDescriptor,
    freeze_settings,
)


class PandapowerNativeBackend:
    """Solve a pandapower network with pandapower's own Newton-Raphson solver."""

    DESCRIPTOR = PowerFlowBackendDescriptor(
        backend_id=PANDAPOWER_NATIVE_BACKEND_ID,
        name="pandapower Newton-Raphson (native runpp)",
        capability=None,
        settings=freeze_settings({"algorithm": "nr", "init": "auto"}),
    )

    def __init__(self, **settings: Any) -> None:
        """Build the backend, overriding its declared default settings.

        Args:
            **settings: Solver keywords that replace the declared defaults for
                every solve this instance performs. Recorded in the instance
                descriptor, so provenance reflects the instance rather than the
                class.
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
        """Solve ``net`` in place.

        Args:
            net: A pandapower network, mutated in place with ``res_*`` tables.
            **kwargs: Per-call solver keywords; they override the backend
                settings, preserving each caller-parametrised call site.
        """
        import pandapower as pp

        pp.runpp(net, **{**self._settings, **kwargs})


__all__ = ["PandapowerNativeBackend"]

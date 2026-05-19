"""Small LightSim2Grid adapter for Gridalyn control environments."""

from __future__ import annotations

import warnings

import numpy as np
import pandapower as pp


class LightSimPowerflowAdapter:
    """Wrap LightSim2Grid's grid model behind a narrow Gridalyn API."""

    def __init__(self, net: pp.pandapowerNet) -> None:
        try:
            from lightsim2grid.gridmodel import init_from_pandapower
        except ImportError as exc:
            raise ImportError(
                "LightSimPowerflowAdapter requires lightsim2grid. "
                "Install gridalyn with the simulation dependencies."
            ) from exc
        self.net = net
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message='LightSim has not found any generators tagged as "slack bus".*',
                category=UserWarning,
            )
            self.grid = init_from_pandapower(net)
        self._last_voltage = np.ones(len(net.bus), dtype=complex)

    def reset(self) -> None:
        self._last_voltage = np.ones(len(self.net.bus), dtype=complex)

    def change_load(self, load_idx: int, p_mw: float, q_mvar: float = 0.0) -> None:
        self.grid.change_p_load(int(load_idx), float(p_mw))
        self.grid.change_q_load(int(load_idx), float(q_mvar))

    def change_sgen(self, sgen_idx: int, p_mw: float, q_mvar: float = 0.0) -> None:
        self.grid.change_p_sgen(int(sgen_idx), float(p_mw))
        self.grid.change_q_sgen(int(sgen_idx), float(q_mvar))

    def solve_voltage_magnitudes(
        self,
        *,
        max_iteration: int = 10,
        tolerance: float = 1e-8,
    ) -> np.ndarray:
        self._last_voltage = self.grid.ac_pf(
            self._last_voltage,
            int(max_iteration),
            float(tolerance),
        )
        return np.asarray(self.grid.get_Vm(), dtype=float)

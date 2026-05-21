"""Voltage-control environment backed by Gridalyn assets and LightSim2Grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gridalyn.assets.modeling.feeders import RadialFeederSpec
from gridalyn.assets.modeling.voltage_control import VoltageControlDERSpec
from gridalyn.simulation.simulators.lightsim import LightSimPowerflowAdapter
from gridalyn.simulation.simulators.powerflow.voltage_control import (
    build_voltage_control_feeder,
)


@dataclass(frozen=True)
class VoltageControlEnvironmentSpec:
    """Configuration contract for a voltage-control simulation environment."""

    feeder: RadialFeederSpec
    der: VoltageControlDERSpec
    load_multiplier_profile: np.ndarray
    pv_profile: np.ndarray
    timestep_hours: float
    voltage_target_pu: float
    voltage_low_pu: float
    voltage_high_pu: float
    voltage_violation_weight: float = 120.0
    voltage_deviation_weight: float = 8.0
    action_weight: float = 0.25


class VoltageControlEnvironment:
    """Deterministic voltage-control environment for RL and policy evaluation."""

    def __init__(self, spec: VoltageControlEnvironmentSpec) -> None:
        _validate_environment_spec(spec)
        self.spec = spec
        self.net = build_voltage_control_feeder(spec.feeder, spec.der)
        self.adapter = LightSimPowerflowAdapter(self.net)
        self.load_bus_ids = sorted(spec.feeder.loads_mw)
        self.base_load_p = np.array(
            [spec.feeder.loads_mw[bus_id] for bus_id in self.load_bus_ids],
            dtype=float,
        )
        self.base_load_q = self.base_load_p * float(spec.feeder.q_to_p_ratio)
        self.battery_load_idx = len(self.base_load_p)
        self.pv_sgen_idx = 0
        self.battery_sgen_idx = 1
        self.soc_mwh = float(spec.der.battery.initial_soc_mwh)

    def reset(self) -> None:
        self.soc_mwh = float(self.spec.der.battery.initial_soc_mwh)
        self.adapter.reset()

    def step(self, step: int, action_mw: float) -> dict:
        pv_mw, applied_action_mw = self._set_step(step, action_mw)
        vm = self.adapter.solve_voltage_magnitudes()
        controlled_vm = float(vm[int(self.spec.der.controlled_bus_id)])
        voltage_violation = max(controlled_vm - self.spec.voltage_high_pu, 0.0) + max(
            self.spec.voltage_low_pu - controlled_vm,
            0.0,
        )
        deviation = abs(controlled_vm - self.spec.voltage_target_pu)
        reward = (
            -float(self.spec.voltage_violation_weight) * voltage_violation
            - float(self.spec.voltage_deviation_weight) * deviation
            - float(self.spec.action_weight) * abs(applied_action_mw)
        )
        return {
            "step": int(step),
            "pv_mw": float(pv_mw),
            "action_mw": float(applied_action_mw),
            "soc_mwh": float(self.soc_mwh),
            "controlled_vm_pu": controlled_vm,
            "max_vm_pu": float(vm.max()),
            "min_vm_pu": float(vm.min()),
            "voltage_violation": float(voltage_violation),
            "reward": float(reward),
        }

    def _set_step(self, step: int, action_mw: float) -> tuple[float, float]:
        load_multiplier = float(self.spec.load_multiplier_profile[int(step)])
        pv_mw = float(self.spec.der.pv_capacity_mw * self.spec.pv_profile[int(step)])
        requested_action = self._clamp_action(float(action_mw))
        for idx, p_mw in enumerate(self.base_load_p * load_multiplier):
            self.adapter.change_load(
                idx,
                float(p_mw),
                float(self.base_load_q[idx] * load_multiplier),
            )

        battery_charge_mw = max(-requested_action, 0.0)
        battery_discharge_mw = max(requested_action, 0.0)
        self.adapter.change_load(self.battery_load_idx, battery_charge_mw, 0.0)
        self.adapter.change_sgen(self.pv_sgen_idx, pv_mw, 0.0)
        self.adapter.change_sgen(self.battery_sgen_idx, battery_discharge_mw, 0.0)
        self.soc_mwh = min(
            max(
                self.soc_mwh - requested_action * float(self.spec.timestep_hours),
                float(self.spec.der.battery.min_soc_mwh),
            ),
            float(self.spec.der.max_soc_mwh),
        )
        return pv_mw, requested_action

    def _clamp_action(self, action_mw: float) -> float:
        battery = self.spec.der.battery
        requested_action = float(action_mw)
        if requested_action > 0 and self.soc_mwh <= battery.min_soc_mwh:
            return 0.0
        if requested_action < 0 and self.soc_mwh >= self.spec.der.max_soc_mwh:
            return 0.0
        if requested_action > 0:
            return min(
                requested_action,
                (self.soc_mwh - float(battery.min_soc_mwh))
                / float(self.spec.timestep_hours),
            )
        if requested_action < 0:
            return -min(
                abs(requested_action),
                (float(self.spec.der.max_soc_mwh) - self.soc_mwh)
                / float(self.spec.timestep_hours),
            )
        return 0.0


def _validate_environment_spec(spec: VoltageControlEnvironmentSpec) -> None:
    if len(spec.load_multiplier_profile) != len(spec.pv_profile):
        raise ValueError("load_multiplier_profile and pv_profile must have equal length")
    if len(spec.load_multiplier_profile) == 0:
        raise ValueError("profiles must not be empty")
    if spec.timestep_hours <= 0:
        raise ValueError("timestep_hours must be positive")
    if spec.voltage_low_pu >= spec.voltage_high_pu:
        raise ValueError("voltage_low_pu must be less than voltage_high_pu")

"""Voltage-control environment composed from the backend, observation and
policy seams (10-01, 10-03, 10-04).

Before this module, ``VoltageControlEnvironment`` fused four concerns in 138
lines: it built the feeder, hardcoded ``LightSimPowerflowAdapter`` as the
solver, read voltage through that adapter's own low-level API (bypassing the
pandapower result tables every other power-flow call site in this repository
reads), and computed the reward inline. It now composes three swappable
seams instead:

* the solver is resolved from the :mod:`gridalyn.simulation.backends`
  registry (10-01), not hardcoded;
* what a step observes is built through :func:`gridalyn.simulation.
  observation.contract.observe_network` (10-03), not a bespoke adapter call;
* an action can come from a registered :class:`gridalyn.simulation.policies.
  contract.Policy` (10-04) via :func:`run_policy_episode`, though
  :meth:`VoltageControlEnvironment.step` itself still accepts an externally
  supplied action -- Q-learning training needs to inject arbitrary
  exploratory actions, which a fixed policy interface cannot express, so
  :mod:`gridalyn.simulation.control.tabular_voltage` keeps driving ``step``
  directly during training and only becomes a :class:`Policy` afterward.

Switching the solver from the adapter's incremental, warm-started AC power
flow to a full :func:`gridalyn.simulation.backends.registry.solve_power_flow`
call every step is a real implementation change, not just a rename -- proven
byte-identical over a full episode against the pre-decomposition adapter path
in ``tests/test_voltage_control_environment.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from gridalyn.assets.modeling.feeders import RadialFeederSpec
from gridalyn.assets.modeling.voltage_control import VoltageControlDERSpec
from gridalyn.simulation.backends.contract import LIGHTSIM2GRID_BACKEND_ID
from gridalyn.simulation.backends.registry import resolve_powerflow_backend
from gridalyn.simulation.observation.contract import observe_network
from gridalyn.simulation.policies.contract import voltage_at_bus
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

    def __init__(
        self,
        spec: VoltageControlEnvironmentSpec,
        *,
        backend_id: str = LIGHTSIM2GRID_BACKEND_ID,
    ) -> None:
        """Build the environment, resolving its solver from the backend registry.

        Args:
            spec: The environment configuration.
            backend_id: Power-flow backend to solve every step with, resolved
                through :func:`gridalyn.simulation.backends.registry.
                resolve_powerflow_backend`. Defaults to ``lightsim2grid`` --
                the engine this environment always used before the backend
                seam existed -- so the default configuration's behaviour is
                unchanged.
        """
        _validate_environment_spec(spec)
        self.spec = spec
        self.net = build_voltage_control_feeder(spec.feeder, spec.der)
        self.backend_id = backend_id
        self._backend = resolve_powerflow_backend(backend_id)
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
        """Reset the battery state of charge to its configured initial value."""
        self.soc_mwh = float(self.spec.der.battery.initial_soc_mwh)

    def step(self, step: int, action_mw: float) -> dict:
        """Apply an externally supplied action and return the resulting metrics.

        Args:
            step: Zero-based step index.
            action_mw: Requested battery action in MW; the environment still
                applies its own state-of-charge feasibility clamp.

        Returns:
            A record with the applied action, resulting voltages and reward.
        """
        pv_mw, applied_action_mw = self._set_step(step, action_mw)
        self._backend.solve(self.net)
        observation = observe_network(self.net)
        controlled_vm = voltage_at_bus(observation, self.spec.der.controlled_bus_id)
        vm_max = observation.max_voltage_pu
        vm_min = observation.min_voltage_pu
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
            "max_vm_pu": vm_max,
            "min_vm_pu": vm_min,
            "voltage_violation": float(voltage_violation),
            "reward": float(reward),
        }

    def _set_step(self, step: int, action_mw: float) -> tuple[float, float]:
        load_multiplier = float(self.spec.load_multiplier_profile[int(step)])
        pv_mw = float(self.spec.der.pv_capacity_mw * self.spec.pv_profile[int(step)])
        requested_action = self._clamp_action(float(action_mw))
        for idx, p_mw in enumerate(self.base_load_p * load_multiplier):
            self.net.load.at[idx, "p_mw"] = float(p_mw)
            self.net.load.at[idx, "q_mvar"] = float(
                self.base_load_q[idx] * load_multiplier
            )

        battery_charge_mw = max(-requested_action, 0.0)
        battery_discharge_mw = max(requested_action, 0.0)
        self.net.load.at[self.battery_load_idx, "p_mw"] = battery_charge_mw
        self.net.load.at[self.battery_load_idx, "q_mvar"] = 0.0
        self.net.sgen.at[self.pv_sgen_idx, "p_mw"] = pv_mw
        self.net.sgen.at[self.pv_sgen_idx, "q_mvar"] = 0.0
        self.net.sgen.at[self.battery_sgen_idx, "p_mw"] = battery_discharge_mw
        self.net.sgen.at[self.battery_sgen_idx, "q_mvar"] = 0.0
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


def run_policy_episode(
    spec: VoltageControlEnvironmentSpec,
    policy: Any,
    step_count: int,
    *,
    backend_id: str = LIGHTSIM2GRID_BACKEND_ID,
) -> list[dict]:
    """Run a full episode driven entirely by a :class:`Policy` (the policy seam).

    This is where the third composed seam becomes observable: unlike
    :meth:`VoltageControlEnvironment.step`, which still takes its action from
    the caller, this function asks a registered policy for every action, so
    substituting a second policy here is what proves the seam -- not the
    ``step`` method, which stays externally driven for the reasons in this
    module's docstring.

    Args:
        spec: The environment configuration.
        policy: A :class:`gridalyn.simulation.policies.contract.Policy`
            already constructed with whatever state it needs (a trained
            Q-table, a measured sensitivity coefficient, ...).
        step_count: Number of steps to run.
        backend_id: Power-flow backend the environment solves with.

    Returns:
        One step record per step, in the same shape :meth:`VoltageControlEnvironment.
        step` returns.
    """
    env = VoltageControlEnvironment(spec, backend_id=backend_id)
    env.reset()
    records = []
    action_mw = 0.0
    for step in range(int(step_count)):
        record = env.step(step, action_mw)
        records.append(record)
        action_mw = policy.decide(
            observe_network(env.net),
            soc_mwh=env.soc_mwh,
            step=step,
        )
    return records


def _validate_environment_spec(spec: VoltageControlEnvironmentSpec) -> None:
    if len(spec.load_multiplier_profile) != len(spec.pv_profile):
        raise ValueError(
            "load_multiplier_profile and pv_profile must have equal length"
        )
    if len(spec.load_multiplier_profile) == 0:
        raise ValueError("profiles must not be empty")
    if spec.timestep_hours <= 0:
        raise ValueError("timestep_hours must be positive")
    if spec.voltage_low_pu >= spec.voltage_high_pu:
        raise ValueError("voltage_low_pu must be less than voltage_high_pu")

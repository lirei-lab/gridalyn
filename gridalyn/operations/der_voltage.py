"""Voltage-constrained DER dispatch operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd

from gridalyn.assets.modeling.feeders import RadialFeederSpec
from gridalyn.assets.modeling.voltage_control import VoltageControlDERSpec
from gridalyn.simulation.backends.contract import DEFAULT_POWERFLOW_BACKEND_ID
from gridalyn.simulation.backends.registry import solve_power_flow
from gridalyn.simulation.policies.contract import voltage_at_bus
from gridalyn.simulation.simulators.powerflow.der_dispatch import (
    apply_der_dispatch_setpoints_to_pandapower,
    build_der_dispatch_pandapower_network,
)
from gridalyn.simulation.simulators.powerflow.voltage_control import (
    build_voltage_control_feeder,
)
from gridalyn.twin.observation.contract import NetworkObservation, observe_network


@dataclass(frozen=True)
class DERVoltageDispatchConfig:
    """Configuration for linearized voltage-constrained DER dispatch."""

    voltage_min_pu: float = 0.95
    voltage_max_pu: float = 1.05
    perturbation_mw: float = 0.05
    voltage_target_pu: float = 1.01
    battery_charge_weight: float = 0.04
    voltage_deviation_weight: float = 0.05
    solver_name: str = "CLARABEL"


# Module-level default so the dataclass is not constructed in an argument
# default (bugbear B008). Safe to share: the config is frozen and immutable.
_DEFAULT_DISPATCH_CONFIG = DERVoltageDispatchConfig()


@dataclass(frozen=True)
class DERVoltageDispatchResult:
    """Tables and metadata produced by a DER voltage dispatch run.

    The two observations are kept apart on purpose. They are two *network
    states* -- the feeder at full PV output and the feeder at the optimized
    setpoints -- not a full and a filtered view of one state, and the summary
    reports a maximum for both but a minimum only for the optimized one.
    Collapsing them would change what the study reports.

    Attributes:
        sensitivity: Per-bus, per-DER voltage sensitivity table.
        dispatch: Per-DER dispatch decision table.
        verification: Per-bus voltages under both verified network states.
        optimization_metadata: Solver name, status and objective value.
        full_pv_converged: Whether the full-PV verification net converged.
        optimized_converged: Whether the optimized verification net converged.
        full_pv_observation: Observation of the full-PV verification net.
        optimized_observation: Observation of the optimized verification net.
    """

    sensitivity: pd.DataFrame
    dispatch: pd.DataFrame
    verification: pd.DataFrame
    optimization_metadata: dict
    full_pv_converged: bool
    optimized_converged: bool
    full_pv_observation: NetworkObservation
    optimized_observation: NetworkObservation


def run_der_voltage_dispatch(
    build_feeder: Callable[[], pp.pandapowerNet],
    der_assets: pd.DataFrame,
    config: DERVoltageDispatchConfig = _DEFAULT_DISPATCH_CONFIG,
) -> DERVoltageDispatchResult:
    """Solve DER dispatch and verify the result with an AC pandapower snapshot."""
    base_voltage = _base_voltage(build_feeder)
    sensitivity = _voltage_sensitivity(
        build_feeder,
        der_assets,
        base_voltage,
        config,
    )
    dispatch, optimization_metadata = _solve_dispatch(
        der_assets,
        base_voltage,
        sensitivity,
        config,
    )

    full_pv_net = build_der_dispatch_pandapower_network(
        build_feeder,
        der_assets,
        der_assets["pv_available_mw"].to_numpy(dtype=float),
        np.zeros(len(der_assets)),
    )
    optimized_net = build_der_dispatch_pandapower_network(
        build_feeder,
        der_assets,
        dispatch["pv_dispatch_mw"].to_numpy(dtype=float),
        dispatch["battery_charge_mw"].to_numpy(dtype=float),
    )
    full_pv_observation = observe_network(full_pv_net)
    optimized_observation = observe_network(optimized_net)
    verification = pd.DataFrame(
        {
            # Positional, not the result index: preserved verbatim from before
            # the observation contract, because the figure and the study
            # artifact both key off it.
            "bus_id": list(range(len(optimized_net.bus))),
            "full_pv_vm_pu": full_pv_observation.bus_voltage_pu,
            "optimized_vm_pu": optimized_observation.bus_voltage_pu,
        }
    )
    return DERVoltageDispatchResult(
        sensitivity=sensitivity,
        dispatch=dispatch,
        verification=verification,
        optimization_metadata=optimization_metadata,
        full_pv_converged=full_pv_observation.converged,
        optimized_converged=optimized_observation.converged,
        full_pv_observation=full_pv_observation,
        optimized_observation=optimized_observation,
    )


def summarize_der_voltage_dispatch(
    result: DERVoltageDispatchResult,
) -> dict:
    """Build the canonical report summary for a DER voltage dispatch result."""
    dispatch = result.dispatch
    return {
        "algorithm": "cvxpy_linearized_voltage_constrained_der_dispatch",
        "solver": result.optimization_metadata["solver_name"],
        "solver_status": result.optimization_metadata["solver_status"],
        "objective_value": result.optimization_metadata["objective_value"],
        "der_count": int(len(dispatch)),
        "total_pv_available_mw": float(dispatch["pv_available_mw"].sum()),
        "total_pv_dispatch_mw": float(dispatch["pv_dispatch_mw"].sum()),
        "total_pv_curtailment_mw": float(dispatch["pv_curtailment_mw"].sum()),
        "total_battery_charge_mw": float(dispatch["battery_charge_mw"].sum()),
        "verified_max_voltage_before_pu": result.full_pv_observation.max_voltage_pu,
        "verified_max_voltage_after_pu": result.optimized_observation.max_voltage_pu,
        "verified_min_voltage_after_pu": result.optimized_observation.min_voltage_pu,
    }


def write_der_voltage_dispatch_figure(
    verification: pd.DataFrame,
    dispatch: pd.DataFrame,
    path: str | Path,
    *,
    voltage_max_pu: float = 1.05,
) -> Path:
    """Write the canonical DER voltage-dispatch figure."""
    from gridalyn.simulation import configure_headless_matplotlib

    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    figure_path = Path(path)
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(9.4, 7.0),
        gridspec_kw={"height_ratios": [1.2, 1.0]},
    )
    axes[0].plot(
        verification["bus_id"],
        verification["full_pv_vm_pu"],
        marker="o",
        label="Full PV",
    )
    axes[0].plot(
        verification["bus_id"],
        verification["optimized_vm_pu"],
        marker="o",
        label="Optimized",
    )
    axes[0].axhline(
        voltage_max_pu,
        color="#c0392b",
        linestyle="--",
        linewidth=1.2,
        label="1.05 p.u.",
    )
    axes[0].set_ylabel("Voltage [p.u.]")
    axes[0].set_title("DER Dispatch Verified With Pandapower")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    x = np.arange(len(dispatch))
    axes[1].bar(x - 0.25, dispatch["pv_available_mw"], width=0.25, label="PV available")
    axes[1].bar(x, dispatch["pv_dispatch_mw"], width=0.25, label="PV dispatch")
    axes[1].bar(
        x + 0.25, dispatch["battery_charge_mw"], width=0.25, label="Battery charge"
    )
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(dispatch["der_id"])
    axes[1].set_ylabel("Power [MW]")
    axes[1].grid(True, axis="y", alpha=0.3)
    axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _base_voltage(build_feeder: Callable[[], pp.pandapowerNet]) -> np.ndarray:
    net = build_feeder()
    solve_power_flow(net)
    return observe_network(net).bus_voltage_pu


def _voltage_sensitivity(
    build_feeder: Callable[[], pp.pandapowerNet],
    der_assets: pd.DataFrame,
    base_voltage: np.ndarray,
    config: DERVoltageDispatchConfig,
) -> pd.DataFrame:
    rows = []
    for asset in der_assets.itertuples(index=False):
        net = build_feeder()
        apply_der_dispatch_setpoints_to_pandapower(
            net,
            pd.DataFrame([asset._asdict()]),
            np.array([config.perturbation_mw], dtype=float),
            np.array([0.0], dtype=float),
        )
        solve_power_flow(net)
        perturbed = observe_network(net).bus_voltage_pu
        delta = (perturbed - base_voltage) / config.perturbation_mw
        for bus_id, value in enumerate(delta):
            rows.append(
                {
                    "bus_id": bus_id,
                    "der_id": asset.der_id,
                    "der_bus_id": int(asset.bus_id),
                    "dvm_dpinj_pu_per_mw": float(value),
                }
            )
    return pd.DataFrame(rows)


def _solve_dispatch(
    der_assets: pd.DataFrame,
    base_voltage: np.ndarray,
    sensitivity: pd.DataFrame,
    config: DERVoltageDispatchConfig,
) -> tuple[pd.DataFrame, dict]:
    import cvxpy as cp

    der_ids = list(der_assets["der_id"])
    bus_ids = sorted(sensitivity["bus_id"].unique())
    s_matrix = (
        sensitivity.pivot(
            index="bus_id", columns="der_id", values="dvm_dpinj_pu_per_mw"
        )
        .loc[bus_ids, der_ids]
        .to_numpy(dtype=float)
    )
    pv_available = der_assets["pv_available_mw"].to_numpy(dtype=float)
    battery_power = der_assets["battery_charge_power_mw"].to_numpy(dtype=float)

    pv_dispatch = cp.Variable(len(der_assets))
    battery_charge = cp.Variable(len(der_assets))
    net_injection = pv_dispatch - battery_charge
    predicted_voltage = base_voltage + s_matrix @ net_injection

    objective = cp.Minimize(
        cp.sum(pv_available - pv_dispatch)
        + config.battery_charge_weight * cp.sum(battery_charge)
        + config.voltage_deviation_weight
        * cp.sum_squares(predicted_voltage - config.voltage_target_pu)
    )
    problem = cp.Problem(
        objective,
        [
            pv_dispatch >= 0.0,
            pv_dispatch <= pv_available,
            battery_charge >= 0.0,
            battery_charge <= battery_power,
            predicted_voltage >= config.voltage_min_pu,
            predicted_voltage <= config.voltage_max_pu,
        ],
    )
    problem.solve(solver=getattr(cp, config.solver_name))

    dispatch = der_assets.copy()
    dispatch["pv_dispatch_mw"] = np.asarray(pv_dispatch.value, dtype=float)
    dispatch["pv_curtailment_mw"] = (
        dispatch["pv_available_mw"] - dispatch["pv_dispatch_mw"]
    )
    dispatch["battery_charge_mw"] = np.asarray(battery_charge.value, dtype=float)
    dispatch["net_injection_mw"] = (
        dispatch["pv_dispatch_mw"] - dispatch["battery_charge_mw"]
    )
    dispatch["predicted_voltage_at_bus_pu"] = [
        float(predicted_voltage.value[int(bus_id)]) for bus_id in dispatch["bus_id"]
    ]
    metadata = {
        "solver_name": config.solver_name,
        "solver_status": str(problem.status),
        "objective_value": float(problem.value),
    }
    return dispatch, metadata


def measure_local_voltage_sensitivity(
    feeder: RadialFeederSpec,
    der: VoltageControlDERSpec,
    *,
    perturbation_mw: float = 0.01,
    backend_id: str = DEFAULT_POWERFLOW_BACKEND_ID,
) -> float:
    """Measure the local dV/dP sensitivity at one bus for one battery.

    Paradigm 2 (sensitivity dispatch) adapted from :func:`_voltage_sensitivity`'s
    multi-DER finite-difference technique -- perturb, resolve, take the delta
    -- to :class:`gridalyn.simulation.environments.voltage_control.
    VoltageControlEnvironment`'s single controlled bus and single battery.
    Where :func:`_voltage_sensitivity` perturbs every DER in a batch against a
    shared base voltage, this measures exactly one DER against its own,
    freshly solved base case, because the caller (a
    :class:`gridalyn.simulation.policies.registry.SensitivityDispatchPolicy`)
    needs one scalar coefficient, not a per-DER table.

    Args:
        feeder: The feeder to measure on.
        der: DER spec naming the controlled bus and the battery's discharge
            ``sgen``.
        perturbation_mw: Injection step applied to the battery's discharge
            ``sgen`` to measure the response.
        backend_id: Power-flow backend to solve both cases with. Both the
            base and the perturbed case use the same backend, so the
            measured sensitivity is not itself an artifact of a backend
            disagreement -- the concern 10-01 exists to close.

    Returns:
        ``(perturbed_vm - base_vm) / perturbation_mw`` at ``der.
        controlled_bus_id``, in per-unit voltage per MW.
    """
    base_net = build_voltage_control_feeder(feeder, der)
    solve_power_flow(base_net, backend_id=backend_id)
    base_vm = voltage_at_bus(observe_network(base_net), der.controlled_bus_id)

    perturbed_net = build_voltage_control_feeder(feeder, der)
    battery_sgen_idx = perturbed_net.sgen.index[
        perturbed_net.sgen["name"] == "battery_discharge"
    ][0]
    perturbed_net.sgen.at[battery_sgen_idx, "p_mw"] = float(perturbation_mw)
    solve_power_flow(perturbed_net, backend_id=backend_id)
    perturbed_vm = voltage_at_bus(observe_network(perturbed_net), der.controlled_bus_id)

    return float((perturbed_vm - base_vm) / perturbation_mw)


__all__ = [
    "DERVoltageDispatchConfig",
    "DERVoltageDispatchResult",
    "measure_local_voltage_sensitivity",
    "run_der_voltage_dispatch",
    "summarize_der_voltage_dispatch",
    "write_der_voltage_dispatch_figure",
]

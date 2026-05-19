"""Solve a cvxpy voltage-constrained DER dispatch and verify with pandapower."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import cvxpy as cp
import matplotlib
import numpy as np
import pandas as pd
import pandapower as pp

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from gridalyn.foundation import ReportMetadata, file_reference, write_report

from network_model import build_der_feeder


PROJECT_NAME = "der_voltage_optimization"
V_MIN = 0.95
V_MAX = 1.05
PERTURBATION_MW = 0.05


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/figures", "outputs/operations", "outputs/reports", "outputs/cache"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _run_net_with_setpoints(der_assets: pd.DataFrame, pv_dispatch: np.ndarray, battery_charge: np.ndarray) -> pp.pandapowerNet:
    net = build_der_feeder()
    for idx, row in enumerate(der_assets.itertuples(index=False)):
        pp.create_sgen(
            net,
            bus=int(row.bus_id),
            p_mw=float(pv_dispatch[idx]),
            q_mvar=0.0,
            name=f"{row.der_id}_pv_dispatch",
            type="PV",
        )
        if float(battery_charge[idx]) > 0:
            pp.create_load(
                net,
                bus=int(row.bus_id),
                p_mw=float(battery_charge[idx]),
                q_mvar=0.0,
                name=f"{row.der_id}_battery_charge",
                type="battery_charge",
            )
    pp.runpp(net, algorithm="nr", init="auto")
    return net


def _base_voltage() -> np.ndarray:
    net = build_der_feeder()
    pp.runpp(net, algorithm="nr", init="auto")
    return net.res_bus.vm_pu.to_numpy(dtype=float)


def _voltage_sensitivity(der_assets: pd.DataFrame, base_voltage: np.ndarray) -> pd.DataFrame:
    rows = []
    for asset in der_assets.itertuples(index=False):
        net = build_der_feeder()
        pp.create_sgen(
            net,
            bus=int(asset.bus_id),
            p_mw=PERTURBATION_MW,
            q_mvar=0.0,
            name=f"{asset.der_id}_sensitivity",
            type="PV",
        )
        pp.runpp(net, algorithm="nr", init="auto")
        delta = (net.res_bus.vm_pu.to_numpy(dtype=float) - base_voltage) / PERTURBATION_MW
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


def _solve_dispatch(der_assets: pd.DataFrame, base_voltage: np.ndarray, sensitivity: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    der_ids = list(der_assets["der_id"])
    bus_ids = sorted(sensitivity["bus_id"].unique())
    s_matrix = (
        sensitivity.pivot(index="bus_id", columns="der_id", values="dvm_dpinj_pu_per_mw")
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
        + 0.04 * cp.sum(battery_charge)
        + 0.05 * cp.sum_squares(predicted_voltage - 1.01)
    )
    problem = cp.Problem(
        objective,
        [
            pv_dispatch >= 0.0,
            pv_dispatch <= pv_available,
            battery_charge >= 0.0,
            battery_charge <= battery_power,
            predicted_voltage >= V_MIN,
            predicted_voltage <= V_MAX,
        ],
    )
    problem.solve(solver=cp.CLARABEL)

    dispatch = der_assets.copy()
    dispatch["pv_dispatch_mw"] = np.asarray(pv_dispatch.value, dtype=float)
    dispatch["pv_curtailment_mw"] = dispatch["pv_available_mw"] - dispatch["pv_dispatch_mw"]
    dispatch["battery_charge_mw"] = np.asarray(battery_charge.value, dtype=float)
    dispatch["net_injection_mw"] = dispatch["pv_dispatch_mw"] - dispatch["battery_charge_mw"]
    dispatch["predicted_voltage_at_bus_pu"] = [
        float(predicted_voltage.value[int(bus_id)]) for bus_id in dispatch["bus_id"]
    ]

    metadata = {
        "solver_name": "CLARABEL",
        "solver_status": str(problem.status),
        "objective_value": float(problem.value),
    }
    return dispatch, metadata


def _verification_table(full_pv_net: pp.pandapowerNet, optimized_net: pp.pandapowerNet) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bus_id": list(range(len(optimized_net.bus))),
            "full_pv_vm_pu": full_pv_net.res_bus.vm_pu.to_numpy(dtype=float),
            "optimized_vm_pu": optimized_net.res_bus.vm_pu.to_numpy(dtype=float),
        }
    )


def _write_figure(verification: pd.DataFrame, dispatch: pd.DataFrame) -> Path:
    figure_path = Path("outputs/figures/der_voltage_optimization.png")
    fig, axes = plt.subplots(2, 1, figsize=(9.4, 7.0), gridspec_kw={"height_ratios": [1.2, 1.0]})
    axes[0].plot(verification["bus_id"], verification["full_pv_vm_pu"], marker="o", label="Full PV")
    axes[0].plot(verification["bus_id"], verification["optimized_vm_pu"], marker="o", label="Optimized")
    axes[0].axhline(V_MAX, color="#c0392b", linestyle="--", linewidth=1.2, label="1.05 p.u.")
    axes[0].set_ylabel("Voltage [p.u.]")
    axes[0].set_title("CVXPY DER Dispatch Verified With Pandapower")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    x = np.arange(len(dispatch))
    axes[1].bar(x - 0.25, dispatch["pv_available_mw"], width=0.25, label="PV available")
    axes[1].bar(x, dispatch["pv_dispatch_mw"], width=0.25, label="PV dispatch")
    axes[1].bar(x + 0.25, dispatch["battery_charge_mw"], width=0.25, label="Battery charge")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(dispatch["der_id"])
    axes[1].set_ylabel("Power [MW]")
    axes[1].grid(True, axis="y", alpha=0.3)
    axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def main() -> int:
    _ensure_outputs()
    der_assets_path = Path("outputs/data/der_assets.csv")
    der_assets = pd.read_csv(der_assets_path)
    base_voltage = _base_voltage()
    sensitivity = _voltage_sensitivity(der_assets, base_voltage)
    dispatch, optimization_metadata = _solve_dispatch(der_assets, base_voltage, sensitivity)

    full_pv_net = _run_net_with_setpoints(
        der_assets,
        der_assets["pv_available_mw"].to_numpy(dtype=float),
        np.zeros(len(der_assets)),
    )
    optimized_net = _run_net_with_setpoints(
        der_assets,
        dispatch["pv_dispatch_mw"].to_numpy(dtype=float),
        dispatch["battery_charge_mw"].to_numpy(dtype=float),
    )
    verification = _verification_table(full_pv_net, optimized_net)

    sensitivity_path = Path("outputs/data/voltage_sensitivity_matrix.csv")
    dispatch_path = Path("outputs/operations/der_dispatch.csv")
    verification_path = Path("outputs/data/pandapower_verification.csv")
    sensitivity.to_csv(sensitivity_path, index=False)
    dispatch.to_csv(dispatch_path, index=False)
    verification.to_csv(verification_path, index=False)
    figure_path = _write_figure(verification, dispatch)

    max_after = float(verification["optimized_vm_pu"].max())
    valid = bool(
        optimized_net.converged
        and optimization_metadata["solver_status"] in {"optimal", "optimal_inaccurate"}
        and max_after <= V_MAX + 1e-3
    )
    write_report(
        Path("outputs/reports/der_voltage_optimization_report.json"),
        metadata=ReportMetadata(
            report_id="der_voltage_optimization_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(der_assets_path),
            {"name": "cvxpy_linearized_voltage_model", "type": "optimization_model"},
        ],
        artifacts=[
            file_reference(sensitivity_path),
            file_reference(dispatch_path),
            file_reference(verification_path),
            file_reference(figure_path),
        ],
        summary={
            "algorithm": "cvxpy_linearized_voltage_constrained_der_dispatch",
            "solver": optimization_metadata["solver_name"],
            "solver_status": optimization_metadata["solver_status"],
            "objective_value": optimization_metadata["objective_value"],
            "der_count": int(len(der_assets)),
            "total_pv_available_mw": float(dispatch["pv_available_mw"].sum()),
            "total_pv_dispatch_mw": float(dispatch["pv_dispatch_mw"].sum()),
            "total_pv_curtailment_mw": float(dispatch["pv_curtailment_mw"].sum()),
            "total_battery_charge_mw": float(dispatch["battery_charge_mw"].sum()),
            "verified_max_voltage_before_pu": float(verification["full_pv_vm_pu"].max()),
            "verified_max_voltage_after_pu": max_after,
            "verified_min_voltage_after_pu": float(verification["optimized_vm_pu"].min()),
        },
        validation={
            "valid": valid,
            "errors": [] if valid else ["optimized pandapower verification exceeded voltage limit"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

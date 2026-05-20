"""Generate deterministic operational scenarios for the IEEE 33-bus demo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pandapower as pp
import pandapower.networks as pn

from gridalyn.foundation import ReportMetadata, file_reference, write_report


PROJECT_NAME = "ieee_33_bus_demo"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    load_multiplier: float = 1.0
    pv_buses: tuple[int, ...] = ()
    pv_mw_per_bus: float = 0.0
    ev_buses: tuple[int, ...] = ()
    ev_mw_per_bus: float = 0.0


SCENARIOS = (
    Scenario(
        scenario_id="baseline",
        description="Original IEEE 33-bus feeder.",
    ),
    Scenario(
        scenario_id="load_growth_20",
        description="Uniform 20 percent demand growth.",
        load_multiplier=1.2,
    ),
    Scenario(
        scenario_id="pv_midday",
        description="Midday distributed PV at selected downstream buses.",
        pv_buses=(6, 14, 24, 30),
        pv_mw_per_bus=0.25,
    ),
    Scenario(
        scenario_id="ev_evening_peak",
        description="Evening EV charging demand at selected downstream buses.",
        ev_buses=(17, 18, 25, 30, 32),
        ev_mw_per_bus=0.18,
    ),
    Scenario(
        scenario_id="pv_plus_ev",
        description="Combined PV and EV condition for a mixed operating case.",
        pv_buses=(6, 14, 24, 30),
        pv_mw_per_bus=0.18,
        ev_buses=(17, 18, 25, 30, 32),
        ev_mw_per_bus=0.12,
    ),
)


def _ensure_outputs() -> None:
    for relative in (
        "outputs/data",
        "outputs/figures",
        "outputs/reports",
        "outputs/cache",
    ):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _base_network() -> pp.pandapowerNet:
    return pn.case33bw()


def _apply_scenario(net: pp.pandapowerNet, scenario: Scenario) -> None:
    net.load["p_mw"] = net.load["p_mw"] * scenario.load_multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * scenario.load_multiplier

    for bus in scenario.pv_buses:
        pp.create_sgen(
            net,
            bus=bus,
            p_mw=scenario.pv_mw_per_bus,
            q_mvar=0.0,
            name=f"{scenario.scenario_id}_pv_bus_{bus}",
            type="PV",
        )

    for bus in scenario.ev_buses:
        pp.create_load(
            net,
            bus=bus,
            p_mw=scenario.ev_mw_per_bus,
            q_mvar=scenario.ev_mw_per_bus * 0.25,
            name=f"{scenario.scenario_id}_ev_bus_{bus}",
            type="EV",
        )


def _run_scenario(scenario: Scenario) -> tuple[dict, pd.DataFrame]:
    net = _base_network()
    _apply_scenario(net, scenario)
    pp.runpp(net, algorithm="nr", init="auto")

    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]
    voltage["scenario_id"] = scenario.scenario_id

    result = {
        "scenario_id": scenario.scenario_id,
        "description": scenario.description,
        "load_multiplier": scenario.load_multiplier,
        "pv_bus_count": len(scenario.pv_buses),
        "pv_total_mw": len(scenario.pv_buses) * scenario.pv_mw_per_bus,
        "ev_bus_count": len(scenario.ev_buses),
        "ev_total_mw": len(scenario.ev_buses) * scenario.ev_mw_per_bus,
        "converged": bool(net.converged),
        "total_load_mw": float(net.load.p_mw.sum()),
        "total_generation_mw": float(net.sgen.p_mw.sum()) if len(net.sgen) else 0.0,
        "net_demand_mw": float(net.load.p_mw.sum() - net.sgen.p_mw.sum()) if len(net.sgen) else float(net.load.p_mw.sum()),
        "line_loss_mw": float(net.res_line.pl_mw.sum()),
        "min_voltage_pu": float(net.res_bus.vm_pu.min()),
        "max_voltage_pu": float(net.res_bus.vm_pu.max()),
        "max_line_loading_percent": float(net.res_line.loading_percent.max()),
        "voltage_violation_count": int((net.res_bus.vm_pu < 0.95).sum() + (net.res_bus.vm_pu > 1.05).sum()),
    }
    return result, voltage


def _write_scenario_inputs() -> Path:
    path = Path("outputs/data/scenarios.csv")
    rows = [
        {
            "scenario_id": scenario.scenario_id,
            "description": scenario.description,
            "load_multiplier": scenario.load_multiplier,
            "pv_buses": " ".join(str(bus) for bus in scenario.pv_buses),
            "pv_mw_per_bus": scenario.pv_mw_per_bus,
            "ev_buses": " ".join(str(bus) for bus in scenario.ev_buses),
            "ev_mw_per_bus": scenario.ev_mw_per_bus,
        }
        for scenario in SCENARIOS
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_voltage_comparison(results: pd.DataFrame, voltages: pd.DataFrame) -> Path:
    figure_path = Path("outputs/figures/ieee33_scenario_voltage_comparison.png")
    fig, ax = plt.subplots(figsize=(10, 5.4))
    for scenario_id, group in voltages.groupby("scenario_id", sort=False):
        ax.plot(group["bus_id"], group["vm_pu"], linewidth=1.7, marker="o", markersize=3, label=scenario_id)
    ax.axhline(0.95, color="#c0392b", linestyle="--", linewidth=1.2, label="0.95 p.u.")
    ax.set_title("IEEE 33-Bus Demo - Scenario Voltage Comparison")
    ax.set_xlabel("Bus index")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.32)
    ax.legend(loc="lower left", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _summary(results: pd.DataFrame) -> dict:
    best = results.sort_values(["min_voltage_pu", "line_loss_mw"], ascending=[False, True]).iloc[0]
    worst = results.sort_values(["min_voltage_pu", "line_loss_mw"], ascending=[True, False]).iloc[0]
    return {
        "scenario_count": int(len(results)),
        "scenario_ids": list(results["scenario_id"]),
        "best_voltage_scenario": str(best["scenario_id"]),
        "worst_voltage_scenario": str(worst["scenario_id"]),
        "min_voltage_pu": float(results["min_voltage_pu"].min()),
        "max_voltage_pu": float(results["max_voltage_pu"].max()),
        "max_line_loading_percent": float(results["max_line_loading_percent"].max()),
        "max_voltage_violation_count": int(results["voltage_violation_count"].max()),
    }


def main() -> int:
    _ensure_outputs()
    scenario_input_path = _write_scenario_inputs()
    rows = []
    voltage_frames = []
    for scenario in SCENARIOS:
        result, voltage = _run_scenario(scenario)
        rows.append(result)
        voltage_frames.append(voltage)

    results = pd.DataFrame(rows)
    voltages = pd.concat(voltage_frames, ignore_index=True)
    result_path = Path("outputs/data/scenario_results.csv")
    voltage_path = Path("outputs/data/scenario_voltage_profiles.csv")
    results.to_csv(result_path, index=False)
    voltages.to_csv(voltage_path, index=False)
    figure_path = _write_voltage_comparison(results, voltages)
    report_path = Path("outputs/reports/ieee33_scenario_comparison_report.json")

    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="ieee33_scenario_comparison_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(scenario_input_path),
            {"name": "pandapower.networks.case33bw", "type": "pandapower_builtin_network"},
        ],
        artifacts=[
            file_reference(result_path),
            file_reference(voltage_path),
            file_reference(figure_path),
        ],
        summary=_summary(results),
        validation={
            "valid": bool(results["converged"].all()),
            "errors": [] if bool(results["converged"].all()) else ["one or more scenarios did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a generated daily load time series on the IEEE 33-bus benchmark feeder."""

from __future__ import annotations

import pandas as pd

from gridalyn.assets import IEEE_33_BUS_BENCHMARK
from gridalyn.assets.datagen import scale_profiles_to_peaks
from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import build_ieee33_benchmark_feeder


def _write_envelope_figure(script: ProjectScript, results: pd.DataFrame) -> str:
    import matplotlib.pyplot as plt

    figure_path = script.figures_dir / "ieee33_daily_voltage_envelope.png"
    hours = results["hour"]
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.fill_between(
        hours,
        results["min_voltage_pu"],
        results["max_voltage_pu"],
        alpha=0.30,
        color="#0aa6b5",
        label="Voltage envelope (all buses)",
    )
    ax.plot(hours, results["min_voltage_pu"], color="#0a7a85", linewidth=1.6)
    ax.plot(hours, results["max_voltage_pu"], color="#0a7a85", linewidth=1.6)
    ax.axhline(0.95, color="#c0392b", linestyle="--", linewidth=1.2, label="0.95 p.u.")
    ax.set_title("IEEE 33-Bus Demo - Daily Voltage Envelope (Generated Loads)")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.32)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return str(figure_path)


def main() -> int:
    script = project_script()
    require_capabilities("sim", context="the IEEE 33-bus daily time-series power flow")
    import pandapower as pp

    net = build_ieee33_benchmark_feeder()
    base_p = net.load["p_mw"].copy()
    base_q = net.load["q_mvar"].copy()

    profiles = script.load_generated_load_profiles()
    # The benchmark's embedded per-load peaks anchor the magnitudes; the
    # generated profiles contribute the hourly shape and per-bus diversity.
    bus_series_mw = scale_profiles_to_peaks(profiles, dict(base_p))

    profile_path = script.data_dir / "daily_bus_load_profiles.csv"
    bus_series_mw.to_csv(profile_path, index_label="timestamp")

    rows = []
    for hour, (_, loads_mw) in enumerate(bus_series_mw.iterrows()):
        for load_idx in net.load.index:
            p_new = float(loads_mw[load_idx])
            ratio = float(base_q[load_idx]) / float(base_p[load_idx])
            net.load.at[load_idx, "p_mw"] = p_new
            net.load.at[load_idx, "q_mvar"] = p_new * ratio
        pp.runpp(net, algorithm="nr", init="auto", max_iteration=100)
        rows.append(
            {
                "hour": hour,
                "converged": bool(net.converged),
                "total_load_mw": float(net.load.p_mw.sum()),
                "min_voltage_pu": float(net.res_bus.vm_pu.min()),
                "max_voltage_pu": float(net.res_bus.vm_pu.max()),
                "max_line_loading_percent": float(net.res_line.loading_percent.max()),
                "line_loss_mw": float(net.res_line.pl_mw.sum()),
            }
        )

    results = pd.DataFrame(rows)
    results_path = script.data_dir / "daily_timeseries_results.csv"
    results.to_csv(results_path, index=False)
    figure_path = _write_envelope_figure(script, results)

    converged_hours = int(results["converged"].sum())
    peak_hour = int(results.loc[results["total_load_mw"].idxmax(), "hour"])
    script.write_report(
        "ieee33_daily_timeseries_report",
        inputs=[
            {"name": IEEE_33_BUS_BENCHMARK.source_name, "type": "gridalyn_benchmark_feeder"},
            {
                "name": "loadGeneration",
                "type": "generated_load_profile",
                **dict(script.input("loadGeneration")),
            },
        ],
        artifacts=[
            script.file_reference(profile_path),
            script.file_reference(results_path),
            script.file_reference(figure_path),
        ],
        summary={
            "hour_count": int(len(results)),
            "converged_hours": converged_hours,
            "peak_hour": peak_hour,
            "min_voltage_pu": float(results["min_voltage_pu"].min()),
            "max_voltage_pu": float(results["max_voltage_pu"].max()),
            "max_line_loading_percent": float(results["max_line_loading_percent"].max()),
            "daily_energy_mwh": float(results["total_load_mw"].sum()),
        },
        validation={
            "valid": converged_hours == len(results),
            "errors": [] if converged_hours == len(results) else ["one or more hourly power flows did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

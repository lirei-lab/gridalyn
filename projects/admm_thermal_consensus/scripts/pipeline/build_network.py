"""Stage: build IEEE-33, derive bus weights, and the feeder scale factor."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus power-flow validation")
    from gridalyn.simulation.simulators.powerflow.benchmarks import (
        build_ieee33_benchmark_feeder,
    )

    script = project_script()
    net = build_ieee33_benchmark_feeder()
    # bus weights = native per-load active-power share (sum to 1)
    loads = net.load[["bus", "p_mw"]].copy()
    total_p = float(loads["p_mw"].sum())
    loads["weight"] = loads["p_mw"] / total_p
    bus_weights = {int(r.bus): float(r.weight) for r in loads.itertuples()}

    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    uncoordinated_peak_kw = float(params["uncoordinated_peak_kw"])
    # scale so the uncoordinated aggregate peak == TARGET_FEEDER_PEAK_MW on the feeder
    scale_kw_to_mw = (C.TARGET_FEEDER_PEAK_MW * 1000.0 / uncoordinated_peak_kw) / 1000.0

    # Calibrate trunk ampacity so the uncoordinated winter peak reaches a
    # realistic overload. The scale maps the uncoordinated peak to
    # TARGET_FEEDER_PEAK_MW, so distributing that MW reproduces the peak flow.
    import pandapower as pp

    tan_phi = math.tan(math.acos(C.POWER_FACTOR))
    net_cal = build_ieee33_benchmark_feeder()
    for bus, w in bus_weights.items():
        mask = net_cal.load.bus == bus
        net_cal.load.loc[mask, "p_mw"] = C.TARGET_FEEDER_PEAK_MW * w
        net_cal.load.loc[mask, "q_mvar"] = C.TARGET_FEEDER_PEAK_MW * w * tan_phi
    pp.runpp(net_cal, algorithm="nr", init="auto")
    worst_i_ka = float(net_cal.res_line.i_ka.max())
    line_max_i_ka = worst_i_ka / (C.TARGET_UNCOORD_LINE_LOADING_PCT / 100.0)

    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    bw_path = C.JSON_DIR / "bus_weights.json"
    ns_path = C.JSON_DIR / "network_scale.json"
    bw_path.write_text(json.dumps(bus_weights, indent=2), encoding="utf-8")
    ns_path.write_text(
        json.dumps(
            {
                "scale_aggregate_kw_to_feeder_mw": scale_kw_to_mw,
                "target_feeder_peak_mw": C.TARGET_FEEDER_PEAK_MW,
                "native_total_load_mw": total_p,
                "power_factor": C.POWER_FACTOR,
                "n_load_buses": int(len(loads)),
                "line_max_i_ka": line_max_i_ka,
                "uncoordinated_worst_line_i_ka": worst_i_ka,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    script.write_report(
        "network_report",
        artifacts=[script.file_reference(bw_path), script.file_reference(ns_path)],
        summary={
            "benchmark": "ieee_33_bus",
            "n_buses": int(len(net.bus)),
            "n_load_buses": int(len(loads)),
            "native_total_load_mw": total_p,
            "target_feeder_peak_mw": C.TARGET_FEEDER_PEAK_MW,
            "scale_aggregate_kw_to_feeder_mw": scale_kw_to_mw,
            "line_max_i_ka": line_max_i_ka,
        },
    )
    print(f"build_network: IEEE-33, {len(loads)} load buses, scale={scale_kw_to_mw:.6e}")


if __name__ == "__main__":
    main()

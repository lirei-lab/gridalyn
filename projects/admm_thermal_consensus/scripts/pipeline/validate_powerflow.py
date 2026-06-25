"""Stage: validate each coordinated aggregate on the IEEE-33 feeder."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus power-flow validation")
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.artifacts import (
        build_pandapower_summary,
    )
    from gridalyn.simulation.simulators.powerflow.benchmarks import (
        build_ieee33_benchmark_feeder,
    )

    script = project_script()
    profiles = pd.read_parquet(C.DATA_DIR / "aggregate_profiles.parquet")
    bus_weights = {
        int(k): float(v)
        for k, v in json.loads((C.JSON_DIR / "bus_weights.json").read_text()).items()
    }
    network_scale = json.loads((C.JSON_DIR / "network_scale.json").read_text())
    scale = network_scale["scale_aggregate_kw_to_feeder_mw"]
    line_max_i_ka = network_scale["line_max_i_ka"]
    tan_phi = math.tan(math.acos(C.POWER_FACTOR))

    rows = []
    for scenario in profiles.columns:
        agg_kw = profiles[scenario].to_numpy()
        worst_vmin = math.inf
        worst_line = -math.inf
        worst_step = -1
        nonconverged = 0
        for t in range(len(agg_kw)):
            net = build_ieee33_benchmark_feeder()
            net.line["max_i_ka"] = line_max_i_ka
            p_total_mw = agg_kw[t] * scale  # aggregate kW -> feeder MW
            for bus, w in bus_weights.items():
                mask = net.load.bus == bus
                net.load.loc[mask, "p_mw"] = p_total_mw * w
                net.load.loc[mask, "q_mvar"] = p_total_mw * w * tan_phi
            try:
                pp.runpp(net, algorithm="nr", init="auto")
            except Exception:  # noqa: BLE001 - non-convergence is a recorded outcome
                nonconverged += 1
                continue
            summary = build_pandapower_summary(net, network="ieee_33_bus")
            vmin = summary["min_voltage_pu"]
            lmax = summary["max_line_loading_percent"]
            if vmin is not None and vmin < worst_vmin:
                worst_vmin = vmin
            if lmax is not None and lmax > worst_line:
                worst_line = lmax
                worst_step = t
        rows.append(
            {
                "scenario": scenario,
                "feeder_peak_mw": float(agg_kw.max() * scale),
                "worst_min_voltage_pu": None if worst_vmin is math.inf else float(worst_vmin),
                "worst_max_line_loading_pct": None if worst_line == -math.inf else float(worst_line),
                "worst_step": worst_step,
                "voltage_violation": (worst_vmin < C.VOLTAGE_LOWER_PU)
                if worst_vmin is not math.inf
                else None,
                "line_violation": (worst_line > C.LINE_LOADING_LIMIT_PCT)
                if worst_line != -math.inf
                else None,
                "nonconverged_steps": nonconverged,
            }
        )

    feas = pd.DataFrame(rows)
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    feas_path = C.DATA_DIR / "network_feasibility.parquet"
    feas.to_parquet(feas_path)

    script.write_report(
        "powerflow_report",
        artifacts=[script.file_reference(feas_path)],
        summary={
            "scenarios": feas["scenario"].tolist(),
            "uncoordinated_worst_min_voltage_pu": float(
                feas.loc[feas.scenario == "uncoordinated", "worst_min_voltage_pu"].iloc[0]
            ),
            "ideal_worst_min_voltage_pu": float(
                feas.loc[feas.scenario == "coordinated_ideal", "worst_min_voltage_pu"].iloc[0]
            ),
            "uncoordinated_worst_line_loading_pct": float(
                feas.loc[feas.scenario == "uncoordinated", "worst_max_line_loading_pct"].iloc[0]
            ),
            "ideal_worst_line_loading_pct": float(
                feas.loc[feas.scenario == "coordinated_ideal", "worst_max_line_loading_pct"].iloc[0]
            ),
            "voltage_lower_pu": C.VOLTAGE_LOWER_PU,
            "line_loading_limit_pct": C.LINE_LOADING_LIMIT_PCT,
        },
    )
    print("validate_powerflow: scenarios validated:", len(feas))


if __name__ == "__main__":
    main()

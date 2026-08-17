"""Stage: validate each coordinated aggregate on the synthetic LV feeder.

For each scenario the daily aggregate home demand is injected at the LV load
buses and AC power flow is solved at every time step. The binding constraint is
the MV/LV transformer thermal loading (the residential winter-peak limit); LV bus
voltage is reported as a secondary severity measure.
"""

from __future__ import annotations

import math

import pandas as pd

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts import lv_feeder


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus power-flow validation")

    script = project_script()
    profiles = pd.read_parquet(C.DATA_DIR / "aggregate_profiles.parquet")
    net, load_buses = lv_feeder.build_lv_feeder()

    rows = []
    for scenario in profiles.columns:
        agg_kw = profiles[scenario].to_numpy()
        worst_vmin = math.inf
        worst_load = -math.inf
        worst_step = -1
        nonconverged = 0
        for t in range(len(agg_kw)):
            lv_feeder.inject_total(net, load_buses, float(agg_kw[t]))
            try:
                vmin, loading = lv_feeder.solve_metrics(net)
            except Exception:  # noqa: BLE001 - non-convergence is a recorded outcome
                nonconverged += 1
                continue
            if vmin < worst_vmin:
                worst_vmin = vmin
            if loading > worst_load:
                worst_load = loading
                worst_step = t
        rows.append(
            {
                "scenario": scenario,
                "peak_kw": float(agg_kw.max()),
                "worst_min_voltage_pu": (
                    None if worst_vmin is math.inf else float(worst_vmin)
                ),
                "worst_transformer_loading_pct": (
                    None if worst_load == -math.inf else float(worst_load)
                ),
                "worst_step": worst_step,
                "voltage_violation": (
                    (worst_vmin < C.VOLTAGE_LOWER_PU)
                    if worst_vmin is not math.inf
                    else None
                ),
                "transformer_violation": (
                    (worst_load > C.TRANSFORMER_LOADING_LIMIT_PCT)
                    if worst_load != -math.inf
                    else None
                ),
                "nonconverged_steps": nonconverged,
            }
        )

    feas = pd.DataFrame(rows)
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    feas_path = C.DATA_DIR / "network_feasibility.parquet"
    feas.to_parquet(feas_path)

    def _val(scenario, col):
        return float(feas.loc[feas.scenario == scenario, col].iloc[0])

    script.write_report(
        "powerflow_report",
        artifacts=[script.file_reference(feas_path)],
        summary={
            "scenarios": feas["scenario"].tolist(),
            "uncoordinated_worst_transformer_loading_pct": _val(
                "uncoordinated", "worst_transformer_loading_pct"
            ),
            "ideal_worst_transformer_loading_pct": _val(
                "coordinated_ideal", "worst_transformer_loading_pct"
            ),
            "uncoordinated_worst_min_voltage_pu": _val(
                "uncoordinated", "worst_min_voltage_pu"
            ),
            "ideal_worst_min_voltage_pu": _val(
                "coordinated_ideal", "worst_min_voltage_pu"
            ),
            "transformer_loading_limit_pct": C.TRANSFORMER_LOADING_LIMIT_PCT,
            "voltage_lower_pu": C.VOLTAGE_LOWER_PU,
        },
    )
    print("validate_powerflow: scenarios validated:", len(feas))


if __name__ == "__main__":
    main()

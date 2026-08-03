"""Stage: build the synthetic LV residential feeder and record its parameters."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts import lv_feeder


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus power-flow validation")

    script = project_script()
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    uncoordinated_peak_kw = float(params["uncoordinated_peak_kw"])

    # solve the uncoordinated winter peak to report the transformer overload
    net, load_buses = lv_feeder.build_lv_feeder()
    lv_feeder.inject_total(net, load_buses, uncoordinated_peak_kw)
    vmin, loading = lv_feeder.solve_metrics(net)

    bus_fractions = lv_feeder.bus_fractions()
    counts = lv_feeder.home_counts()

    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    bw_path = C.JSON_DIR / "bus_weights.json"
    ns_path = C.JSON_DIR / "network_scale.json"
    bw_path.write_text(
        json.dumps({str(i): f for i, f in enumerate(bus_fractions)}, indent=2),
        encoding="utf-8",
    )
    ns_path.write_text(
        json.dumps(
            {
                "feeder": "synthetic_lv_residential",
                "transformer_kva": C.TRANSFORMER_KVA,
                "mv_kv": C.MV_KV, "lv_kv": C.LV_KV,
                "n_homes": C.N_AGENTS,
                "n_load_buses": C.N_LV_SECTIONS,
                "homes_per_bus": counts,
                "power_factor": C.POWER_FACTOR,
                "uncoordinated_peak_kw": uncoordinated_peak_kw,
                "uncoordinated_transformer_loading_pct": loading,
                "uncoordinated_min_lv_voltage_pu": vmin,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    script.write_report(
        "network_report",
        artifacts=[script.file_reference(bw_path), script.file_reference(ns_path)],
        summary={
            "feeder": "synthetic_lv_residential",
            "transformer_kva": C.TRANSFORMER_KVA,
            "n_homes": C.N_AGENTS,
            "n_load_buses": C.N_LV_SECTIONS,
            "uncoordinated_transformer_loading_pct": loading,
            "uncoordinated_min_lv_voltage_pu": vmin,
        },
    )
    print(
        f"build_network: LV feeder, {C.N_AGENTS} homes on a {C.TRANSFORMER_KVA:.0f} kVA "
        f"transformer; uncoordinated loading {loading:.1f}%, min V {vmin:.3f} pu"
    )


if __name__ == "__main__":
    main()

"""
pandapower_validation.py - Validate the study CLS grid with a custom pandapower network.

Creates a 15 MVA 120/25 kV custom transformer type, builds a minimal network,
and runs power flow for each EV scenario to compare:
  - pandapower static loading (nameplate S_rated)
  - IEEE C57.91 dynamic thermal capacity at winter ambient

Outputs: projects/flexibility_cls/outputs/json/pandapower_validation.json
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pandapower as pp

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import (
    S_RATED_MVA, S_RATED_KVA, THETA_MAX, PF,
    GRID_CONFIG,
)
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from projects.flexibility_cls.scripts.thermal_forecast import (
    build_thermal_forecast,
    thermal_forecast_metadata,
)

DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"
JSON_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "json"
JSON_DIR.mkdir(parents=True, exist_ok=True)


def create_custom_transformer_type(net: pp.pandapowerNet) -> str:
    """Register the 15 MVA 120/25 kV HQ custom type in pandapower."""
    name = f"{S_RATED_MVA:.0f} MVA 120/25 kV HQ"
    params = {
        "sn_mva": S_RATED_MVA,
        "vn_hv_kv": GRID_CONFIG["buses"]["hv"]["voltage_kv"],
        "vn_lv_kv": GRID_CONFIG["buses"]["mv"]["voltage_kv"],
        "vk_percent": 8.5,
        "vkr_percent": 0.45,
        "pfe_kw": 10.0,
        "i0_percent": 0.08,
        "shift_degree": 0,
        "vector_group": "Dyn11",
        "tap_side": "hv",
        "tap_neutral": 0,
        "tap_min": -8,
        "tap_max": 8,
        "tap_step_percent": 1.25,
        "tap_step_degree": 0,
        "tap_pos": 0,
        "tap_phase_shifter": False,
    }
    pp.create_std_type(net, params, name=name, element="trafo")
    return name


def build_network() -> tuple[pp.pandapowerNet, int, int]:
    """Build a minimal network: HV ext_grid → T1 → MV feeder → load."""
    net = pp.create_empty_network(name="TR_CLS_Validation")

    v_hv = GRID_CONFIG["buses"]["hv"]["voltage_kv"]
    v_mv = GRID_CONFIG["buses"]["mv"]["voltage_kv"]

    hv_bus = pp.create_bus(net, vn_kv=v_hv, name="HV_Grid")
    mv_bus = pp.create_bus(net, vn_kv=v_mv, name="MV_Substation")
    load_bus = pp.create_bus(net, vn_kv=v_mv, name="Load_Center")

    pp.create_ext_grid(net, bus=hv_bus, vm_pu=1.02, name="Utility")

    trafo_name = create_custom_transformer_type(net)
    pp.create_transformer(net, hv_bus=hv_bus, lv_bus=mv_bus,
                          std_type=trafo_name, name="T1_CLS")

    pp.create_line_from_parameters(
        net, from_bus=mv_bus, to_bus=load_bus, length_km=4.0,
        r_ohm_per_km=0.1, x_ohm_per_km=0.1, c_nf_per_km=400,
        max_i_ka=0.5, name="Feeder_Study",
    )

    pp.create_load(net, bus=load_bus, p_mw=0.0, q_mvar=0.0, name="Study_Zone")

    return net, 0, load_bus  # trafo_idx, load_bus


def main():
    print("=" * 60)
    print("  Pandapower Validation: Custom Transformer + CLS Scenarios")
    print("=" * 60)

    # Load simulation results
    summary_path = JSON_DIR / "ev_summary_results.json"
    if not summary_path.exists():
        print(f"  ✗ Missing {summary_path.name}, run pipeline first.")
        return
    with open(summary_path) as f:
        ev_summary = json.load(f)

    net, trafo_idx, load_bus = build_network()

    # IEEE C57.91 dynamic model. This scalar is a winter design point for
    # comparing pandapower load-flow results, while the pipeline dispatch uses
    # the full forecast trace exported by build_thermal_forecast().
    thermal = TransformerThermalModel(
        s_rated_kva=S_RATED_KVA,
        theta_max=THETA_MAX,
    )

    # Winter design ambient = -22.5 °C
    T_amb_winter = -22.5
    P_static = S_RATED_MVA * PF          # MW
    P_dynamic_kw = thermal.max_load_for_temp(T_amb_winter, THETA_MAX)
    P_dynamic = P_dynamic_kw / 1000.0    # MW
    K_cold = P_dynamic / P_static
    n_steps = 336
    dispatch_path = DATA_DIR / "market_dispatch_timeseries.parquet"
    if dispatch_path.exists():
        import pandas as pd

        n_steps = len(pd.read_parquet(dispatch_path))
    thermal_forecast = build_thermal_forecast(n_steps)

    print(f"\n  Transformer: {S_RATED_MVA:.0f} MVA, θ_max={THETA_MAX:.0f}°C")
    print(f"  P_static = {P_static:.2f} MW")
    print(f"  K(-22.5°C) = {K_cold:.3f}")
    print(f"  P_dynamic = {P_dynamic:.2f} MW")
    print()

    results = {
        "transformer": {
            "s_rated_mva": S_RATED_MVA,
            "theta_max_c": THETA_MAX,
            "p_static_mw": round(P_static, 2),
            "k_cold": round(K_cold, 3),
            "p_dynamic_mw": round(P_dynamic, 2),
            "dynamic_limit_winter_design_mw": P_dynamic,
            "t_ambient_c": T_amb_winter,
            "dynamic_limit_basis": "winter_design_ambient_fixed",
        },
        "scenarios": [],
    }
    results["transformer"].update(
        thermal_forecast_metadata(
            thermal_forecast,
            winter_design_limit_mw=P_dynamic,
        )
    )

    header = f"{'Scn':>4} {'EV%':>4} {'P_MW':>7} {'Static%':>8} {'Dyn%':>8} {'V_pu':>7} {'Status':>18}"
    print(f"  {header}")
    print(f"  {'─' * len(header)}")

    for label, data in ev_summary.items():
        if not isinstance(data, dict):
            continue  # skip scalar entries like p_rated_mw
        ev_pct_map = {"S0_0pct": 0, "S1_10pct": 10, "S2_20pct": 20, "S3_30pct": 30, "S4_40pct": 40}
        ev_pct = ev_pct_map.get(label, 0)
        p_peak = data.get("unmanaged_peak_mw", 0)

        net.load.at[0, "p_mw"] = p_peak
        net.load.at[0, "q_mvar"] = p_peak * 0.33

        pp.runpp(net)

        static_pct = net.res_trafo.at[trafo_idx, "loading_percent"]
        dynamic_pct = (p_peak / P_dynamic) * 100.0
        v_pu = net.res_bus.at[load_bus, "vm_pu"]

        if dynamic_pct > 100:
            status = "⚡ CONGESTION (dyn)"
        elif static_pct > 100:
            status = "⚠️ Static overload"
        else:
            status = "✓ OK"

        scenario = {
            "label": label,
            "ev_pct": ev_pct,
            "p_peak_mw": float(p_peak),
            "static_loading_pct": round(static_pct, 1),
            "dynamic_loading_pct": round(dynamic_pct, 1),
            "winter_design_loading_pct": round(dynamic_pct, 1),
            "voltage_pu": round(v_pu, 4),
            "converged": bool(net.converged),
            "congested_dynamic": bool(dynamic_pct > 100),
            "congested_winter_design": bool(dynamic_pct > 100),
            "congested_static": bool(static_pct > 100),
        }
        results["scenarios"].append(scenario)

        print(f"  {label:>4} {ev_pct:>3}% {p_peak:>6.2f} {static_pct:>7.1f}% {dynamic_pct:>7.1f}% {v_pu:>6.4f} {status:>18}")

    # Save
    out_path = JSON_DIR / "pandapower_validation.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  ✓ Saved {out_path}")

    # Summary
    n_dyn_congested = sum(1 for s in results["scenarios"] if s["congested_dynamic"])
    n_static_overload = sum(1 for s in results["scenarios"] if s["congested_static"])
    print(f"\n  Summary:")
    print(f"    Scenarios with STATIC overload (>100% nameplate): {n_static_overload}/{len(results['scenarios'])}")
    print(f"    Scenarios with DYNAMIC congestion (>100% IEEE):   {n_dyn_congested}/{len(results['scenarios'])}")
    print(f"    This confirms the transformer operates within IEEE C57.91")
    print(f"    dynamic limits at winter ambient until EV penetration")
    print(f"    pushes load beyond P_dynamic = {P_dynamic:.1f} MW.")


if __name__ == "__main__":
    main()

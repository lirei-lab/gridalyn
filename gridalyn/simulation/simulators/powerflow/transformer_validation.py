"""Pandapower transformer peak-loading validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandapower as pp

from gridalyn.assets.modeling.transformers import TransformerThermalModel


_SCENARIO_RE = re.compile(r"^S\d+_(\d+)pct$")


@dataclass(frozen=True)
class TransformerPeakValidationConfig:
    """Parameters for a compact transformer peak-loading validation network."""

    s_rated_mva: float
    s_rated_kva: float
    theta_max_c: float
    power_factor: float
    hv_voltage_kv: float
    mv_voltage_kv: float
    winter_design_ambient_c: float = -22.5
    ext_grid_vm_pu: float = 1.02
    load_q_to_p_ratio: float = 0.33
    feeder_length_km: float = 4.0
    feeder_r_ohm_per_km: float = 0.1
    feeder_x_ohm_per_km: float = 0.1
    feeder_c_nf_per_km: float = 400.0
    feeder_max_i_ka: float = 0.5


def create_transformer_peak_validation_network(
    config: TransformerPeakValidationConfig,
) -> tuple[pp.pandapowerNet, int, int]:
    """Build a minimal HV-transformer-MV-load pandapower network."""
    net = pp.create_empty_network(name="TransformerPeakValidation")
    hv_bus = pp.create_bus(net, vn_kv=config.hv_voltage_kv, name="HV_Grid")
    mv_bus = pp.create_bus(net, vn_kv=config.mv_voltage_kv, name="MV_Substation")
    load_bus = pp.create_bus(net, vn_kv=config.mv_voltage_kv, name="Load_Center")

    pp.create_ext_grid(net, bus=hv_bus, vm_pu=config.ext_grid_vm_pu, name="Utility")
    trafo_name = register_transformer_peak_validation_type(net, config)
    trafo_idx = pp.create_transformer(
        net,
        hv_bus=hv_bus,
        lv_bus=mv_bus,
        std_type=trafo_name,
        name="T1_Validation",
    )
    pp.create_line_from_parameters(
        net,
        from_bus=mv_bus,
        to_bus=load_bus,
        length_km=config.feeder_length_km,
        r_ohm_per_km=config.feeder_r_ohm_per_km,
        x_ohm_per_km=config.feeder_x_ohm_per_km,
        c_nf_per_km=config.feeder_c_nf_per_km,
        max_i_ka=config.feeder_max_i_ka,
        name="Feeder_Study",
    )
    pp.create_load(net, bus=load_bus, p_mw=0.0, q_mvar=0.0, name="Study_Zone")
    return net, int(trafo_idx), int(load_bus)


def register_transformer_peak_validation_type(
    net: pp.pandapowerNet,
    config: TransformerPeakValidationConfig,
) -> str:
    """Register a transformer type for peak-loading validation."""
    name = f"{config.s_rated_mva:.0f} MVA {config.hv_voltage_kv:g}/{config.mv_voltage_kv:g} kV"
    params = {
        "sn_mva": config.s_rated_mva,
        "vn_hv_kv": config.hv_voltage_kv,
        "vn_lv_kv": config.mv_voltage_kv,
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


def validate_transformer_peak_scenarios(
    *,
    scenarios: dict[str, dict[str, Any]],
    config: TransformerPeakValidationConfig,
) -> dict[str, Any]:
    """Run pandapower peak-loading checks for unmanaged scenario peaks."""
    net, trafo_idx, load_bus = create_transformer_peak_validation_network(config)
    thermal = TransformerThermalModel(
        s_rated_kva=config.s_rated_kva,
        theta_max=config.theta_max_c,
    )
    p_static_mw = config.s_rated_mva * config.power_factor
    p_dynamic_mw = (
        thermal.max_load_for_temp(
            config.winter_design_ambient_c,
            config.theta_max_c,
        )
        / 1000.0
    )
    k_cold = p_dynamic_mw / p_static_mw

    results = {
        "transformer": {
            "s_rated_mva": config.s_rated_mva,
            "theta_max_c": config.theta_max_c,
            "p_static_mw": round(p_static_mw, 2),
            "k_cold": round(k_cold, 3),
            "p_dynamic_mw": round(p_dynamic_mw, 2),
            "dynamic_limit_winter_design_mw": p_dynamic_mw,
            "t_ambient_c": config.winter_design_ambient_c,
            "dynamic_limit_basis": "winter_design_ambient_fixed",
        },
        "scenarios": [],
    }

    for label, data in scenarios.items():
        p_peak_mw = float(data.get("unmanaged_peak_mw", 0.0))
        net.load.at[0, "p_mw"] = p_peak_mw
        net.load.at[0, "q_mvar"] = p_peak_mw * config.load_q_to_p_ratio
        pp.runpp(net)

        static_pct = float(net.res_trafo.at[trafo_idx, "loading_percent"])
        dynamic_pct = (p_peak_mw / p_dynamic_mw) * 100.0 if p_dynamic_mw > 0 else 0.0
        scenario = {
            "label": label,
            "ev_pct": _ev_percent_from_label(label),
            "p_peak_mw": p_peak_mw,
            "static_loading_pct": round(static_pct, 1),
            "dynamic_loading_pct": round(dynamic_pct, 1),
            "winter_design_loading_pct": round(dynamic_pct, 1),
            "voltage_pu": round(float(net.res_bus.at[load_bus, "vm_pu"]), 4),
            "converged": bool(net.converged),
            "congested_dynamic": bool(dynamic_pct > 100.0),
            "congested_winter_design": bool(dynamic_pct > 100.0),
            "congested_static": bool(static_pct > 100.0),
        }
        results["scenarios"].append(scenario)

    return results


def _ev_percent_from_label(label: str) -> int:
    match = _SCENARIO_RE.match(label)
    return int(match.group(1)) if match else 0


__all__ = [
    "TransformerPeakValidationConfig",
    "create_transformer_peak_validation_network",
    "register_transformer_peak_validation_type",
    "validate_transformer_peak_scenarios",
]

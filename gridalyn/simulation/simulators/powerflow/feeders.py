"""Pandapower builders for Gridalyn feeder asset contracts."""

from __future__ import annotations

import pandapower as pp

from gridalyn.assets.modeling.feeders import (
    RadialFeederSpec,
    validate_radial_feeder_spec,
)


def build_radial_pandapower_feeder(spec: RadialFeederSpec) -> pp.pandapowerNet:
    """Build a simple radial pandapower feeder from a stable Gridalyn spec."""
    validate_radial_feeder_spec(spec)
    net = pp.create_empty_network(sn_mva=float(spec.sn_mva))
    for bus_id in range(spec.bus_count):
        pp.create_bus(
            net,
            vn_kv=float(spec.base_voltage_kv),
            name=f"bus_{bus_id:02d}",
            geodata=(float(bus_id), float(spec.bus_y_step) * float(bus_id % 3)),
        )
    pp.create_ext_grid(net, bus=0, vm_pu=float(spec.slack_vm_pu), name="grid_connection")

    for from_bus, to_bus in zip(
        range(spec.bus_count - 1),
        range(1, spec.bus_count),
        strict=True,
    ):
        pp.create_line_from_parameters(
            net,
            from_bus=from_bus,
            to_bus=to_bus,
            length_km=float(spec.line_lengths_km.get(to_bus, spec.line_length_km)),
            r_ohm_per_km=float(spec.line_r_ohm_per_km),
            x_ohm_per_km=float(spec.line_x_ohm_per_km),
            c_nf_per_km=float(spec.line_c_nf_per_km),
            max_i_ka=float(spec.line_max_i_ka),
            name=f"line_{from_bus:02d}_{to_bus:02d}",
        )

    for bus_id, p_mw in sorted(spec.loads_mw.items()):
        pp.create_load(
            net,
            bus=int(bus_id),
            p_mw=float(p_mw),
            q_mvar=float(p_mw) * float(spec.q_to_p_ratio),
            name=f"load_bus_{int(bus_id):02d}",
        )
    return net


__all__ = ["build_radial_pandapower_feeder"]

"""Reusable feeder constructors for compact study and demo networks."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandapower as pp


@dataclass(frozen=True)
class RadialFeederSpec:
    """Deterministic radial feeder contract backed by pandapower."""

    name: str
    bus_count: int
    sn_mva: float
    base_voltage_kv: float
    slack_vm_pu: float
    loads_mw: dict[int, float]
    q_to_p_ratio: float = 0.30
    line_length_km: float = 0.5
    line_r_ohm_per_km: float = 0.5
    line_x_ohm_per_km: float = 0.3
    line_c_nf_per_km: float = 5.0
    line_max_i_ka: float = 0.2
    line_lengths_km: dict[int, float] = field(default_factory=dict)
    bus_y_step: float = 0.2
    metadata: dict[str, str] = field(default_factory=dict)


def build_radial_pandapower_feeder(spec: RadialFeederSpec) -> pp.pandapowerNet:
    """Build a simple radial pandapower feeder from a stable Gridalyn spec."""
    _validate_radial_feeder_spec(spec)
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


def _validate_radial_feeder_spec(spec: RadialFeederSpec) -> None:
    if spec.bus_count < 2:
        raise ValueError("RadialFeederSpec.bus_count must be at least 2")
    if 0 in spec.loads_mw:
        raise ValueError("loads_mw must not attach load to slack bus 0")
    invalid_buses = sorted(
        bus_id for bus_id in spec.loads_mw if bus_id < 0 or bus_id >= spec.bus_count
    )
    if invalid_buses:
        raise ValueError(f"loads_mw contains buses outside feeder range: {invalid_buses}")
    if spec.sn_mva <= 0:
        raise ValueError("RadialFeederSpec.sn_mva must be positive")
    if spec.base_voltage_kv <= 0:
        raise ValueError("RadialFeederSpec.base_voltage_kv must be positive")

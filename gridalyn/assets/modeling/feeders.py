"""Reusable feeder constructors for compact study and demo networks."""

from __future__ import annotations

from dataclasses import dataclass, field


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


def validate_radial_feeder_spec(spec: RadialFeederSpec) -> None:
    """Validate a radial feeder asset-model contract."""
    if spec.bus_count < 2:
        raise ValueError("RadialFeederSpec.bus_count must be at least 2")
    if 0 in spec.loads_mw:
        raise ValueError("loads_mw must not attach load to slack bus 0")
    invalid_buses = sorted(
        bus_id for bus_id in spec.loads_mw if bus_id < 0 or bus_id >= spec.bus_count
    )
    if invalid_buses:
        raise ValueError(
            f"loads_mw contains buses outside feeder range: {invalid_buses}"
        )
    if spec.sn_mva <= 0:
        raise ValueError("RadialFeederSpec.sn_mva must be positive")
    if spec.base_voltage_kv <= 0:
        raise ValueError("RadialFeederSpec.base_voltage_kv must be positive")


def lv_feeder_spec(
    *,
    name: str,
    bus_count: int,
    sn_mva: float,
    base_voltage_kv: float,
    loads_mw: dict[int, float],
    slack_vm_pu: float = 1.0,
    line_max_i_ka: float = 0.2,
    line_length_km: float = 0.05,
    q_to_p_ratio: float = 0.30,
) -> RadialFeederSpec:
    """Build a compact LV-feeder ``RadialFeederSpec``.

    Constructs a deterministic radial LV feeder contract: a head transformer
    (``sn_mva`` at ``base_voltage_kv``) feeding the declared per-bus ``loads_mw``
    over short LV lines (default 50 m, ``line_max_i_ka=0.2``). The result passes
    :func:`validate_radial_feeder_spec` and is deterministic for fixed inputs, so
    a study can rebuild an LV feeder without bespoke network construction.

    The name is deliberately a *spec* constructor (``lv_feeder_spec``), not a
    ``build_*`` network builder: it returns a :class:`RadialFeederSpec` contract,
    and a net is built from it later via the power-flow builder. This also avoids
    colliding with study-local ``build_lv_feeder`` functions that construct a net
    (e.g. ``admm_thermal_consensus/scripts/lv_feeder.py``).

    Args:
        name: Feeder name for the spec.
        bus_count: Number of buses (slack + LV buses); at least 2.
        sn_mva: Head transformer rating in MVA.
        base_voltage_kv: LV nominal voltage in kV.
        loads_mw: Per-bus load in MW keyed by bus index (never bus 0, the slack).
        slack_vm_pu: Slack voltage in per unit.
        line_max_i_ka: LV line continuous rating in kA.
        line_length_km: LV line length in km.
        q_to_p_ratio: Reactive-to-active load ratio.

    Returns:
        A frozen ``RadialFeederSpec`` variant.

    Raises:
        ValueError: If the resulting spec is invalid (delegates to
            :func:`validate_radial_feeder_spec`).
    """
    spec = RadialFeederSpec(
        name=name,
        bus_count=bus_count,
        sn_mva=sn_mva,
        base_voltage_kv=base_voltage_kv,
        slack_vm_pu=slack_vm_pu,
        loads_mw=dict(loads_mw),
        q_to_p_ratio=q_to_p_ratio,
        line_length_km=line_length_km,
        line_max_i_ka=line_max_i_ka,
        metadata={"builder": "lv_feeder_spec", "class": "lv"},
    )
    validate_radial_feeder_spec(spec)
    return spec


__all__ = [
    "RadialFeederSpec",
    "lv_feeder_spec",
    "validate_radial_feeder_spec",
]

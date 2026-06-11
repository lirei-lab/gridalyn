"""Project bindings for the Gridalyn RL voltage-control demo model."""

from __future__ import annotations

from gridalyn.projects import (
    load_generated_load_multipliers,
    load_numeric_profile_array,
    load_radial_feeder_spec,
    load_voltage_control_der_spec,
    project_input,
)
from gridalyn.simulation import VoltageControlEnvironmentSpec, build_voltage_control_feeder


FEEDER_SPEC = load_radial_feeder_spec("project.yaml")
DER_SPEC = load_voltage_control_der_spec("project.yaml", feeder=FEEDER_SPEC)
BASE_LOADS_MW = FEEDER_SPEC.loads_mw
BATTERY_BUS = DER_SPEC.battery_bus_id
PV_BUS = DER_SPEC.pv_bus_id
PV_MAX_MW = DER_SPEC.pv_capacity_mw
BATTERY_POWER_MW = DER_SPEC.battery.power_mw
BATTERY_CAPACITY_MWH = DER_SPEC.battery.capacity_mwh
INITIAL_SOC_MWH = DER_SPEC.battery.initial_soc_mwh
MIN_SOC_MWH = DER_SPEC.battery.min_soc_mwh
MAX_SOC_MWH = DER_SPEC.max_soc_mwh


def build_rl_feeder():
    """Create the project feeder declared in project.yaml."""
    return build_voltage_control_feeder(FEEDER_SPEC, DER_SPEC)


def build_rl_environment_spec():
    """Create the voltage-control environment declared in project.yaml."""
    environment = project_input("project.yaml", "environment")
    return VoltageControlEnvironmentSpec(
        feeder=FEEDER_SPEC,
        der=DER_SPEC,
        load_multiplier_profile=load_multiplier_profile(),
        pv_profile=pv_profile(),
        timestep_hours=float(environment.get("timestepHours", 0.25)),
        voltage_target_pu=float(environment.get("voltageTargetPu", 1.01)),
        voltage_low_pu=float(environment.get("voltageLowPu", 0.98)),
        voltage_high_pu=float(environment.get("voltageHighPu", 1.04)),
    )


def load_multiplier_profile():
    """Return the generated load multiplier profile declared in project.yaml."""
    return load_generated_load_multipliers("project.yaml")


def pv_profile():
    """Return the PV profile declared in project.yaml."""
    return load_numeric_profile_array("project.yaml", "pvProfile")


__all__ = [
    "BASE_LOADS_MW",
    "BATTERY_BUS",
    "BATTERY_CAPACITY_MWH",
    "BATTERY_POWER_MW",
    "DER_SPEC",
    "FEEDER_SPEC",
    "INITIAL_SOC_MWH",
    "MAX_SOC_MWH",
    "MIN_SOC_MWH",
    "PV_BUS",
    "PV_MAX_MW",
    "build_rl_environment_spec",
    "build_rl_feeder",
    "load_multiplier_profile",
    "pv_profile",
]

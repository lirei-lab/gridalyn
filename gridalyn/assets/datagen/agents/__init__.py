"""Synthetic building, hot-water and EV agents used by data-generation workflows.

Two distinct kinds of agent live here:

* **Actuators** carry state and respond to control signals — :class:`EVCharger`
  tracks state of charge and honours a curtailment cap. Use them for control
  and market studies.
* **Profile generators** answer "what does a population draw?" in one call —
  :func:`make_cold_coupled_ev_fleet`, :func:`make_dhw_tank_fleet`. Use them to
  build realistic baseline load.

Do not use an actuator as a stand-in for a generator: :class:`EVCharger`
spreads each session evenly over the plugged window, which pre-flattens the
peak a flexibility study is trying to measure.
"""

from gridalyn.assets.datagen.agents.buildings import Building
from gridalyn.assets.datagen.agents.dhw import (
    DHWDrawProfile,
    DHWTankParams,
    dhw_draw_profile,
    make_dhw_tank_fleet,
)
from gridalyn.assets.datagen.agents.ev import (
    CHARGER_MIX_L2,
    L2_MID_KW,
    EVCharger,
    make_cold_coupled_ev_fleet,
    make_ev_chargers,
)
from gridalyn.assets.datagen.agents.fleet import make_buildings, simulate_buildings

__all__ = [
    "Building",
    "CHARGER_MIX_L2",
    "DHWDrawProfile",
    "DHWTankParams",
    "EVCharger",
    "L2_MID_KW",
    "dhw_draw_profile",
    "make_buildings",
    "make_cold_coupled_ev_fleet",
    "make_dhw_tank_fleet",
    "make_ev_chargers",
    "simulate_buildings",
]

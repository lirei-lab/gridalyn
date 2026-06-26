"""Shared helpers for the comfort-aware (indoor-temperature) coordination.

The coordinator penalizes each home's modelled indoor-temperature excursion --
the deviation from the trajectory the thermostat would hold -- rather than only
its energy deviation. These helpers load the per-home RC parameters exported by
``generate_agents`` and build the precomputed prox inverse (passed to the ADMM
solver) and the temperature-response operators (used to report excursions).
"""

from __future__ import annotations

import json

import numpy as np

from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts.admm.consensus import (
    build_comfort_prox_inverse,
    rc_response_matrix,
)


def thermal_params() -> tuple[np.ndarray, np.ndarray]:
    """Return per-home ``(R, C)`` thermal resistance and capacitance arrays."""
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    resistance = np.asarray(params["thermal_resistance_c_per_kw"], dtype=float)
    capacitance = np.asarray(params["thermal_capacitance_kwh_per_c"], dtype=float)
    return resistance, capacitance


def prox_inverse() -> np.ndarray:
    """Build the comfort-penalty prox inverse for the configured ``COMFORT_GAMMA``."""
    resistance, capacitance = thermal_params()
    return build_comfort_prox_inverse(
        resistance, capacitance, C.STEP_HOURS, C.N_STEPS,
        C.COMFORT_GAMMA, C.ADMM_LAMBDA, C.ADMM_RHO,
    )


def temperature_excursion(schedule: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """Per-home peak indoor-temperature excursion (deg C) of a heating schedule.

    For each home, propagate ``schedule - baseline`` through its RC response and
    return the worst-of-day absolute indoor-temperature deviation.
    """
    resistance, capacitance = thermal_params()
    n_agents = schedule.shape[0]
    out = np.empty(n_agents)
    for i in range(n_agents):
        g_mat = rc_response_matrix(
            float(resistance[i]), float(capacitance[i]), C.STEP_HOURS, C.N_STEPS
        )
        out[i] = float(np.abs(g_mat @ (schedule[i] - baseline[i])).max())
    return out

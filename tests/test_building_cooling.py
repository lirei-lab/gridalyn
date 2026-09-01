"""Cooling must remove heat, under every control mode.

The zone branch used for ``control="hysteresis"`` -- the mode both heavy
studies run -- advanced its state with a heating term only. The air conditioner
was computed, reported in ``p_total_kw`` and billed, and removed no heat, so it
never satisfied its own thermostat and latched open-loop on outdoor
temperature. These assertions are mode-agnostic on purpose: the defect was
present in exactly one branch, and a test that only exercised the default would
not have seen it.
"""

from __future__ import annotations

import unittest

import numpy as np

from gridalyn.assets.datagen.agents.buildings import ETA_COOL, ETA_HEAT, Building

CONTROLS = ("proportional", "hysteresis")


def _hot_run(control: str, p_cool_max: float, t_out: float = 32.0, hours: int = 8):
    """Hold a building at ``t_out`` and return (final T_in, cooling kWh)."""
    building = Building(unit_id=0, rng=np.random.default_rng(7))
    building.p_cool_max = p_cool_max
    building.T_in = t_out
    building.zone_T = np.full_like(building.zone_T, t_out)
    energy = 0.0
    for minute in range(hours * 60):
        result = building.step(
            t_out=t_out,
            minute_of_day=float(minute % 1440),
            p_bg_kw=1.0,
            dt_min=1.0,
            control=control,
        )
        energy += result["p_cool_kw"] / 60.0
    return building.T_in, energy


class TestCoolingRemovesHeat(unittest.TestCase):
    def test_cooling_lowers_indoor_temperature_in_every_control_mode(self) -> None:
        """The assertion that would have caught the defect."""
        for control in CONTROLS:
            with self.subTest(control=control):
                without, _ = _hot_run(control, 0.0)
                with_ac, energy = _hot_run(control, 3.0)
                self.assertGreater(
                    energy, 0.0, "the air conditioner must actually run here"
                )
                self.assertLess(
                    with_ac,
                    without - 1.0,
                    f"{control}: cooling draws {energy:.2f} kWh and leaves "
                    "indoor temperature unchanged -- it is billed but removes "
                    "no heat",
                )

    def test_the_two_control_modes_agree_on_cooling_physics(self) -> None:
        """They differ in HEATING control; cooling is the same physics."""
        prop_t, prop_e = _hot_run("proportional", 3.0)
        hyst_t, hyst_e = _hot_run("hysteresis", 3.0)
        self.assertAlmostEqual(prop_t, hyst_t, places=6)
        self.assertAlmostEqual(prop_e, hyst_e, places=6)

    def test_cooling_settles_near_its_setpoint_rather_than_latching(self) -> None:
        """An A/C that removes no heat never satisfies its own thermostat."""
        from gridalyn.assets.datagen.agents.buildings import T_COOL_SET

        for control in CONTROLS:
            with self.subTest(control=control):
                final, _ = _hot_run(control, 3.0)
                self.assertLess(final, T_COOL_SET + 2.0)


class TestIntegratorIsHonoured(unittest.TestCase):
    def test_exact_is_not_a_silent_no_op_in_any_control_mode(self) -> None:
        """``integrator`` was validated and then ignored on the zone branch."""
        for control in CONTROLS:
            with self.subTest(control=control):
                paths = {}
                for integrator in ("euler", "exact"):
                    building = Building(unit_id=5, rng=np.random.default_rng(3))
                    building.T_in = 21.0
                    building.zone_T = np.full_like(building.zone_T, 21.0)
                    for minute in range(360):
                        building.step(
                            t_out=-20.0,
                            minute_of_day=float(minute % 1440),
                            p_bg_kw=1.0,
                            dt_min=1.0,
                            integrator=integrator,
                            control=control,
                        )
                    paths[integrator] = building.T_in
                self.assertNotEqual(
                    paths["euler"],
                    paths["exact"],
                    f"{control}: integrator='exact' produced the Euler answer, "
                    "so the argument is being ignored",
                )

    #: Agreement after a full day at dt = 1 min. The smooth controller is pure
    #: integration error; the latching one is larger by three orders of
    #: magnitude because a zone that flips one step earlier separates the two
    #: trajectories discretely. Both are far below any physical significance,
    #: and both are bounds on a MEASURED value (7.2e-5 K and 0.081 K), not
    #: round numbers chosen to pass.
    INTEGRATOR_AGREEMENT_K = {"proportional": 0.001, "hysteresis": 0.25}

    def test_the_two_integrators_stay_close_at_the_production_step(self) -> None:
        """dt = 1 min sits ~3 orders of magnitude inside Euler's stability limit."""
        for control in CONTROLS:
            with self.subTest(control=control):
                ends = []
                for integrator in ("euler", "exact"):
                    building = Building(unit_id=5, rng=np.random.default_rng(3))
                    building.T_in = 21.0
                    building.zone_T = np.full_like(building.zone_T, 21.0)
                    for minute in range(1440):
                        building.step(
                            t_out=-20.0,
                            minute_of_day=float(minute % 1440),
                            p_bg_kw=1.0,
                            dt_min=1.0,
                            integrator=integrator,
                            control=control,
                        )
                    ends.append(building.T_in)
                self.assertLess(
                    abs(ends[0] - ends[1]),
                    self.INTEGRATOR_AGREEMENT_K[control],
                )


class TestZoneDecompositionStaysExact(unittest.TestCase):
    def test_zones_reproduce_the_whole_house_lumped_parameters(self) -> None:
        """Adding cooling per zone must not break the parallel decomposition."""
        building = Building(unit_id=0, rng=np.random.default_rng(11))
        share = building.zone_share
        self.assertAlmostEqual(float(np.sum(building.C * share)), building.C)
        self.assertAlmostEqual(
            float(np.sum(1.0 / (building.R / share))), 1.0 / building.R
        )
        self.assertAlmostEqual(float(np.sum(share)), 1.0)

    def test_cooling_term_matches_the_whole_house_form(self) -> None:
        """(1/c_z)*p_cool_z reduces to p_cool/C, as heating does."""
        building = Building(unit_id=0, rng=np.random.default_rng(11))
        share = building.zone_share
        p_cool = 2.5
        per_zone = (p_cool * share) / (building.C * share)
        self.assertTrue(
            np.allclose(per_zone, p_cool / building.C),
            "the per-zone cooling term must equal the whole-house term",
        )
        self.assertGreater(ETA_COOL, ETA_HEAT, "cooling carries a COP above 1")


if __name__ == "__main__":
    unittest.main()

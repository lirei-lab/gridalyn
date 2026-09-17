"""Gate for the dwelling archetype seam (bd irz).

``Building`` sampled its physical parameters from module constants and declared
them ``field(init=False)``, so a study calibrated to a different dwelling had no
way to state one: ``ev_hosting_flex`` built its fleet and then overwrote
``building.R`` and ``building.p_heat_max`` on every object. :class:`ThermalArchetype`
is the seam that removes the need to.

The load-bearing property is not that the seam exists but that it moves nothing:
this module's own baselines, and two studies', are frozen against the sampling
that was there before. Two tests carry that weight -- the default archetype must
reproduce the old draw sequence exactly, and the study's declared archetype must
equal what overwriting produced, attribute for attribute, including the ones it
never touched.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.agents import DEFAULT_ARCHETYPE, Building, ThermalArchetype
from gridalyn.assets.datagen.agents import buildings as building_module
from gridalyn.assets.datagen.agents import make_buildings
from gridalyn.assets.datagen.core import GridLoadFacade

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every parameter a dwelling samples, in the order ``__post_init__`` draws it.
_SAMPLED = (
    "R",
    "C",
    "p_heat_max",
    "p_cool_max",
    "bg_mean",
    "bg_std",
    "occupancy_offset_min",
    "T_in",
)


def _state(building: Building) -> tuple:
    return tuple(getattr(building, name) for name in _SAMPLED)


def _sampled_from_constants(unit_id: int, seed: int) -> tuple:
    """Replay the draw sequence as it stood before the archetype existed.

    Written against the module constants rather than the archetype, so it fails
    if a future change re-parameterises the defaults instead of the sampler.
    """
    module = building_module
    rng = np.random.default_rng(seed + unit_id)
    r = float(rng.normal(module.R_MEAN, module.R_STD))
    c = float(rng.normal(module.C_MEAN, module.C_STD))
    r = max(r, module.R_MEAN * 0.3)
    c = max(c, module.C_MEAN * 0.3)
    p_heat = float(rng.uniform(module.P_HEAT_MAX_KW * 0.4, module.P_HEAT_MAX_KW))
    p_cool = float(rng.uniform(module.P_COOL_MAX_KW * 0.4, module.P_COOL_MAX_KW))
    bg_mean = max(
        float(rng.normal(module.BG_MEAN_KW, module.BG_STD_KW)), module.BG_MEAN_KW * 0.3
    )
    bg_std = max(
        float(rng.normal(module.BG_STD_KW, module.BG_STD_KW * 0.1)),
        module.BG_STD_KW * 0.3,
    )
    occupancy = int(rng.integers(-30, 31))
    t_in = float(rng.uniform(17.0, 25.0))
    return (r, c, p_heat, p_cool, bg_mean, bg_std, occupancy, t_in)


class DefaultArchetypeChangesNothingTest(unittest.TestCase):
    """The default must be the old behaviour, draw for draw."""

    def test_the_default_reproduces_the_module_constants(self):
        for building in make_buildings(32, seed=42):
            with self.subTest(unit_id=building.unit_id):
                self.assertEqual(
                    _state(building), _sampled_from_constants(building.unit_id, 42)
                )

    def test_the_default_archetype_carries_the_module_constants(self):
        self.assertEqual(DEFAULT_ARCHETYPE.r_mean, building_module.R_MEAN)
        self.assertEqual(DEFAULT_ARCHETYPE.r_std, building_module.R_STD)
        self.assertEqual(DEFAULT_ARCHETYPE.p_heat_max_kw, building_module.P_HEAT_MAX_KW)
        self.assertEqual(DEFAULT_ARCHETYPE.bg_mean_kw, building_module.BG_MEAN_KW)

    def test_an_unstated_archetype_is_the_default(self):
        self.assertIs(Building(unit_id=0).archetype, DEFAULT_ARCHETYPE)


class DeclaringEqualsOverwritingTest(unittest.TestCase):
    """The migration a study can make without moving a pin."""

    R_FIXED = 7.5
    P_HEAT_FIXED = 13.0

    def _declared(self) -> list[Building]:
        return make_buildings(
            32,
            seed=42,
            archetype=ThermalArchetype(
                r_mean=self.R_FIXED,
                r_std=0.0,
                p_heat_max_kw=self.P_HEAT_FIXED,
                p_heat_fraction_min=1.0,
            ),
        )

    def _overwritten(self) -> list[Building]:
        buildings = make_buildings(32, seed=42)
        for building in buildings:
            building.R = self.R_FIXED
            building.p_heat_max = self.P_HEAT_FIXED
        return buildings

    def test_every_sampled_parameter_matches_the_overwrite(self):
        for declared, overwritten in zip(
            self._declared(), self._overwritten(), strict=True
        ):
            with self.subTest(unit_id=declared.unit_id):
                self.assertEqual(_state(declared), _state(overwritten))

    def test_the_pinned_parameters_are_pinned(self):
        for building in self._declared():
            with self.subTest(unit_id=building.unit_id):
                self.assertEqual(building.R, self.R_FIXED)
                self.assertEqual(building.p_heat_max, self.P_HEAT_FIXED)

    def test_pinning_still_consumes_its_draw(self):
        """Why the equality above holds: the stream is not shifted.

        A fixed parameter implemented by skipping the draw would leave every
        later value different -- which is the silent baseline move this seam
        exists to avoid.
        """
        pinned = make_buildings(4, seed=7, archetype=ThermalArchetype(r_std=0.0))
        default = make_buildings(4, seed=7)

        for one, other in zip(pinned, default, strict=True):
            with self.subTest(unit_id=one.unit_id):
                self.assertNotEqual(one.R, other.R, "r_std=0 pins R")
                self.assertEqual(one.C, other.C, "later draws must be untouched")
                self.assertEqual(one.T_in, other.T_in)


class ArchetypeValidationTest(unittest.TestCase):
    """A parameter set the sampler cannot honour is refused at construction."""

    def test_a_negative_spread_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            ThermalArchetype(r_std=-1.0)
        self.assertIn("r_std", str(caught.exception))

    def test_a_fraction_above_one_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            ThermalArchetype(p_heat_fraction_min=1.5)
        self.assertIn("p_heat_fraction_min", str(caught.exception))

    def test_a_zero_fraction_is_refused(self):
        with self.assertRaises(ValueError):
            ThermalArchetype(floor_fraction=0.0)


class FacadeRoutingTest(unittest.TestCase):
    """The facade routes two engines; only one has an envelope to state."""

    def _weather(self) -> pd.Series:
        index = pd.date_range("2024-01-01", periods=180, freq="1min")
        return pd.Series(np.full(len(index), -20.0), index=index)

    def test_the_parametric_engine_refuses_an_archetype(self):
        with self.assertRaises(ValueError) as caught:
            GridLoadFacade.generate_loads(
                "parametric",
                self._weather(),
                n_houses=2,
                resolution_minutes=15,
                seed=1,
                archetype=ThermalArchetype(),
            )
        message = str(caught.exception)
        self.assertIn("thermodynamic", message)
        self.assertIn("archetype", message)

    def test_the_thermodynamic_engine_takes_one(self):
        heat, background = GridLoadFacade.generate_loads(
            "thermodynamic",
            self._weather(),
            n_houses=2,
            resolution_minutes=15,
            seed=1,
            archetype=ThermalArchetype(r_mean=7.0, r_std=0.0, p_heat_max_kw=13.0),
        )

        self.assertEqual(heat.shape[1], 2)
        self.assertEqual(background.shape, heat.shape)
        self.assertTrue(heat.max() > 0.0, "a -20 C day must draw heat")


class StudyStatesItsArchetypeTest(unittest.TestCase):
    """The flagship study must not go back to overwriting constructed objects.

    The seam is only worth having if its consumer uses it; without this the
    study could quietly revert to mutation and every test above would still
    pass.
    """

    SCRIPTS = _REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts"

    def test_no_study_script_overwrites_a_sampled_parameter(self):
        offenders: list[str] = []
        for path in sorted(self.SCRIPTS.rglob("*.py")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for attribute in (".R = ", ".p_heat_max = ", ".C = "):
                    if attribute in stripped and "archetype" not in stripped:
                        offenders.append(
                            f"{path.relative_to(_REPO_ROOT)}:{number}: {stripped}"
                        )

        self.assertEqual(
            [],
            offenders,
            "state a ThermalArchetype instead of overwriting a constructed dwelling",
        )

    def test_the_study_archetype_pins_what_it_used_to_overwrite(self):
        import sys

        if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - import shim
            sys.path.insert(0, str(_REPO_ROOT))
        from projects.ev_hosting_flex.scripts.config import (
            P_HEAT_QUEBEC,
            R_STUDY_B,
            build_study_thermal_archetype,
        )

        archetype = build_study_thermal_archetype()

        self.assertEqual(archetype.r_mean, R_STUDY_B)
        self.assertEqual(archetype.r_std, 0.0)
        self.assertEqual(archetype.p_heat_max_kw, P_HEAT_QUEBEC)
        self.assertEqual(archetype.p_heat_fraction_min, 1.0)


if __name__ == "__main__":
    unittest.main()

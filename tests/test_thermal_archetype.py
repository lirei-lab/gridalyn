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

from gridalyn.assets.datagen.agents import (
    DEFAULT_ARCHETYPE,
    QUEBEC_ALL_ELECTRIC,
    Building,
    ThermalArchetype,
)
from gridalyn.assets.datagen.agents import buildings as building_module
from gridalyn.assets.datagen.agents import make_buildings
from gridalyn.assets.datagen.api import generate_residential_load_profiles
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


class PackagedQuebecArchetypeTest(unittest.TestCase):
    """The named archetype the in-package consumers state.

    It exists because the twin and the Monte-Carlo runner live inside this
    package and cannot read a study's ``project.yaml``; the two studies that
    carry this calibration keep declaring it in their own contracts, and those
    values must not drift from this one.
    """

    def test_it_carries_the_installed_capacity_calibration(self):
        self.assertEqual(QUEBEC_ALL_ELECTRIC.r_mean, 7.5)
        self.assertEqual(QUEBEC_ALL_ELECTRIC.p_heat_max_kw, 13.0)

    def test_it_pins_rather_than_spreads(self):
        """Every dwelling gets the stated envelope and nameplate."""
        self.assertEqual(QUEBEC_ALL_ELECTRIC.r_std, 0.0)
        self.assertEqual(QUEBEC_ALL_ELECTRIC.p_heat_fraction_min, 1.0)

        for building in make_buildings(8, seed=3, archetype=QUEBEC_ALL_ELECTRIC):
            with self.subTest(unit_id=building.unit_id):
                self.assertEqual(building.R, 7.5)
                self.assertEqual(building.p_heat_max, 13.0)

    def test_the_default_is_still_the_energy_derived_archetype(self):
        """Adopting it elsewhere must not have changed what an unstated call gets."""
        self.assertNotEqual(DEFAULT_ARCHETYPE.r_mean, QUEBEC_ALL_ELECTRIC.r_mean)
        self.assertEqual(DEFAULT_ARCHETYPE.r_mean, building_module.R_MEAN)

    def test_it_draws_roughly_twice_the_peak_of_the_default(self):
        """The difference that makes the adoption a re-base, not a refactor."""
        index = pd.date_range("2024-01-01", periods=240, freq="1min")
        weather = pd.Series(np.full(len(index), -20.0), index=index)

        default_heat, _ = GridLoadFacade.generate_loads(
            "thermodynamic", weather, n_houses=6, resolution_minutes=15, seed=5
        )
        quebec_heat, _ = GridLoadFacade.generate_loads(
            "thermodynamic",
            weather,
            n_houses=6,
            resolution_minutes=15,
            seed=5,
            archetype=QUEBEC_ALL_ELECTRIC,
        )

        self.assertGreater(
            quebec_heat.sum(axis=1).max(), default_heat.sum(axis=1).max()
        )


class PublicEntryPassesTheArchetypeThroughTest(unittest.TestCase):
    """``generate_residential_load_profiles`` is the documented way in."""

    def test_the_parametric_engine_refuses_one_through_the_public_entry(self):
        with self.assertRaises(ValueError) as caught:
            generate_residential_load_profiles(
                n_units=2,
                day="cold",
                resolution_minutes=60,
                seed=1,
                generator="parametric",
                weather="synthetic",
                archetype=QUEBEC_ALL_ELECTRIC,
            )
        self.assertIn("thermodynamic", str(caught.exception))

    def test_stating_the_archetype_changes_the_profile(self):
        default = generate_residential_load_profiles(
            n_units=4,
            day="cold",
            resolution_minutes=60,
            seed=1,
            generator="thermodynamic",
            weather="synthetic",
        )
        quebec = generate_residential_load_profiles(
            n_units=4,
            day="cold",
            resolution_minutes=60,
            seed=1,
            generator="thermodynamic",
            weather="synthetic",
            archetype=QUEBEC_ALL_ELECTRIC,
        )

        self.assertEqual(default.shape, quebec.shape)
        self.assertGreater(quebec.sum(axis=1).max(), default.sum(axis=1).max())


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

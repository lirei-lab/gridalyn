"""Tests for the one-call load-generation API."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.api import (
    aggregate_load_multipliers,
    coincident_peak_loads_mw,
    generate_residential_load_profiles,
    scale_profiles_to_peaks,
)
from gridalyn.assets.datagen.data.weather import download_tmy


def _profiles(n_units: int = 10, **kwargs) -> pd.DataFrame:
    defaults = dict(
        day="peak",
        resolution_minutes=60,
        seed=7,
        weather="synthetic",
    )
    defaults.update(kwargs)
    return generate_residential_load_profiles(n_units, **defaults)


class TestSyntheticWeatherSource(unittest.TestCase):
    def test_synthetic_source_is_deterministic_and_annotated(self) -> None:
        first = download_tmy(source="synthetic")
        second = download_tmy(source="synthetic")

        self.assertTrue(first["temp_air"].equals(second["temp_air"]))
        self.assertEqual(len(first), 8760)
        self.assertEqual(
            first.attrs.get("gridalyn_weather_source"), "synthetic_climate_normals"
        )

    def test_unknown_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            download_tmy(source="weird")


class TestGenerateResidentialLoadProfiles(unittest.TestCase):
    def test_shape_columns_and_index(self) -> None:
        profiles = _profiles(n_units=5, resolution_minutes=30)

        self.assertEqual(profiles.shape, (48, 5))
        self.assertEqual(list(profiles.columns)[0], "unit_000")
        self.assertIsInstance(profiles.index, pd.DatetimeIndex)
        self.assertEqual(profiles.index[1] - profiles.index[0], pd.Timedelta(minutes=30))

    def test_same_seed_is_deterministic(self) -> None:
        self.assertTrue(_profiles(seed=11).equals(_profiles(seed=11)))

    def test_different_seed_differs(self) -> None:
        self.assertFalse(_profiles(seed=11).equals(_profiles(seed=12)))

    def test_loads_are_positive(self) -> None:
        self.assertGreater(float(_profiles().to_numpy().min()), 0.0)

    def test_unknown_day_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _profiles(day="weekend")


class TestAggregateLoadMultipliers(unittest.TestCase):
    def test_full_window_max_equals_peak_multiplier(self) -> None:
        multipliers = aggregate_load_multipliers(
            _profiles(), intervals=24, peak_multiplier=1.26
        )

        self.assertEqual(len(multipliers), 24)
        self.assertAlmostEqual(float(multipliers.max()), 1.26, places=9)
        self.assertGreater(float(multipliers.min()), 0.0)

    def test_peak_window_resamples_finer_than_profile(self) -> None:
        multipliers = aggregate_load_multipliers(
            _profiles(n_units=30, resolution_minutes=15),
            intervals=12,
            interval_minutes=5,
            peak_multiplier=1.24,
            window="peak",
        )

        self.assertEqual(len(multipliers), 12)
        self.assertAlmostEqual(float(multipliers.max()), 1.24, places=9)
        self.assertFalse(np.isnan(multipliers).any())

    def test_peak_window_requires_interval_minutes(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            aggregate_load_multipliers(_profiles(), intervals=12, window="peak")
        self.assertIn("interval_minutes", str(ctx.exception))


class TestAnchoringHelpers(unittest.TestCase):
    ANCHORS = {1: 0.035, 2: 0.045, 3: 0.030, 4: 0.040}

    def test_scale_profiles_to_peaks_hits_declared_peaks(self) -> None:
        scaled = scale_profiles_to_peaks(_profiles(), self.ANCHORS)

        for bus, peak_mw in self.ANCHORS.items():
            self.assertAlmostEqual(float(scaled[bus].max()), peak_mw, places=9)

    def test_coincident_peak_total_matches_anchor_total(self) -> None:
        snapshot = coincident_peak_loads_mw(_profiles(), self.ANCHORS)

        self.assertEqual(sorted(snapshot), sorted(self.ANCHORS))
        self.assertAlmostEqual(
            sum(snapshot.values()), sum(self.ANCHORS.values()), places=9
        )
        self.assertTrue(all(value > 0 for value in snapshot.values()))

    def test_snapshot_is_diversified_not_uniform(self) -> None:
        snapshot = coincident_peak_loads_mw(_profiles(n_units=40), self.ANCHORS)

        values = np.array(list(snapshot.values()))
        self.assertGreater(float(values.std()), 0.0)


if __name__ == "__main__":
    unittest.main()

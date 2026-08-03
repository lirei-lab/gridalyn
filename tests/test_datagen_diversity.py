"""Tests for ParametricArxGenerator provenance, fallback warning, and mean-preserving diversity.

These cover the additive, default-OFF hardening of the synthetic load-profile
generator: the default code path must stay byte-identical to the pinned
reference (so the frozen default-path baseline cannot drift), while the new
``mean_preserving_diversity`` flag de-biases the log-normal diversity factor.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator

# Reference values captured from the CURRENT generator (analytical fallback,
# random_seed=4242, 96-step 15-min day, temp = linspace(-10, 5, 96), 4 houses).
# These pin the DEFAULT path so frozen study baselines cannot drift.
_REF_HEAT = np.array(
    [
        [3.5091800391497534, 3.2258326176712138],
        [2.59644005497335, 3.480327741374323],
        [3.1681764510657073, 3.861720873668484],
    ],
    dtype=float,
)
_REF_BG = np.array(
    [
        [0.5379929895123345, 0.16394287277366967],
        [0.650994263950416, 0.1551396905691124],
        [0.3501399988160483, 0.12303818162567555],
    ],
    dtype=float,
)


def _fixed_temp() -> pd.Series:
    """Build a deterministic 15-min one-day outdoor-temperature series."""
    idx = pd.date_range("2024-01-15", periods=96, freq="15min")
    return pd.Series(np.linspace(-10.0, 5.0, 96), index=idx)


def _analytical_generator(
    tmp_path, *, mean_preserving_diversity: bool = False
) -> ParametricArxGenerator:
    """Construct a generator forced onto the analytical fallback (no weights)."""
    return ParametricArxGenerator(
        model_dir=tmp_path / "no_weights_here",
        random_seed=4242,
        mean_preserving_diversity=mean_preserving_diversity,
    )


def test_default_arrays_byte_identical_reference(tmp_path) -> None:
    """Default path is reproducible AND byte-identical to the pinned reference."""
    temp = _fixed_temp()
    g1 = _analytical_generator(tmp_path)
    g1.load()
    heat1, bg1 = g1.generate(temp, 4)
    heat2, bg2 = g1.generate(temp, 4)
    # Same seed -> identical across calls.
    assert np.array_equal(heat1, heat2)
    assert np.array_equal(bg1, bg2)
    # Pinned reference slice -> frozen baseline cannot drift.
    assert np.array_equal(heat1[:3, :2], _REF_HEAT)
    assert np.array_equal(bg1[:3, :2], _REF_BG)


def test_provenance_recorded_analytical(tmp_path) -> None:
    """After load() with missing weights, provenance is 'analytical'."""
    g = _analytical_generator(tmp_path)
    assert g.model_provenance is None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g.load()
    assert g.model_provenance == "analytical"


def test_silent_fallback_warns(tmp_path) -> None:
    """The silent analytical fallback emits a warning naming the swap."""
    g = _analytical_generator(tmp_path)
    with pytest.warns(UserWarning):
        g.load()


def test_mean_preserving_default_false_identical(tmp_path) -> None:
    """Default (flag off) equals the pinned byte-identical reference."""
    temp = _fixed_temp()
    g = _analytical_generator(tmp_path, mean_preserving_diversity=False)
    g.load()
    heat, bg = g.generate(temp, 4)
    assert np.array_equal(heat[:3, :2], _REF_HEAT)
    assert np.array_equal(bg[:3, :2], _REF_BG)


def test_mean_preserving_debiases(tmp_path) -> None:
    """mean_preserving=True de-biases the log-normal factor toward unit mean."""
    temp = _fixed_temp()
    sigma_heat = 0.6

    g_def = _analytical_generator(tmp_path, mean_preserving_diversity=False)
    g_def.load()
    heat_def, _ = g_def.generate(temp, 8)

    g_mp = _analytical_generator(tmp_path, mean_preserving_diversity=True)
    g_mp.load()
    heat_mp, _ = g_mp.generate(temp, 8)

    # Reconstruct the AR(1) noise the same way generate() does so we can isolate
    # the multiplicative log-normal factor for a single column.
    steps = len(temp)
    n_houses = 8
    dt_hours = 0.25
    rho_heat = np.exp(-dt_hours / 2.5)
    ar_heat = g_def._generate_ar1_noise(
        steps, n_houses, rho=rho_heat, sigma=sigma_heat, rng=g_def._rng(0)
    )
    col = 0
    factor_default = np.exp(ar_heat[:, col])
    factor_mp = np.exp(ar_heat[:, col] - 0.5 * sigma_heat**2)

    # The de-biased multiplicative factor has a column-mean closer to 1.0.
    assert abs(factor_mp.mean() - 1.0) < abs(factor_default.mean() - 1.0)
    # And the de-biased trace is strictly below the default on the same seed.
    assert np.all(factor_mp < factor_default)
    # The realized heat array differs once the flag is on.
    assert not np.array_equal(heat_def, heat_mp)

"""Unit tests for the LightGBM heating imputer."""

from __future__ import annotations

import numpy as np

from projects.admm_thermal_consensus.scripts.forecast.imputer import (
    HeatingImputer,
    build_features,
)


def _toy_data(seed: int = 0):
    rng = np.random.default_rng(seed)
    T, N = 96, 12
    hours = (np.arange(T) * 15 / 60.0) % 24
    temp = -10.0 + 6.0 * np.sin((hours - 6) / 24 * 2 * np.pi)
    levels = rng.uniform(2.0, 5.0, size=N)
    # heating rises as temperature falls, scaled by agent level
    heating = np.maximum(
        0.0, (levels[:, None]) * (1.0 - (temp[None, :] + 10) / 20.0)
    ) + rng.normal(0, 0.05, size=(N, T))
    return temp, heating, levels


def test_build_features_shapes():
    temp, heating, levels = _toy_data()
    X, y = build_features(temp, heating, levels)
    assert X.shape[0] == heating.size
    assert X.shape[1] == 4  # temp, sin_h, cos_h, level
    assert y.shape[0] == heating.size


def test_imputer_predicts_held_out_agent_reasonably():
    temp, heating, levels = _toy_data()
    train = np.arange(0, 9)
    test = np.arange(9, 12)
    imp = HeatingImputer(random_seed=0)
    imp.fit(temp, heating[train], levels[train])
    pred = imp.predict_agent(temp, levels[test[0]])
    truth = heating[test[0]]
    rmse = float(np.sqrt(np.mean((pred - truth) ** 2)))
    # predictions track the true held-out agent within a loose tolerance
    assert rmse < 0.6 * float(np.std(truth)) + 0.5
    assert pred.shape == truth.shape

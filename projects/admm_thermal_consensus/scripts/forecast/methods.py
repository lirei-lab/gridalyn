"""Estimator zoo for comparing imputation methods for non-responsive agents.

The coordinator observes only the responsive homes' heating; it trains an
estimator on them and predicts each silent home's profile from features it does
know (ambient temperature, time-of-day, and the home's nameplate heating level).
This module exposes several learned estimators plus naive baselines on a common
``fit_predict`` interface so they can be compared on equal footing.
"""

from __future__ import annotations

import numpy as np
from lightgbm import LGBMRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor

from projects.admm_thermal_consensus.scripts.forecast.imputer import build_features

# Methods that learn a feature->heating map (vs. the naive baselines below).
LEARNED_METHODS = ("lightgbm", "random_forest", "ridge", "knn")
# All methods that produce an estimate (naive baselines included). "none" is the
# no-imputation case and is handled by the coordinator, not by an estimator.
ESTIMATING_METHODS = LEARNED_METHODS + ("mean_level",)


def make_estimator(method: str, seed: int):
    """Return an unfitted sklearn-style regressor for a learned method."""
    if method == "lightgbm":
        return LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            min_child_samples=20, random_state=seed, verbose=-1,
        )
    if method == "random_forest":
        return RandomForestRegressor(
            n_estimators=200, max_depth=None, random_state=seed, n_jobs=-1,
        )
    if method == "ridge":
        return Ridge(alpha=1.0)
    if method == "knn":
        return KNeighborsRegressor(n_neighbors=15, weights="distance")
    raise ValueError(f"unknown learned method {method!r}")


def _predict_features(temperature: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Build the (len(levels)*T, 4) feature matrix for a set of query levels."""
    horizon = temperature.shape[0]
    step_hours = 24.0 / horizon
    hours = (np.arange(horizon) * step_hours) % 24.0
    sin_h = np.sin(2 * np.pi * hours / 24.0)
    cos_h = np.cos(2 * np.pi * hours / 24.0)
    blocks = [
        np.column_stack([temperature, sin_h, cos_h, np.full(horizon, lv)])
        for lv in levels
    ]
    return np.vstack(blocks)


def fit_predict(
    method: str,
    temperature: np.ndarray,
    heat_train: np.ndarray,
    levels_train: np.ndarray,
    levels_query: np.ndarray,
    seed: int,
) -> np.ndarray:
    """Estimate the heating profiles of query agents from the training agents.

    Args:
        method: one of ``ESTIMATING_METHODS``.
        temperature: shape ``(T,)`` ambient temperature.
        heat_train: shape ``(n_train, T)`` responsive agents' true heating.
        levels_train: shape ``(n_train,)`` responsive nameplate levels.
        levels_query: shape ``(n_query,)`` silent agents' nameplate levels.
        seed: RNG seed for the learned estimators.

    Returns:
        ``(n_query, T)`` non-negative estimated heating profiles.
    """
    horizon = temperature.shape[0]
    n_query = len(levels_query)
    if n_query == 0:
        return np.zeros((0, horizon))
    if method == "mean_level":
        # naive: a flat profile at each agent's known mean level (no shape)
        return np.repeat(levels_query[:, None], horizon, axis=1)
    estimator = make_estimator(method, seed)
    x_train, y_train = build_features(temperature, heat_train, levels_train)
    estimator.fit(x_train, y_train)
    preds = estimator.predict(_predict_features(temperature, levels_query))
    return np.maximum(0.0, preds.reshape(n_query, horizon))

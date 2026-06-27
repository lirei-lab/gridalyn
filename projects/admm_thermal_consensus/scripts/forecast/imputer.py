"""LightGBM imputer for a communication-failed agent's heating profile.

Features available to the coordinator WITHOUT the agent's report: ambient
temperature, time-of-day (sin/cos of hour), and the agent's known nameplate
heating level. The model is trained on responsive agents and used to impute
non-responsive ones inside the ADMM loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from lightgbm import LGBMRegressor


def build_features(
    temperature: np.ndarray, heating: np.ndarray, levels: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten (agents x time) heating into a feature/target table.

    Args:
        temperature: shape ``(T,)`` ambient temperature in degC.
        heating: shape ``(N, T)`` per-agent heating in kW.
        levels: shape ``(N,)`` per-agent nameplate level (mean heating kW).

    Returns:
        ``(X, y)`` with ``X`` columns ``[temp, sin_hour, cos_hour, level]``.
    """
    n_agents, horizon = heating.shape
    step_hours = 24.0 / horizon
    hours = (np.arange(horizon) * step_hours) % 24.0
    sin_h = np.sin(2 * np.pi * hours / 24.0)
    cos_h = np.cos(2 * np.pi * hours / 24.0)
    rows = []
    targets = []
    for i in range(n_agents):
        feat = np.column_stack(
            [temperature, sin_h, cos_h, np.full(horizon, levels[i])]
        )
        rows.append(feat)
        targets.append(heating[i])
    return np.vstack(rows), np.concatenate(targets)


@dataclass
class HeatingImputer:
    """LightGBM regressor that imputes a missing agent's heating profile."""

    random_seed: int = 42
    model: LGBMRegressor | None = field(default=None, init=False)

    def fit(
        self, temperature: np.ndarray, heating: np.ndarray, levels: np.ndarray
    ) -> "HeatingImputer":
        """Train on responsive agents' (feature, heating) rows."""
        x, y = build_features(temperature, heating, levels)
        self.model = LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            random_state=self.random_seed,
            verbose=-1,
            n_jobs=1,
            deterministic=True,
            force_row_wise=True,
        )
        self.model.fit(x, y)
        return self

    def predict_agent(self, temperature: np.ndarray, level: float) -> np.ndarray:
        """Predict the heating profile of an agent with the given level."""
        if self.model is None:
            raise RuntimeError("imputer is not fitted")
        horizon = temperature.shape[0]
        step_hours = 24.0 / horizon
        hours = (np.arange(horizon) * step_hours) % 24.0
        feat = np.column_stack(
            [
                temperature,
                np.sin(2 * np.pi * hours / 24.0),
                np.cos(2 * np.pi * hours / 24.0),
                np.full(horizon, level),
            ]
        )
        return np.maximum(0.0, self.model.predict(feat))

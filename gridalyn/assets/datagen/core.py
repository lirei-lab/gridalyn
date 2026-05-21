"""Facade for stochastic load-profile generation."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


LoadGeneratorType = Literal["parametric", "thermodynamic"]


class GridLoadFacade:
    """Generate synthetic heating and background-load trajectories.

    The facade supports two reproducible synthetic engines:

    - ``parametric``: a packaged LightGBM macro-shape model plus AR(1) diversity;
    - ``thermodynamic``: an explicit RC-style residential building simulator.

    Both engines return matrices in kilowatts with shape
    ``(time_steps, n_houses)``. They are intended for repeatable studies and
    examples, not as calibrated forecasts for a specific utility territory.
    """

    @classmethod
    def generate_loads(
        cls,
        generator_type: LoadGeneratorType,
        df_weather: pd.Series,
        n_houses: int,
        resolution_minutes: int,
        seed: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Route load generation to the requested synthetic engine."""
        if n_houses <= 0:
            raise ValueError("n_houses must be positive")
        if resolution_minutes <= 0:
            raise ValueError("resolution_minutes must be positive")

        target_freq = f"{resolution_minutes}min"
        native_res_temp = df_weather.resample(target_freq).mean().interpolate()

        if generator_type == "parametric":
            from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator

            gen = ParametricArxGenerator(random_seed=seed)
            gen.load()
            return gen.generate(native_res_temp, n_houses=n_houses)

        if generator_type == "thermodynamic":
            from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings

            buildings = make_buildings(n_houses, seed=seed)
            bld_results = simulate_buildings(buildings, native_res_temp)

            time_steps = len(native_res_temp)
            heat_kw_matrix = np.zeros((time_steps, n_houses))
            bg_kw_matrix = np.zeros((time_steps, n_houses))

            for i in range(n_houses):
                heat_kw_matrix[:, i] = bld_results[i]["p_heat_kw"].values
                bg_kw_matrix[:, i] = bld_results[i]["p_bg_kw"].values

            return heat_kw_matrix, bg_kw_matrix

        raise ValueError(
            "Unknown generator_type: "
            f"{generator_type!r}. Must be 'parametric' or 'thermodynamic'."
        )

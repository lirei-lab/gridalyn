"""Facade for stochastic load-profile generation."""

from __future__ import annotations

from typing import Any, Literal

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
        archetype: Any | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Route load generation to the requested synthetic engine.

        Args:
            generator_type: ``"parametric"`` or ``"thermodynamic"``.
            df_weather: Outdoor temperature series.
            n_houses: Dwellings to generate.
            resolution_minutes: Target resolution.
            seed: Base seed.
            archetype: Optional
                :class:`~gridalyn.assets.datagen.agents.ThermalArchetype` for the
                ``thermodynamic`` engine (bd irz). ``None`` keeps this module's
                default population, which is what every caller got before the
                parameter existed.

        Returns:
            Heating and background matrices in kilowatts.

        Raises:
            ValueError: On a non-positive count or resolution, an unknown
                engine, or an archetype handed to ``"parametric"`` -- a learned
                macro-shape model has no thermal envelope to re-parameterise, so
                accepting one silently would promise a calibration it cannot
                honour.
        """
        if n_houses <= 0:
            raise ValueError("n_houses must be positive")
        if resolution_minutes <= 0:
            raise ValueError("resolution_minutes must be positive")

        target_freq = f"{resolution_minutes}min"
        native_res_temp = df_weather.resample(target_freq).mean().interpolate()

        if generator_type == "parametric":
            from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator

            if archetype is not None:
                raise ValueError(
                    "archetype applies to generator_type='thermodynamic' only; "
                    "the parametric engine is a trained macro-shape model with "
                    "no RC envelope to re-parameterise. Pass "
                    "generator_type='thermodynamic', or drop the archetype to "
                    "accept the packaged model as calibrated."
                )
            gen = ParametricArxGenerator(random_seed=seed)
            gen.load()
            return gen.generate(native_res_temp, n_houses=n_houses)

        if generator_type == "thermodynamic":
            from gridalyn.assets.datagen.agents import (
                DEFAULT_ARCHETYPE,
                make_buildings,
                simulate_buildings,
            )

            buildings = make_buildings(
                n_houses,
                seed=seed,
                archetype=DEFAULT_ARCHETYPE if archetype is None else archetype,
            )
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

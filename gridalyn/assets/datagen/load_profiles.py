"""Synthetic residential load-profile generators."""

from __future__ import annotations

import os
import pickle
import warnings
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd


DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parent
    / "models"
    / "weights"
)


class _AnalyticalMacroModel:
    """Small deterministic fallback used when packaged ML weights are absent."""

    def __init__(self, kind: str):
        self.kind = kind

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        temp = features["temperature"].to_numpy(dtype=float)
        hour = features["hour"].to_numpy(dtype=float)
        evening_peak = np.exp(-0.5 * ((hour - 19.0) / 3.0) ** 2)
        morning_peak = np.exp(-0.5 * ((hour - 7.0) / 2.5) ** 2)
        occupancy_shape = 0.55 + 0.30 * morning_peak + 0.45 * evening_peak
        heating_degree = np.clip(18.0 - temp, 0.0, None)
        if self.kind == "heat":
            return np.clip(0.18 * heating_degree * occupancy_shape, 0.0, None)
        return 0.35 + 0.45 * occupancy_shape


class ParametricArxGenerator:
    """Parametric ARX generator for synthetic residential load traces.

    When packaged LightGBM weights are available, they provide aggregate heating
    and background-load shapes from temperature and time-of-day features. When
    weights or the optional LightGBM runtime are absent, the generator falls back
    to a deterministic analytical macro shape. Per-household diversity is
    introduced with seeded AR(1) noise, fixed structural multipliers, and phase
    shifts. The generator is reproducible, but it should be treated as a
    synthetic baseline rather than a calibrated forecast for a specific feeder.
    """

    def __init__(
        self,
        model_dir: str | os.PathLike[str] | None = None,
        random_seed: int | None = 4242,
        mean_preserving_diversity: bool = False,
    ) -> None:
        """Initialize the generator.

        Args:
            model_dir: Directory holding the packaged LightGBM macro weights.
                When ``None`` the packaged default directory is used.
            random_seed: Base seed for the reproducible diversity streams.
            mean_preserving_diversity: When ``True``, de-bias the log-normal
                diversity factor (``exp(ar - sigma**2 / 2)``) so the aggregate
                energy is not inflated by the multiplicative noise. Defaults to
                ``False``, which keeps the historical (byte-identical) traces.
        """
        self.model_dir = Path(model_dir) if model_dir is not None else DEFAULT_MODEL_DIR
        self.heat_model_path = self.model_dir / "lgbm_heating_macro.pkl"
        self.bg_model_path = self.model_dir / "lgbm_bg_macro.pkl"
        self.heat_model = None
        self.bg_model = None
        self.random_seed = random_seed
        self.mean_preserving_diversity = mean_preserving_diversity
        self.model_provenance: str | None = None

    def fit(self, df_meteo: pd.DataFrame, df_heating: pd.DataFrame, df_bg: pd.DataFrame):
        """Train and serialize the packaged macro-shape models."""
        import lightgbm as lgb

        print("Training Parametric ARX macro models...")
        os.makedirs(self.model_dir, exist_ok=True)

        unique_days = df_meteo.resample('D').mean().index

        X_list, y_heat_list, y_bg_list = [], [], []

        avg_heat_kw = df_heating.mean(axis=1)
        avg_bg_kw = df_bg.mean(axis=1)
        
        for d in unique_days:
            day_str = d.strftime('%Y-%m-%d')
            try:
                temp_day = df_meteo.loc[day_str, 'DryBulb'].resample('15min').mean()
                h_day = avg_heat_kw.loc[day_str][:len(temp_day)]
                b_day = avg_bg_kw.loc[day_str][:len(temp_day)]
                
                # Features: Exact Temperature, Hour, and Sinusoidal time of day
                hours = temp_day.index.hour + temp_day.index.minute / 60.0
                hour_sin = np.sin(2 * np.pi * hours / 24.0)
                hour_cos = np.cos(2 * np.pi * hours / 24.0)
                
                X = pd.DataFrame({
                    'temperature': temp_day.values,
                    'hour_sin': hour_sin,
                    'hour_cos': hour_cos,
                    'hour': hours
                })
                
                X_list.append(X)
                y_heat_list.append(h_day.values)
                y_bg_list.append(b_day.values)
            except Exception:
                pass
                
        X_train = pd.concat(X_list, ignore_index=True)
        y_heat_train = np.concatenate(y_heat_list)
        y_bg_train = np.concatenate(y_bg_list)
        
        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'num_leaves': 128,
            'learning_rate': 0.05,
            'n_estimators': 300,
            'verbose': -1
        }
        
        self.heat_model = lgb.LGBMRegressor(**params)
        self.heat_model.fit(X_train, y_heat_train)
        
        self.bg_model = lgb.LGBMRegressor(**params)
        self.bg_model.fit(X_train, y_bg_train)
        
        with open(self.heat_model_path, 'wb') as f:
            pickle.dump(self.heat_model, f)
        with open(self.bg_model_path, 'wb') as f:
            pickle.dump(self.bg_model, f)

        print(f"Models serialized to {self.model_dir}")

    def _load_analytical_fallback(self) -> None:
        self.heat_model = _AnalyticalMacroModel("heat")
        self.bg_model = _AnalyticalMacroModel("background")

    def _warn_silent_fallback(self, reason: str) -> None:
        """Emit a reproducibility warning when the analytical macro is used."""
        warnings.warn(
            "ParametricArxGenerator: packaged LightGBM macro weights "
            f"unavailable ({reason}); silently falling back to the "
            "deterministic analytical macro model. Aggregate shapes now come "
            "from the analytical fallback, NOT the trained LightGBM weights -- "
            "results are reproducible but differ from a weighted run. Install "
            "the weights (and the optional 'lightgbm' runtime) for the trained "
            "path. Inspect ParametricArxGenerator.model_provenance to confirm "
            "which path produced a given trace.",
            UserWarning,
            stacklevel=2,
        )

    def load(self):
        """Load packaged model weights, or use the analytical fallback.

        On the trained path ``model_provenance`` is set to ``"lgbm"``. On either
        fallback branch (missing weights or an absent ``lightgbm`` runtime) it is
        set to ``"analytical"`` and a :class:`UserWarning` is emitted naming the
        silent swap. Neither the provenance flag nor the warning changes the
        numeric traces.
        """
        if not self.heat_model_path.exists() or not self.bg_model_path.exists():
            self._load_analytical_fallback()
            self.model_provenance = "analytical"
            self._warn_silent_fallback("weight files not found")
            return

        try:
            with open(self.heat_model_path, 'rb') as f:
                self.heat_model = pickle.load(f)
            with open(self.bg_model_path, 'rb') as f:
                self.bg_model = pickle.load(f)
            self.model_provenance = "lgbm"
        except ModuleNotFoundError:
            self._load_analytical_fallback()
            self.model_provenance = "analytical"
            self._warn_silent_fallback("optional 'lightgbm' runtime not installed")
            
    def _rng(self, stream_offset: int = 0) -> np.random.Generator:
        if self.random_seed is None:
            return np.random.default_rng()
        return np.random.default_rng(self.random_seed + stream_offset)

    def _generate_ar1_noise(
        self,
        steps: int,
        n_houses: int,
        rho: float,
        sigma: float,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Generate auto-correlated AR(1) diversity noise."""
        noise = np.zeros((steps, n_houses), dtype=np.float32)
        # Seed first step
        noise[0, :] = rng.normal(0, sigma, size=n_houses)
        
        # The true variance of the injected shock
        shock_std = sigma * np.sqrt(1 - rho**2)
        
        for t in range(1, steps):
            shock = rng.normal(0, shock_std, size=n_houses)
            noise[t, :] = rho * noise[t-1, :] + shock
            
        return noise

    def generate(self, temp_out_series: pd.Series, n_houses: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate heating and background-load matrices in kilowatts."""
        if self.heat_model is None or self.bg_model is None:
            self.load()
            
        steps = len(temp_out_series)
        
        # 1. Feature Engineering
        hours = temp_out_series.index.hour + temp_out_series.index.minute / 60.0
        X_infer = pd.DataFrame({
            'temperature': temp_out_series.values,
            'hour_sin': np.sin(2 * np.pi * hours / 24.0),
            'hour_cos': np.cos(2 * np.pi * hours / 24.0),
            'hour': hours
        })
        
        # 2. Extract aggregate macro shapes.
        macro_heat = self.heat_model.predict(X_infer)
        macro_bg = self.bg_model.predict(X_infer)
        
        # Prevent negative macro predictions
        macro_heat = np.maximum(macro_heat, 0.0)
        macro_bg = np.maximum(macro_bg, 0.0)
        
        # 3. Resolution-aware AR(1) coefficients.
        try:
            # Detect delta_t in hours exactly 
            dt_hours = (temp_out_series.index[1] - temp_out_series.index[0]).total_seconds() / 3600.0
        except IndexError:
            dt_hours = 0.25 # Default fallback (15 min)
            
        tau_heat = 2.5
        tau_bg = 1.0
        
        # Transform continuous time constants to discrete Markov coefficients.
        rho_heat = np.exp(-dt_hours / tau_heat)
        rho_bg = np.exp(-dt_hours / tau_bg)

        # Generate AR(1) diversity noise. Bind the sigmas to named locals so the
        # optional mean-preserving de-bias term below reuses the SAME value.
        sigma_heat = 0.6
        sigma_bg = 0.4
        ar_heat = self._generate_ar1_noise(
            steps, n_houses, rho=rho_heat, sigma=sigma_heat, rng=self._rng(0)
        )
        ar_bg = self._generate_ar1_noise(
            steps, n_houses, rho=rho_bg, sigma=sigma_bg, rng=self._rng(1)
        )
        
        # 4. Preserve per-household structural consistency across calls.
        if getattr(self, '_n_houses_initialized', None) != n_houses:
            # Seeded structural multipliers make each house reproducible across runs.
            s_rng = self._rng(2)
            self._multiplier_heat = np.maximum(s_rng.normal(1.0, 0.25, size=n_houses), 0.1)
            self._multiplier_bg = np.maximum(s_rng.normal(1.0, 0.35, size=n_houses), 0.1)
            # Phase shifts add individual peak diversity.
            self._phase_shift_min = s_rng.normal(0, 60, size=n_houses).astype(int)
            self._n_houses_initialized = n_houses
            
        try:
            dt_min = int((temp_out_series.index[1] - temp_out_series.index[0]).total_seconds() / 60.0)
        except IndexError:
            dt_min = 15
            
        shifted_macro_heat = np.zeros((steps, n_houses))
        shifted_macro_bg = np.zeros((steps, n_houses))
        
        for i in range(n_houses):
            shift_steps = self._phase_shift_min[i] // dt_min
            shifted_macro_heat[:, i] = np.roll(macro_heat, shift_steps)
            shifted_macro_bg[:, i] = np.roll(macro_bg, shift_steps)
            
        # 5. Apply positive log-normal diversity around the aggregate shape.
        # When mean_preserving_diversity is enabled, subtract sigma**2/2 from the
        # AR(1) term so E[exp(ar - sigma**2/2)] ~ 1 and the multiplicative noise
        # no longer inflates aggregate energy. Default (False) keeps exp(ar)
        # unchanged, preserving byte-identity with the historical traces.
        if self.mean_preserving_diversity:
            factor_heat = np.exp(ar_heat - 0.5 * sigma_heat**2)
            factor_bg = np.exp(ar_bg - 0.5 * sigma_bg**2)
        else:
            factor_heat = np.exp(ar_heat)
            factor_bg = np.exp(ar_bg)

        raw_heat = (shifted_macro_heat * self._multiplier_heat[np.newaxis, :]) * factor_heat
        raw_bg   = (shifted_macro_bg   * self._multiplier_bg[np.newaxis, :])   * factor_bg

        # Preserve a small background standby floor.
        raw_bg = np.maximum(raw_bg, 0.05)

        return raw_heat, raw_bg

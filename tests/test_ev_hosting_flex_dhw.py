"""Unit tests for the stochastic electric DHW-tank base kernel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._annual import dhw_tank_annual


def _temp(hours: int = 240, tout: float = -10.0) -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=hours, freq="h")
    return pd.Series(np.full(hours, tout), index=idx)


def test_dhw_energy_per_home_realistic() -> None:
    """A full-year tank draws ~3-6 MWh/home/yr (QC DHW band)."""
    idx = pd.date_range("2020-01-01", periods=8760, freq="h")
    temp = pd.Series(-5.0 + 15.0 * np.sin(np.arange(8760) * 2 * np.pi / 8760), idx)
    feeder = dhw_tank_annual(np.random.default_rng(0), 4, temp, res_minutes=15)
    per_home_mwh = feeder.sum() * (15 / 60) / 1000 / 4
    assert 3.0 <= per_home_mwh <= 6.0, per_home_mwh


def test_dhw_deterministic() -> None:
    """Same rng seed -> byte-identical trace."""
    t = _temp()
    a = dhw_tank_annual(np.random.default_rng(7), 3, t, res_minutes=15)
    b = dhw_tank_annual(np.random.default_rng(7), 3, t, res_minutes=15)
    assert np.array_equal(a, b)


def test_dhw_zero_homes_is_zero() -> None:
    """No homes -> a zero trace."""
    t = _temp()
    z = dhw_tank_annual(np.random.default_rng(1), 0, t, res_minutes=15)
    assert z.shape[0] > 0 and float(np.abs(z).max()) == 0.0


def test_dhw_element_bounds_power() -> None:
    """No step exceeds n_homes x element power (the physical cap)."""
    from projects.ev_hosting_flex.scripts.config import DHW_ELEMENT_KW

    t = _temp()
    f = dhw_tank_annual(np.random.default_rng(2), 5, t, res_minutes=15)
    assert float(f.max()) <= 5 * float(DHW_ELEMENT_KW) + 1e-9


def test_dhw_draws_cluster_into_a_peak() -> None:
    """The occupancy weights produce an evening reheat peak above the daily
    mean (the tank recovers after clustered draws)."""
    idx = pd.date_range("2020-01-01", periods=24 * 30, freq="h")
    temp = pd.Series(np.full(24 * 30, -10.0), idx)
    f = dhw_tank_annual(np.random.default_rng(3), 8, temp, res_minutes=15)
    spd = 24 * 60 // 15
    daily = f[: (f.shape[0] // spd) * spd].reshape(-1, spd)
    hourly = daily.mean(axis=0).reshape(24, spd // 24).mean(axis=1)
    assert hourly[18:22].max() > hourly.mean()   # evening reheat peak


# ── Governed range assertion on the recalibrated base (skipif cache absent) ──
# Runs once generate_annual_mc has regenerated base_annual.npy (Task 5); asserts
# the realistic base lands in the HQ band in BOTH peak and energy.
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES, PROJECT_OUTPUTS_DIR,
)

_BASE = PROJECT_OUTPUTS_DIR / "data" / "base_annual.npy"


@pytest.mark.skipif(not _BASE.is_file(), reason="base_annual.npy absent (run generate_annual_mc)")
def test_recalibrated_base_in_hq_band() -> None:
    """The governed 6-home base is realistic in peak AND energy."""
    base = np.load(_BASE).astype(float)[0]
    n_homes = 6
    spd = 24 * 60 // ANNUAL_RES_MINUTES
    per_home = base / n_homes
    annual_mwh = per_home.sum() * (ANNUAL_RES_MINUTES / 60) / 1000
    p99_daily_peak = float(np.percentile(per_home.reshape(365, spd).max(axis=1), 99))
    assert 24.0 <= annual_mwh <= 31.0, f"energy {annual_mwh:.1f} MWh out of band"
    assert 10.0 <= p99_daily_peak <= 13.0, f"peak {p99_daily_peak:.1f} kW out of band"

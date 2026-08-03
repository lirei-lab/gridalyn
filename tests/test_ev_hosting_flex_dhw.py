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
    """No step exceeds the sum of the per-home jittered element powers. The
    per-home element is max(1.0, N(DHW_ELEMENT_KW, DHW_ELEMENT_JITTER_KW)), so
    the feeder cap is n_homes * a generous per-home ceiling (4-sigma tail)."""
    from projects.ev_hosting_flex.scripts.config import (
        DHW_ELEMENT_JITTER_KW,
        DHW_ELEMENT_KW,
    )

    t = _temp()
    n = 5
    f = dhw_tank_annual(np.random.default_rng(2), n, t, res_minutes=15)
    cap = n * (float(DHW_ELEMENT_KW) + 4.0 * float(DHW_ELEMENT_JITTER_KW))
    assert float(f.max()) <= cap + 1e-9


def test_dhw_draws_cluster_at_local_occupancy_hours() -> None:
    """The reheat peak lands at the LOCAL occupancy hours (evening 17-21),
    honouring the 19:00 TMY phase anchor — position p is local hour (19+p)%24.
    A phase bug (ignoring hod0) would peak ~5 h early at local midday."""
    hod0 = 19
    idx = pd.date_range("2020-01-01 19:00", periods=24 * 30, freq="h")
    temp = pd.Series(np.full(24 * 30, -10.0), idx)
    f = dhw_tank_annual(np.random.default_rng(3), 8, temp, res_minutes=15)
    spd = 24 * 60 // 15
    daily = f[: (f.shape[0] // spd) * spd].reshape(-1, spd)
    by_pos = daily.mean(axis=0).reshape(24, spd // 24).mean(axis=1)   # by array-hour
    # remap array-hour position p -> local clock hour (hod0 + p) % 24
    by_local = np.zeros(24)
    for p in range(24):
        by_local[(hod0 + p) % 24] = by_pos[p]
    # evening cluster (local 17-21) is the elevated peak of the continuous profile
    assert by_local[17:22].max() > by_local.mean()
    assert 17 <= int(np.argmax(by_local)) <= 21


def test_dhw_per_home_diversity_and_energy() -> None:
    """Per-home jitter diversifies the tanks (a small aggregate is not a clean
    integer multiple of one tank) while the annual energy stays in the QC band."""
    idx = pd.date_range("2020-01-01", periods=8760, freq="h")
    temp = pd.Series(-5.0 + 15.0 * np.sin(np.arange(8760) * 2 * np.pi / 8760), idx)
    one = dhw_tank_annual(np.random.default_rng(0), 1, temp, res_minutes=15)
    many = dhw_tank_annual(np.random.default_rng(0), 20, temp, res_minutes=15)
    # not identical tanks: 20-home trace is not 20x the single (jitter + draws differ)
    assert not np.allclose(many, 20.0 * one, atol=1.0)
    per_home_mwh = many.sum() * (15 / 60) / 1000 / 20
    assert 3.0 <= per_home_mwh <= 6.0, per_home_mwh


def test_dhw_deterministic_after_jitter() -> None:
    """Same rng seed -> byte-identical trace (the added jitter draws are seeded)."""
    idx = pd.date_range("2020-01-01 19:00", periods=24 * 20, freq="h")
    temp = pd.Series(np.full(24 * 20, -8.0), idx)
    a = dhw_tank_annual(np.random.default_rng(5), 4, temp, res_minutes=15)
    b = dhw_tank_annual(np.random.default_rng(5), 4, temp, res_minutes=15)
    assert np.array_equal(a, b)


def test_dhw_draw_profile_continuous_and_smoother() -> None:
    """The continuous draw profile has no zero hours, sums to 1, peaks in the
    evening, and is far smoother (smaller hour-to-hour jumps) than the old
    sparse DHW_DRAW_WEIGHTS."""
    from projects.ev_hosting_flex.scripts._annual import dhw_draw_profile
    from projects.ev_hosting_flex.scripts.config import DHW_DRAW_WEIGHTS

    w = dhw_draw_profile()
    assert w.shape == (24,)
    assert (w > 0.0).all()                       # no zero hours
    assert abs(float(w.sum()) - 1.0) < 1e-9      # normalized
    assert 17 <= int(np.argmax(w)) <= 21         # evening peak
    # sparse baseline (old dict) for the relative smoothness comparison
    sparse = np.zeros(24)
    for h, v in DHW_DRAW_WEIGHTS.items():
        sparse[int(h)] = v
    sparse = sparse / sparse.sum()
    new_step = float(np.max(np.abs(np.diff(w))))
    old_step = float(np.max(np.abs(np.diff(sparse))))
    assert new_step <= 0.6 * old_step, (new_step, old_step)


# ── Governed range assertion on the recalibrated base (skipif cache absent) ──
# Runs once generate_annual_mc has regenerated base_annual.npy (Task 5); asserts
# the realistic base lands in the HQ band in BOTH peak and energy.
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES, PROJECT_OUTPUTS_DIR,
)

_BASE = PROJECT_OUTPUTS_DIR / "data" / "base_annual.npy"


@pytest.mark.skipif(not _BASE.is_file(), reason="base_annual.npy absent (run generate_annual_mc)")
def test_recalibrated_base_in_hq_band() -> None:
    """The governed 6-home base is realistic in peak AND energy. The annual
    coincident peak sits in the HQ 10-15 kW band; the P99 typical-cold-day peak is
    ~9.8 (the smooth-DHW base diversifies the coincident peak down, as real
    diversified hot-water use does)."""
    base = np.load(_BASE).astype(float)[0]
    n_homes = 6
    spd = 24 * 60 // ANNUAL_RES_MINUTES
    per_home = base / n_homes
    annual_mwh = per_home.sum() * (ANNUAL_RES_MINUTES / 60) / 1000
    annual_peak = float(per_home.max())
    p99_daily_peak = float(np.percentile(per_home.reshape(365, spd).max(axis=1), 99))
    assert 24.0 <= annual_mwh <= 31.0, f"energy {annual_mwh:.1f} MWh out of band"
    assert 10.0 <= annual_peak <= 15.0, f"annual peak {annual_peak:.1f} kW out of band"
    assert 9.0 <= p99_daily_peak <= 13.0, f"p99 peak {p99_daily_peak:.1f} kW"

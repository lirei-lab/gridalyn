"""Unit + governed tests for the study-B annual Monte-Carlo seam (F1).

Tier 1 — hand-computed kernel tests (no SDK simulation, no cache): the cold
coupling, the curtailment backstop + fairness rotation, and the cold-day
P95-evening firm rule.
Tier 2 — governed reproduce-and-pin over the emitted annual artifacts (skipif
absent, like the other cache-dependent tests): shapes, the stressed-calibration
band, and the report contract.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._annual import (
    N_DAYS,
    cold_intensity,
    day_mean_temps,
    ev_fleet_annual,
    firm_annual,
    p95_cold_evening_loading,
    simulate_curtailment,
)
from projects.ev_hosting_flex.scripts.config import (
    CALENDAR_HOURS,
    E_TREF_C,
    EVENING_WINDOW_ANNUAL,
    K_ANNUAL,
    POOL_MAX_ANNUAL,
    PROJECT_OUTPUTS_DIR,
    SEED,
)

_DATA = PROJECT_OUTPUTS_DIR / "data"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "annual_mc_report.json"
_SKIP_REASON = (
    "annual artifacts (outputs/data/base_annual.npy / ev_fleet_annual.npy / "
    "tday_mean_c.npy) not present; run generate_annual_mc.py first "
    "(outputs are gitignored)"
)


# ─── Tier 1: hand-computed kernel tests ──────────────────────────────────


def test_cold_intensity_hand_computed() -> None:
    """cp = max(0, E_TREF − Tday): zero above the reference, linear below."""
    tday = np.array([E_TREF_C + 5.0, E_TREF_C, 0.0, -25.0])
    assert cold_intensity(tday) == pytest.approx([0.0, 0.0, E_TREF_C, E_TREF_C + 25.0])


def test_ev_fleet_cold_coupling_and_determinism() -> None:
    """A cold year draws MORE EV energy than a mild one; same seed → same pool."""
    cold_year = np.full(N_DAYS, -15.0)
    mild_year = np.full(N_DAYS, 20.0)
    pool_cold = ev_fleet_annual(np.random.default_rng(SEED), 2, cold_year, hod0=0)
    pool_mild = ev_fleet_annual(np.random.default_rng(SEED), 2, mild_year, hod0=0)
    assert pool_cold.shape == (2, CALENDAR_HOURS)
    # Cold raises BOTH plug-in probability and session energy.
    assert pool_cold.sum() > pool_mild.sum() * 1.3
    again = ev_fleet_annual(np.random.default_rng(SEED), 2, cold_year, hod0=0)
    assert np.array_equal(pool_cold, again)


def test_ev_fleet_respects_hod_phase() -> None:
    """With hod0=0 the charging lands in the evening hours of each day."""
    tday = np.full(N_DAYS, 0.0)
    pool = ev_fleet_annual(np.random.default_rng(SEED), 1, tday, hod0=0)
    by_hour = pool[0].reshape(N_DAYS, 24).sum(axis=0)
    # Arrival N(18, 1.5) clipped [16, 22]: essentially all energy in hours 16-23.
    evening = by_hour[16:24].sum()
    assert evening / by_hour.sum() > 0.95


def test_simulate_curtailment_backstop_and_residual() -> None:
    """The backstop holds enrolled load to the headroom; non-enrolled counts as residual."""
    horizon = 48
    rating = 10.0
    base = np.full(horizon, 8.0)
    demand = np.zeros((2, horizon))
    demand[0, 10] = 5.0  # enrolled: needs 5, headroom is 2 -> curtail 3
    demand[1, 20] = 5.0  # NON-enrolled: congests freely -> residual hour
    enrolled = np.array([True, False])
    out = simulate_curtailment(base, demand, enrolled, rating)
    assert out["curtailed_kwh_by_ev"][0] == pytest.approx(3.0)
    assert out["curtailed_kwh_by_ev"][1] == 0.0
    assert out["events_by_ev"][0] == 1
    assert out["residual_hours"] == 1
    assert out["curtailed_hours"][10] and not out["curtailed_hours"][20]
    assert out["base_floor_hours"] == 0
    # Served profile: enrolled hour clipped to the 2 kW headroom; non-enrolled
    # hour untouched (5 kW through, congestion and all).
    assert out["served_ev_kw"][10] == pytest.approx(2.0)
    assert out["served_ev_kw"][20] == pytest.approx(5.0)


def test_simulate_curtailment_fair_rotation_equalizes() -> None:
    """Two identical enrolled EVs end the year with near-equal curtailed energy."""
    horizon = 200
    rating = 10.0
    base = np.full(horizon, 9.0)
    demand = np.zeros((2, horizon))
    demand[:, ::10] = 2.0  # both want 2 kW every 10th hour; headroom is 1
    enrolled = np.array([True, True])
    fair = simulate_curtailment(base, demand, enrolled, rating, fair=True)
    unfair = simulate_curtailment(base, demand, enrolled, rating, fair=False)
    c_fair = fair["curtailed_kwh_by_ev"]
    c_unfair = unfair["curtailed_kwh_by_ev"]
    assert c_fair.sum() == pytest.approx(c_unfair.sum())  # same total burden
    # Rotation shares it (difference bounded by one event's asymmetry); fixed
    # order systematically favors EV0: per event EV0 gets the 1 kW headroom
    # (cut 1) and EV1 gets nothing (cut 2) -> c_unfair = (S/3, 2S/3).
    assert abs(c_fair[0] - c_fair[1]) <= 2.0 + 1e-9
    assert c_unfair[1] == pytest.approx(2.0 * c_unfair[0])
    assert abs(c_unfair[0] - c_unfair[1]) > abs(c_fair[0] - c_fair[1])


def test_p95_cold_evening_rule_hand_computed() -> None:
    """The firm statistic reads ONLY cold-day evening hours."""
    tday = np.full(N_DAYS, 20.0)
    tday[:100] = -10.0  # 100 cold days
    load = np.zeros(CALENDAR_HOURS)
    daily = load.reshape(N_DAYS, 24)
    start, _ = EVENING_WINDOW_ANNUAL
    daily[:100, start] = 71.25  # exactly the rating on cold-day evenings
    daily[100:, start] = 200.0  # warm-day spikes must be IGNORED
    p95 = p95_cold_evening_loading(daily.ravel(), 71.25, tday)
    assert p95 == pytest.approx(100.0)
    with pytest.raises(ValueError, match="no cold days"):
        p95_cold_evening_loading(load, 71.25, np.full(N_DAYS, 20.0))


def test_firm_annual_monotone_curve() -> None:
    """Adding identical EVs raises P95 monotonically; firm is the last passing n."""
    tday = np.full(N_DAYS, -10.0)
    base = np.zeros(CALENDAR_HOURS)
    base.reshape(N_DAYS, 24)[:, 18] = 60.0
    pool = np.zeros((4, CALENDAR_HOURS))
    pool.reshape(4, N_DAYS, 24)[:, :, 18] = 5.0  # each EV adds 5 kW at the peak
    out = firm_annual(base, pool, 71.25, tday)
    curve = out["p95_curve"]
    assert curve == sorted(curve)
    # 60 + n*5 <= 71.25 -> n = 2 passes (70), n = 3 fails (75).
    assert out["firm_ev_count"] == 2


def test_day_mean_temps_shape() -> None:
    """The per-day mean collapses 8760 hourly values into 365 days."""
    import pandas as pd

    idx = pd.date_range("2005-01-01", periods=CALENDAR_HOURS, freq="h", tz="UTC")
    series = pd.Series(np.arange(CALENDAR_HOURS, dtype=float), index=idx)
    tday = day_mean_temps(series)
    assert tday.shape == (N_DAYS,)
    assert tday[0] == pytest.approx(np.arange(24).mean())


# ─── Tier 2: governed reproduce-and-pin (skipif artifacts absent) ─────────


@pytest.mark.skipif(not (_DATA / "base_annual.npy").is_file(), reason=_SKIP_REASON)
def test_governed_annual_artifacts_shapes_and_band() -> None:
    """Shapes + the stressed study-B calibration band on the emitted base."""
    base = np.load(_DATA / "base_annual.npy")
    pool = np.load(_DATA / "ev_fleet_annual.npy")
    tday = np.load(_DATA / "tday_mean_c.npy")
    assert base.shape == (K_ANNUAL, CALENDAR_HOURS)
    assert pool.shape == (POOL_MAX_ANNUAL, CALENDAR_HOURS)
    assert tday.shape == (N_DAYS,)
    # Stressed calibration (R_STUDY_B): base peak in (80, 100)% of the rating
    # and per-home peak inside the CALIBRATION.md 10-15 kW band.
    peak = float(base[0].max())
    assert 0.80 * 71.25 <= peak <= 71.25, peak
    report = json.loads(_REPORT.read_text())
    n_homes = int(report["summary"]["n_homes"])
    assert 10.0 <= peak / n_homes <= 15.0


_FIRM_ANNUAL = PROJECT_OUTPUTS_DIR / "json" / "firm_hosting_annual.json"


@pytest.mark.skipif(not _FIRM_ANNUAL.is_file(), reason=_SKIP_REASON)
def test_governed_annual_firm_pin() -> None:
    """Governed reproduce-and-pin: annual firm = 3 on the 6-home stressed base.

    The study-B rule (P95 cold-day LOCAL-evening loading ≤ 100 %) crosses
    between 3 and 4 EVs after the 2026-07-07 phase fix (hod0 local anchor: EV
    sessions land at local 16-23h against the true evening base). If a
    deliberate recalibration shifts this, update the pin with rationale —
    never weaken the crossing assertions.
    """
    payload = json.loads(_FIRM_ANNUAL.read_text())
    firm = int(payload["firm_ev_count"])
    curve = payload["p95_cold_evening_curve"]
    limit = float(payload["p95_limit_percent"])
    assert firm == 3, payload
    assert curve == sorted(curve), "P95 must be monotone in the EV count"
    assert curve[firm] <= limit < curve[firm + 1]
    hours = payload["congested_hours_per_year_curve"]
    assert hours == sorted(hours), "congested hours must be monotone"
    assert payload["base_floor_hours"] == hours[0]


_CURTAIL = PROJECT_OUTPUTS_DIR / "json" / "curtailment_hosting.json"


@pytest.mark.skipif(not _CURTAIL.is_file(), reason=_SKIP_REASON)
def test_governed_curtailment_headline_pins() -> None:
    """Governed reproduce-and-pin: the study-B mechanism headlines.

    firm 3 -> flexible 12 (+300 %) with the full-enrollment backstop holding
    residual congestion at the base floor; light curtailment (< 6 % of EV
    energy at the pool top); near-perfect fair rotation; enrollment strictly
    reduces residual congestion; notice quality improves as sigma falls.
    """
    payload = json.loads(_CURTAIL.read_text())
    assert payload["firm_ev_count"] == 3
    assert payload["flexible_ev_count"] == 12
    assert payload["hosting_expansion_percent"] == pytest.approx(3.0)
    assert payload["residual_hours_curve"][payload["flexible_ev_count"]] == (
        payload["base_floor_hours"]
    )
    # The curtailed FRACTION is not monotone (the denominator — total EV
    # energy — grows with every EV while congestion overlap wobbles at low
    # counts); what the mechanism guarantees is non-negativity and a light
    # touch at the pool top.
    price = payload["curtailed_energy_percent_curve"]
    assert all(p >= 0.0 for p in price)
    assert max(price) < 6.0
    assert price[-1] > price[1], "pool-top curtailment must exceed the 1-EV level"
    fairness = payload["fairness"]
    assert fairness["jain_fair"] > 0.99 > fairness["jain_fixed_order"]
    sweep = payload["enrollment_sweep_1ev_per_home"]
    residuals = [row["residual_hours"] for row in sweep]
    assert residuals[0] >= residuals[-1]
    assert residuals[-1] == payload["base_floor_hours"]
    notice = payload["notice_quality_by_sigma"]
    assert notice["0.0"]["surprise_percent"] <= notice["5.0"]["surprise_percent"]


_ECON = PROJECT_OUTPUTS_DIR / "json" / "curtailment_economics.json"


@pytest.mark.skipif(not _ECON.is_file(), reason=_SKIP_REASON)
def test_governed_curtailment_economics_pins() -> None:
    """Governed reproduce-and-pin: contract-vs-reinforcement economics.

    Reinforcement = 8000 × CRF(5%, 30y) ≈ $520.41/yr; the two-part contract
    beats it up to 5 EVs (83% adoption on 6 homes); the zone of agreement
    (ceiling ≥ pay) closes at the same count; contract cost grows with n.
    """
    payload = json.loads(_ECON.read_text())
    assert payload["crf"] == pytest.approx(0.065051, abs=1e-6)
    assert payload["reinforcement_annual_yr"] == pytest.approx(520.411481, abs=1e-3)
    assert payload["breakeven_ev_count"] == 5
    curve = payload["curve"]
    costs = [row["contract_cost_yr"] for row in curve]
    assert costs == sorted(costs), "contract cost must grow with the EV count"
    for row in curve:
        beats = row["contract_beats_reinforcement"]
        assert beats == (row["n_evs"] <= payload["breakeven_ev_count"])
        assert row["household_floor_per_ev_yr"] <= row["pay_per_ev_yr"]


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP_REASON)
def test_governed_annual_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    summary = report["summary"]
    for key in (
        "n_homes",
        "base_peak_pct_rating",
        "base_floor_hours",
        "ev_pool_annual_kwh_mean",
        "fc_base_peaks_kw",
    ):
        assert key in summary, sorted(summary)

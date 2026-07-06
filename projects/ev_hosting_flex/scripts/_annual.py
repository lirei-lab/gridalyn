"""Study-B annual Monte-Carlo kernel: SDK base, cold-coupled EVs, curtailment.

Ports the manuscript study-B sandbox (``manuscripts/ev_hosting_flex/scripts/
study_b/{generate_sdk_base,curtailment_study_refined}.py``) into the governed
pipeline (see ``docs/superpowers/specs/2026-07-06-ev-hosting-flex-study-b-
annual-migration.md``). Three pieces:

* the SDK-agent annual building base (``make_buildings``/``simulate_buildings``
  at the stressed ``R_STUDY_B`` calibration — the ONLY thermal generator; no
  parametric fallback, T-13-03);
* the cold-coupled stochastic EV fleet (session energy and plug-in probability
  both rise with cold intensity, so EV stress compounds with the heating peak);
* the fair real-time curtailment simulator and the cold-day P95-evening firm
  rule (the study-B headlines).

GUARD-02: the SDK agent import is deferred inside the base builders; the EV /
curtailment / firm helpers are plain numpy and stay import-light for tests.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    ARRIVAL_CLIP_ANNUAL,
    ARRIVAL_MEAN_ANNUAL_H,
    ARRIVAL_STD_ANNUAL_H,
    CALENDAR_HOURS,
    CHARGER_MIX,
    COLD_DAY_TMEAN_C,
    DTYPE,
    E_TREF_C,
    EV_KWH_BASE,
    EV_KWH_KCOLD,
    EV_SIGMA_LOG,
    EVENING_WINDOW_ANNUAL,
    FIRM_P95_LIMIT_PERCENT,
    P_HEAT_QUEBEC,
    PLUGIN_BASE,
    PLUGIN_KCOLD,
    PLUGIN_MAX,
    R_STUDY_B,
    TMY_INPUT_PATH,
)

N_DAYS = CALENDAR_HOURS // 24
"""Calendar days of the annual horizon (365, non-leap)."""


def load_annual_tmy() -> pd.Series:
    """Return the committed TMY's 8760-hour ``temp_air`` series (tz-aware).

    Reads the project-local committed CSV (``TMY_INPUT_PATH``) — never a
    network download (the inherited REPRO guard). The first 8760 rows are the
    annual horizon; the tz-aware index preserves the TMY's hour-of-day phase
    (the file starts at 19:00 local — EV placement must respect it, D-B4).

    Returns:
        A float64 ``pd.Series`` of length 8760 indexed by tz-aware timestamps.

    Raises:
        ValueError: If the committed TMY is shorter than 8760 hourly rows.
    """
    df = pd.read_csv(TMY_INPUT_PATH)
    if len(df) < CALENDAR_HOURS:
        raise ValueError(
            f"load_annual_tmy read {len(df)} rows from {TMY_INPUT_PATH}; the "
            f"annual horizon needs {CALENDAR_HOURS}. Remediation: re-copy the "
            "full committed PVGIS TMY."
        )
    out = df.iloc[:CALENDAR_HOURS].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.set_index("timestamp")["temp_air"].astype(float)


def tmy_hour_of_day(temp_hourly: pd.Series) -> int:
    """Return the hour-of-day of the TMY's first row (the phase anchor)."""
    return int(temp_hourly.index[0].tz_convert(None).hour)


def day_mean_temps(temp_hourly: pd.Series) -> np.ndarray:
    """Return the per-day mean temperature array ``(365,)`` (°C, float64)."""
    return (
        temp_hourly.to_numpy(dtype=DTYPE)[: N_DAYS * 24]
        .reshape(N_DAYS, 24)
        .mean(axis=1)
    )


def annual_base_realization(
    temp_hourly: pd.Series,
    n_homes: int,
    seed: int,
    *,
    per_day_offset_c: np.ndarray | None = None,
) -> np.ndarray:
    """Return one annual SDK-agent feeder base realization ``(8760,)`` kW.

    Study-B base (D-B1): the SDK building population recalibrated to the
    stressed Québec archetype (``R_STUDY_B`` / ``P_HEAT_QUEBEC``), simulated at
    1-min over the (optionally offset) annual temperature and aggregated to
    hourly means. Ports ``generate_sdk_base.sdk_base``.

    Args:
        temp_hourly: Output of :func:`load_annual_tmy`.
        n_homes: Dwelling count on the study feeder (topology-cache driven).
        seed: Reproducible realization seed (``SEED + r``).
        per_day_offset_c: Optional ``(365,)`` per-day temperature offset (°C)
            — the day-ahead forecast-error channel (D-B3).

    Returns:
        A ``(8760,)`` float64 feeder-aggregate base trace in kW.

    Raises:
        ImportError: If the SDK agent cannot be imported (no silent fallback —
            never substitutes a hand-rolled base; T-13-03).
    """
    try:
        from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
    except ImportError as exc:  # no silent fallback (T-13-03)
        raise ImportError(
            "annual_base_realization could not import the SDK "
            "'gridalyn.assets.datagen.agents' building generator; the study-B "
            "annual seam refuses to substitute a hand-rolled base. Remediation: "
            f"install the gridalyn SDK. Original error: {exc}"
        ) from exc

    temp = temp_hourly
    if per_day_offset_c is not None:
        offset = np.asarray(per_day_offset_c, dtype=DTYPE)
        if offset.shape != (N_DAYS,):
            raise ValueError(
                f"annual_base_realization received per_day_offset_c "
                f"{offset.shape}, expected ({N_DAYS},) — one offset per day."
            )
        temp = temp + np.repeat(offset, 24)[: len(temp)]
    temp_1min = temp.resample("1min").interpolate()

    buildings = make_buildings(int(n_homes), seed=int(seed))
    for building in buildings:
        building.R = R_STUDY_B
        building.p_heat_max = P_HEAT_QUEBEC
    results = simulate_buildings(
        buildings, temp_1min, burnin_hours=6, random_seed=int(seed)
    )
    agg = sum(results[uid]["p_total_kw"] for uid in results)
    hourly = agg.resample("60min").mean().to_numpy(dtype=DTYPE)
    return hourly[:CALENDAR_HOURS].astype(DTYPE)


def cold_intensity(tday_mean_c: np.ndarray) -> np.ndarray:
    """Return the per-day cold intensity ``cp = max(0, E_TREF_C − Tday)``."""
    return np.maximum(0.0, float(E_TREF_C) - np.asarray(tday_mean_c, dtype=DTYPE))


def ev_fleet_annual(
    rng: np.random.Generator,
    n_evs: int,
    tday_mean_c: np.ndarray,
    hod0: int,
) -> np.ndarray:
    """Return the cold-coupled per-EV annual demand pool ``(n_evs, 8760)`` kW.

    Ports study-B ``fleet()`` (D-B4): per EV per day, the plug-in probability
    and the lognormal session energy BOTH rise with the day's cold intensity;
    arrival is an evening Gaussian; the session charges at the sampled charger
    power with exact hourly overlap allocation, phase-aligned to the TMY's
    hour-of-day anchor.

    Args:
        rng: Pinned generator (``default_rng(SEED)`` in the stage).
        n_evs: Pool size (``POOL_MAX_ANNUAL``).
        tday_mean_c: ``(365,)`` per-day mean temperatures.
        hod0: TMY hour-of-day phase anchor (:func:`tmy_hour_of_day`).

    Returns:
        A ``(n_evs, 8760)`` float64 per-EV demand matrix in kW; sweeps use row
        prefixes (row order is the draw order, pinned by the rng).
    """
    chargers = np.array(sorted(CHARGER_MIX), dtype=DTYPE)
    shares = np.array([CHARGER_MIX[kw] for kw in sorted(CHARGER_MIX)], dtype=DTYPE)
    shares = shares / shares.sum()
    cp_by_day = cold_intensity(tday_mean_c)
    lo, hi = ARRIVAL_CLIP_ANNUAL

    demand = np.zeros((int(n_evs), CALENDAR_HOURS), dtype=DTYPE)
    for ev in range(int(n_evs)):
        for day in range(N_DAYS):
            cp = float(cp_by_day[day])
            plug_p = min(float(PLUGIN_MAX), float(PLUGIN_BASE) + float(PLUGIN_KCOLD) * cp)
            if rng.random() > plug_p:
                continue
            charger_kw = float(rng.choice(chargers, p=shares))
            median_kwh = float(EV_KWH_BASE) * (1.0 + float(EV_KWH_KCOLD) * cp)
            energy_kwh = max(
                1.0, float(rng.lognormal(np.log(median_kwh), float(EV_SIGMA_LOG)))
            )
            start_h = float(
                np.clip(
                    rng.normal(float(ARRIVAL_MEAN_ANNUAL_H), float(ARRIVAL_STD_ANNUAL_H)),
                    lo,
                    hi,
                )
            )
            end_h = start_h + energy_kwh / charger_kw
            day_anchor = day * 24
            for hour in range(int(np.floor(start_h)), int(np.ceil(end_h))):
                idx = day_anchor + ((hour - hod0) % 24)
                if idx < CALENDAR_HOURS:
                    overlap = max(0.0, min(end_h, hour + 1) - max(start_h, hour))
                    demand[ev, idx] += overlap * charger_kw
    return demand


def simulate_curtailment(
    base: np.ndarray,
    ev_demand: np.ndarray,
    enrolled: np.ndarray,
    rating_kw: float,
    *,
    fair: bool = True,
) -> dict[str, Any]:
    """Run the fair real-time curtailment backstop over the year.

    Ports study-B ``simulate()`` (D-B5): each hour the enrolled EVs may draw at
    most the headroom left by the base plus the NON-enrolled EVs (which charge
    freely — congestion the contract cannot touch is counted as ``residual``).
    Enrolled draws above the headroom are curtailed in fairness order
    (descending cumulative curtailed energy — rotation), energy NOT recovered.

    Args:
        base: ``(8760,)`` feeder base in kW.
        ev_demand: ``(n_evs, 8760)`` per-EV demand in kW.
        enrolled: ``(n_evs,)`` bool enrollment mask.
        rating_kw: Feeder transformer usable rating in kW.
        fair: Fairness rotation on (study-B criterion a); ``False`` = fixed
            index order (the unfair comparator).

    Returns:
        Dict with ``curtailed_kwh_by_ev (n_evs,)``, ``events_by_ev (n_evs,)``,
        ``curtailed_hours (8760,) bool``, ``residual_hours`` (int, non-enrolled
        congestion), ``base_floor_hours`` (int, base alone above rating), and
        ``served_ev_kw (horizon,)`` — the post-backstop aggregate EV draw (the
        AC validation's "with contract" hourly profile).
    """
    base = np.asarray(base, dtype=DTYPE)
    demand = np.asarray(ev_demand, dtype=DTYPE)
    enrolled = np.asarray(enrolled, dtype=bool)
    n_evs, horizon = demand.shape
    if enrolled.shape != (n_evs,):
        raise ValueError(
            f"simulate_curtailment received enrolled {enrolled.shape}, expected "
            f"({n_evs},) matching ev_demand rows."
        )

    curtailed = np.zeros(n_evs, dtype=DTYPE)
    events = np.zeros(n_evs, dtype=int)
    curtailed_hours = np.zeros(horizon, dtype=bool)
    residual = 0
    free_draw = demand[~enrolled, :].sum(axis=0)
    served_ev_kw = demand.sum(axis=0).astype(DTYPE)  # curtailments subtract below
    for t in range(horizon):
        headroom = float(rating_kw) - (base[t] + free_draw[t])
        if base[t] <= rating_kw and (base[t] + free_draw[t]) > rating_kw:
            residual += 1
        active = np.where(enrolled & (demand[:, t] > 1e-9))[0]
        if active.size == 0 or demand[active, t].sum() <= max(headroom, 0.0):
            continue
        curtailed_hours[t] = True
        if fair:
            order = active[np.argsort(-curtailed[active], kind="stable")]
        else:
            order = active[np.argsort(active, kind="stable")]
        remaining = max(0.0, headroom)
        for ev in order:
            granted = min(float(demand[ev, t]), remaining)
            remaining -= granted
            cut = float(demand[ev, t]) - granted
            if cut > 1e-9:
                curtailed[ev] += cut
                events[ev] += 1
                served_ev_kw[t] -= cut
    return {
        "curtailed_kwh_by_ev": curtailed,
        "events_by_ev": events,
        "curtailed_hours": curtailed_hours,
        "residual_hours": int(residual),
        "base_floor_hours": int((base > float(rating_kw)).sum()),
        "served_ev_kw": served_ev_kw,
    }


def p95_cold_evening_loading(
    load_kw: np.ndarray, rating_kw: float, tday_mean_c: np.ndarray
) -> float:
    """Return the P95 over cold days of the max evening loading (%).

    The study-B firm statistic (D-B5): reshape the annual load to (365, 24),
    keep the cold days (``Tday < COLD_DAY_TMEAN_C``), take each day's max over
    the evening window, and return the 95th percentile in % of the rating.

    Args:
        load_kw: ``(8760,)`` feeder load in kW.
        rating_kw: Usable rating in kW.
        tday_mean_c: ``(365,)`` per-day mean temperatures.

    Returns:
        The P95 cold-day evening peak loading in percent.

    Raises:
        ValueError: If no day classifies as cold (the rule needs a winter).
    """
    tday = np.asarray(tday_mean_c, dtype=DTYPE)
    cold_days = np.where(tday < float(COLD_DAY_TMEAN_C))[0]
    if cold_days.size == 0:
        raise ValueError(
            "p95_cold_evening_loading found no cold days (Tday < "
            f"{COLD_DAY_TMEAN_C} °C); the firm rule needs a winter. Remediation: "
            "verify the committed TMY is the Trois-Rivières annual file."
        )
    start, end = EVENING_WINDOW_ANNUAL
    daily = np.asarray(load_kw, dtype=DTYPE)[: N_DAYS * 24].reshape(N_DAYS, 24)
    evening_peaks = daily[cold_days, start:end].max(axis=1)
    return float(np.percentile(evening_peaks / float(rating_kw) * 100.0, 95))


def firm_annual(
    base: np.ndarray,
    ev_pool: np.ndarray,
    rating_kw: float,
    tday_mean_c: np.ndarray,
) -> dict[str, Any]:
    """Return the study-B firm hosting count and its P95 curve.

    ``firm`` = the largest pool prefix n whose P95 cold-day evening loading is
    at or below ``FIRM_P95_LIMIT_PERCENT`` (curtailment-free hosting, D-B5).

    Args:
        base: ``(8760,)`` feeder base in kW.
        ev_pool: ``(pool, 8760)`` per-EV demand pool (prefix sweeps).
        rating_kw: Usable rating in kW.
        tday_mean_c: ``(365,)`` per-day mean temperatures.

    Returns:
        Dict with ``firm_ev_count`` (int), ``p95_curve`` (list, index = EV
        count 0..pool) and ``limit_percent``.
    """
    pool = np.asarray(ev_pool, dtype=DTYPE)
    curve: list[float] = []
    cumulative = np.zeros(pool.shape[1], dtype=DTYPE)
    curve.append(p95_cold_evening_loading(base, rating_kw, tday_mean_c))
    for ev in range(pool.shape[0]):
        cumulative = cumulative + pool[ev]
        curve.append(p95_cold_evening_loading(base + cumulative, rating_kw, tday_mean_c))
    passing = [n for n, p95 in enumerate(curve) if p95 <= float(FIRM_P95_LIMIT_PERCENT)]
    return {
        "firm_ev_count": int(passing[-1]) if passing else 0,
        "p95_curve": [round(float(v), 6) for v in curve],
        "limit_percent": float(FIRM_P95_LIMIT_PERCENT),
    }

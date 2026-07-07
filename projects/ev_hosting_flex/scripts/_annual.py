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
    ANNUAL_RES_MINUTES,
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

STEPS_PER_DAY = 24 * 60 // ANNUAL_RES_MINUTES
"""Steps per day at the governed resolution (96 at 15 min)."""

N_STEPS = N_DAYS * STEPS_PER_DAY
"""Annual step count at the governed resolution (35040 at 15 min)."""


def aggregate_to_hourly(arr: np.ndarray, res_minutes: int = ANNUAL_RES_MINUTES) -> np.ndarray:
    """Mean-aggregate a step-resolution trace to hourly (``…, 8760``).

    Reduces the LAST axis from ``N_DAYS * 24*60/res`` steps to ``8760`` hours by
    averaging each ``60/res``-step block — the AC validation layer consumes the
    hourly view of the governed step-resolution arrays.

    Args:
        arr: ``(…, n_steps)`` step-resolution kW trace.
        res_minutes: Step width in minutes (default: the governed resolution).

    Returns:
        The ``(…, 8760)`` hourly-mean trace.
    """
    steps_per_hour = 60 // int(res_minutes)
    a = np.asarray(arr, dtype=DTYPE)
    lead = a.shape[:-1]
    return a.reshape(*lead, CALENDAR_HOURS, steps_per_hour).mean(axis=-1)


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
    # Parse in UTC (a proper DatetimeIndex), then convert back to the file's
    # LOCAL fixed offset read from the first raw timestamp string: the phase
    # anchor below must be the LOCAL hour — the committed TMY starts at 19:00
    # local (00:00 UTC), and anchoring to UTC misplaces the evening EV sessions
    # to local midday (the 2026-07-07 phase-bug fix).
    stamps = pd.to_datetime(out["timestamp"], utc=True)
    raw0 = str(out["timestamp"].iloc[0])
    offset = pd.Timestamp(raw0).utcoffset()
    if offset is None:
        raise ValueError(
            f"load_annual_tmy needs tz-offset timestamps (got {raw0!r}); the "
            "LOCAL phase anchor cannot be derived. Remediation: re-copy the "
            "committed PVGIS TMY with ISO offsets."
        )
    from datetime import timezone as _tz

    out["timestamp"] = stamps.dt.tz_convert(_tz(offset))
    return out.set_index("timestamp")["temp_air"].astype(float)


def tmy_hour_of_day(temp_hourly: pd.Series) -> int:
    """Return the LOCAL hour-of-day of the TMY's first row (the phase anchor).

    Array position ``p`` of every annual artifact corresponds to local clock
    hour ``(hod0 + p) % 24``; the EV sampler and the evening-window firm rule
    both consume this anchor so sessions and windows land at the intended
    LOCAL hours (study-B's ``_HOD0`` convention).
    """
    return int(temp_hourly.index[0].hour)


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
    res_minutes: int = ANNUAL_RES_MINUTES,
) -> np.ndarray:
    """Return one annual SDK-agent feeder base realization ``(n_steps,)`` kW.

    Study-B base (D-B1): the SDK building population recalibrated to the
    stressed Québec archetype (``R_STUDY_B`` / ``P_HEAT_QUEBEC``), simulated at
    1-min over the (optionally offset) annual temperature and aggregated to
    ``res_minutes`` means. Ports ``generate_sdk_base.sdk_base``; the finer-than-
    hourly aggregation is the 2026-07-07 granularity fix (the agent already
    simulates 1-min, so it is free).

    Args:
        temp_hourly: Output of :func:`load_annual_tmy`.
        n_homes: Dwelling count on the study feeder (topology-cache driven).
        seed: Reproducible realization seed (``SEED + r``).
        per_day_offset_c: Optional ``(365,)`` per-day temperature offset (°C)
            — the day-ahead forecast-error channel (D-B3).
        res_minutes: Aggregation resolution in minutes (default: governed).

    Returns:
        A ``(N_DAYS * 24*60/res,)`` float64 feeder-aggregate base trace in kW
        (35040 at 15 min).

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
    stepped = agg.resample(f"{int(res_minutes)}min").mean().to_numpy(dtype=DTYPE)
    n_steps = N_DAYS * (24 * 60 // int(res_minutes))
    # The 1-min resample ends at the TMY's last hourly stamp, so the final
    # ``60/res - 1`` steps of the year (the last <1 h) have no interpolation
    # anchor; deterministically edge-pad to the full step grid (those steps are
    # the 23:xx tail of Dec 31, never a binding cold-evening slot).
    if stepped.shape[0] < n_steps:
        stepped = np.pad(stepped, (0, n_steps - stepped.shape[0]), mode="edge")
    return stepped[:n_steps].astype(DTYPE)


def cold_intensity(tday_mean_c: np.ndarray) -> np.ndarray:
    """Return the per-day cold intensity ``cp = max(0, E_TREF_C − Tday)``."""
    return np.maximum(0.0, float(E_TREF_C) - np.asarray(tday_mean_c, dtype=DTYPE))


def ev_fleet_annual(
    rng: np.random.Generator,
    n_evs: int,
    tday_mean_c: np.ndarray,
    hod0: int,
    *,
    res_minutes: int = ANNUAL_RES_MINUTES,
) -> np.ndarray:
    """Return the cold-coupled per-EV annual demand pool ``(n_evs, n_steps)`` kW.

    Ports study-B ``fleet()`` (D-B4): per EV per day, the plug-in probability
    and the lognormal session energy BOTH rise with the day's cold intensity;
    arrival is an evening Gaussian; the session charges at the sampled charger
    power with exact MINUTE overlap allocation into ``res_minutes`` bins,
    phase-aligned to the TMY's hour-of-day anchor. Each stored value is the
    step's AVERAGE kW (``occupied_fraction × charger_kw``), so
    ``sum(step_kW) × res/60`` reproduces the session energy.

    Args:
        rng: Pinned generator (``default_rng(SEED)`` in the stage).
        n_evs: Pool size (``POOL_MAX_ANNUAL``).
        tday_mean_c: ``(365,)`` per-day mean temperatures.
        hod0: TMY hour-of-day phase anchor (:func:`tmy_hour_of_day`).
        res_minutes: Step width in minutes (default: the governed resolution).

    Returns:
        A ``(n_evs, N_DAYS * 24*60/res)`` float64 per-EV demand matrix in kW;
        sweeps use row prefixes (row order is the draw order, pinned by the rng).
    """
    chargers = np.array(sorted(CHARGER_MIX), dtype=DTYPE)
    shares = np.array([CHARGER_MIX[kw] for kw in sorted(CHARGER_MIX)], dtype=DTYPE)
    shares = shares / shares.sum()
    cp_by_day = cold_intensity(tday_mean_c)
    lo, hi = ARRIVAL_CLIP_ANNUAL

    res = int(res_minutes)
    steps_per_day = 24 * 60 // res
    n_steps = N_DAYS * steps_per_day
    hod0_slot = int(hod0) * (60 // res)  # phase anchor in step units

    demand = np.zeros((int(n_evs), n_steps), dtype=DTYPE)
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
            start_m = float(
                np.clip(
                    rng.normal(float(ARRIVAL_MEAN_ANNUAL_H), float(ARRIVAL_STD_ANNUAL_H)),
                    lo,
                    hi,
                )
            ) * 60.0
            end_m = start_m + energy_kwh / charger_kw * 60.0
            day_anchor = day * steps_per_day
            for slot in range(int(np.floor(start_m / res)), int(np.ceil(end_m / res))):
                slot_start_m = slot * res
                overlap_min = max(
                    0.0, min(end_m, slot_start_m + res) - max(start_m, slot_start_m)
                )
                if overlap_min <= 0.0:
                    continue
                pos = (slot - hod0_slot) % steps_per_day
                # average kW over the step = occupied fraction × charger power
                demand[ev, day_anchor + pos] += (overlap_min / res) * charger_kw
    return demand


def simulate_curtailment(
    base: np.ndarray,
    ev_demand: np.ndarray,
    enrolled: np.ndarray,
    rating_kw: float,
    *,
    fair: bool = True,
    res_minutes: int = 60,
) -> dict[str, Any]:
    """Run the fair real-time curtailment backstop over the year.

    Ports study-B ``simulate()`` (D-B5): each STEP the enrolled EVs may draw at
    most the headroom left by the base plus the NON-enrolled EVs (which charge
    freely — congestion the contract cannot touch is counted as ``residual``).
    Enrolled draws above the headroom are curtailed in fairness order
    (descending cumulative curtailed energy — rotation), energy NOT recovered.

    Energy quantities are in kWh (``step_kW × res_minutes/60``) and duration
    quantities (``residual_hours`` / ``base_floor_hours``) are in real hours,
    so results are resolution-agnostic; ``res_minutes`` defaults to 60 (one step
    = one hour = energy equals power) — the governed stages pass
    ``ANNUAL_RES_MINUTES``.

    Args:
        base: ``(horizon,)`` feeder base in kW (average per step).
        ev_demand: ``(n_evs, horizon)`` per-EV demand in kW (average per step).
        enrolled: ``(n_evs,)`` bool enrollment mask.
        rating_kw: Feeder transformer usable rating in kW.
        fair: Fairness rotation on (study-B criterion a); ``False`` = fixed
            index order (the unfair comparator).
        res_minutes: Step width in minutes (governed stages pass 15).

    Returns:
        Dict with ``curtailed_kwh_by_ev (n_evs,)`` (kWh), ``events_by_ev
        (n_evs,)`` (count of curtailed STEPS), ``curtailed_steps (horizon,)
        bool``, ``residual_hours`` (float, non-enrolled congestion), and
        ``base_floor_hours`` (float, base alone above rating), plus
        ``served_ev_kw (horizon,)`` — the post-backstop aggregate EV draw (the
        AC validation's "with contract" profile).
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
    hours_per_step = float(res_minutes) / 60.0

    curtailed = np.zeros(n_evs, dtype=DTYPE)  # kWh
    events = np.zeros(n_evs, dtype=int)
    curtailed_steps = np.zeros(horizon, dtype=bool)
    residual_steps = 0
    free_draw = demand[~enrolled, :].sum(axis=0)
    served_ev_kw = demand.sum(axis=0).astype(DTYPE)  # curtailments subtract below
    for t in range(horizon):
        headroom = float(rating_kw) - (base[t] + free_draw[t])
        if base[t] <= rating_kw and (base[t] + free_draw[t]) > rating_kw:
            residual_steps += 1
        active = np.where(enrolled & (demand[:, t] > 1e-9))[0]
        if active.size == 0 or demand[active, t].sum() <= max(headroom, 0.0):
            continue
        curtailed_steps[t] = True
        if fair:
            order = active[np.argsort(-curtailed[active], kind="stable")]
        else:
            order = active[np.argsort(active, kind="stable")]
        remaining = max(0.0, headroom)
        for ev in order:
            granted = min(float(demand[ev, t]), remaining)
            remaining -= granted
            cut_kw = float(demand[ev, t]) - granted
            if cut_kw > 1e-9:
                curtailed[ev] += cut_kw * hours_per_step  # kW × h = kWh
                events[ev] += 1
                served_ev_kw[t] -= cut_kw
    return {
        "curtailed_kwh_by_ev": curtailed,
        "events_by_ev": events,
        "curtailed_steps": curtailed_steps,
        "residual_hours": float(residual_steps) * hours_per_step,
        "base_floor_hours": float((base > float(rating_kw)).sum()) * hours_per_step,
        "served_ev_kw": served_ev_kw,
    }


def p95_cold_evening_loading(
    load_kw: np.ndarray,
    rating_kw: float,
    tday_mean_c: np.ndarray,
    *,
    hod0: int = 0,
    res_minutes: int = 60,
) -> float:
    """Return the P95 over cold days of the max evening loading (%).

    The study-B firm statistic (D-B5): reshape the annual load to
    ``(365, steps_per_day)``, keep the cold days (``Tday < COLD_DAY_TMEAN_C``),
    take each day's max over the LOCAL-hour evening window, and return the 95th
    percentile in % of the rating. Step ``p`` maps to local hour
    ``(hod0 + p·res/60) % 24`` — the window is selected in LOCAL hours (the
    2026-07-07 phase fix) at the step resolution (the granularity fix).

    Args:
        load_kw: ``(N_DAYS·steps_per_day,)`` feeder load in kW.
        rating_kw: Usable rating in kW.
        tday_mean_c: ``(365,)`` per-day mean temperatures.
        hod0: LOCAL hour-of-day of array position 0 (:func:`tmy_hour_of_day`).
        res_minutes: Step width in minutes (governed stages pass 15).

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
    steps_per_hour = 60 // int(res_minutes)
    steps_per_day = 24 * steps_per_hour
    local_hour = (int(hod0) + np.arange(steps_per_day) // steps_per_hour) % 24
    window = (local_hour >= start) & (local_hour < end)
    daily = np.asarray(load_kw, dtype=DTYPE)[: N_DAYS * steps_per_day].reshape(
        N_DAYS, steps_per_day
    )
    evening_peaks = daily[cold_days][:, window].max(axis=1)
    return float(np.percentile(evening_peaks / float(rating_kw) * 100.0, 95))


def firm_annual(
    base: np.ndarray,
    ev_pool: np.ndarray,
    rating_kw: float,
    tday_mean_c: np.ndarray,
    *,
    hod0: int = 0,
    res_minutes: int = 60,
) -> dict[str, Any]:
    """Return the study-B firm hosting count and its P95 curve.

    ``firm`` = the largest pool prefix n whose P95 cold-day evening loading is
    at or below ``FIRM_P95_LIMIT_PERCENT`` (curtailment-free hosting, D-B5).

    Args:
        base: ``(horizon,)`` feeder base in kW.
        ev_pool: ``(pool, horizon)`` per-EV demand pool (prefix sweeps).
        rating_kw: Usable rating in kW.
        tday_mean_c: ``(365,)`` per-day mean temperatures.
        hod0: LOCAL hour-of-day of array position 0 (:func:`tmy_hour_of_day`).
        res_minutes: Step width in minutes (governed stages pass 15).

    Returns:
        Dict with ``firm_ev_count`` (int), ``p95_curve`` (list, index = EV
        count 0..pool), ``limit_percent``, ``hod0`` and ``res_minutes``.
    """
    pool = np.asarray(ev_pool, dtype=DTYPE)
    curve: list[float] = []
    cumulative = np.zeros(pool.shape[1], dtype=DTYPE)
    curve.append(
        p95_cold_evening_loading(
            base, rating_kw, tday_mean_c, hod0=hod0, res_minutes=res_minutes
        )
    )
    for ev in range(pool.shape[0]):
        cumulative = cumulative + pool[ev]
        curve.append(
            p95_cold_evening_loading(
                base + cumulative,
                rating_kw,
                tday_mean_c,
                hod0=hod0,
                res_minutes=res_minutes,
            )
        )
    passing = [n for n, p95 in enumerate(curve) if p95 <= float(FIRM_P95_LIMIT_PERCENT)]
    return {
        "firm_ev_count": int(passing[-1]) if passing else 0,
        "p95_curve": [round(float(v), 6) for v in curve],
        "limit_percent": float(FIRM_P95_LIMIT_PERCENT),
        "hod0": int(hod0),
        "res_minutes": int(res_minutes),
    }

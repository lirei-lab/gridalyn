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

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    ARRIVAL_CLIP_ANNUAL,
    ARRIVAL_MEAN_ANNUAL_H,
    ARRIVAL_STD_ANNUAL_H,
    BG_SCALE,
    CALENDAR_HOURS,
    CHARGER_MIX,
    COLD_DAY_TMEAN_C,
    DHW_BASE_WEIGHT,
    DHW_DAILY_L_MEAN,
    DHW_DAILY_L_MIN,
    DHW_DAILY_L_STD,
    DHW_DEADBAND_JITTER_C,
    DHW_ELEMENT_JITTER_KW,
    DHW_ELEMENT_KW,
    DHW_EVENING_AMP,
    DHW_EVENING_HOUR,
    DHW_EVENING_SIGMA,
    DHW_INLET_MAX_C,
    DHW_INLET_MIN_C,
    DHW_MORNING_AMP,
    DHW_MORNING_HOUR,
    DHW_MORNING_SIGMA,
    DHW_SEED_SALT,
    DHW_SETPOINT_JITTER_C,
    DHW_T_AMB,
    DHW_T_LOW,
    DHW_T_SET,
    DHW_TANK_L,
    DHW_TANK_L_JITTER_L,
    DHW_UA_KW_PER_K,
    DTYPE,
    E_TREF_C,
    EV_KWH_BASE,
    EV_KWH_KCOLD,
    EV_SIGMA_LOG,
    EVENING_WINDOW_ANNUAL,
    FIRM_P95_LIMIT_PERCENT,
    P_HEAT_QUEBEC,
    POWER_FACTOR,
    RATING_CONVENTION,
    PLUGIN_BASE,
    PLUGIN_KCOLD,
    PLUGIN_MAX,
    R_STUDY_B,
    RAMP_HORIZON_YEARS,
    RAMP_MAX_EV_PER_HOME,
    RAMP_MIDPOINT_YEAR,
    RAMP_SHAPE,
    RAMP_STEEPNESS,
    TMY_INPUT_PATH,
    TRANSFORMER_KVA,
    TRIAGE_HOTSPOT_LIMIT_C,
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


def cold_capability_curve(
    temp_hourly: pd.Series, *, res_minutes: int = ANNUAL_RES_MINUTES
) -> np.ndarray:
    """Return K(T) per step: usable capability relative to the 30 °C nameplate.

    IEEE C57.91 steady-state hot-spot model held at
    ``TRIAGE_HOTSPOT_LIMIT_C`` (normal insulation life). A transformer in a
    −22 °C ambient sheds heat far better than at the 30 °C basis its nameplate
    assumes, so it carries more current before reaching the same hot spot.

    Args:
        temp_hourly: The committed TMY ambient series (8760 h).
        res_minutes: Step width the curve is expanded to.

    Returns:
        ``(N_DAYS · 24·60/res,)`` multiplier on the nameplate rating.
    """
    from gridalyn.assets.modeling.transformers import TransformerThermalModel

    steps_per_hour = 60 // int(res_minutes)
    temp = np.repeat(
        temp_hourly.to_numpy(dtype=DTYPE)[:CALENDAR_HOURS], steps_per_hour
    )
    model = TransformerThermalModel(theta_max=float(TRIAGE_HOTSPOT_LIMIT_C))
    ref = float(model.max_load_for_temp(30.0))
    rounded = np.round(temp, 1)
    table = {
        t: float(model.max_load_for_temp(float(t))) / ref for t in np.unique(rounded)
    }
    return np.array([table[t] for t in rounded], dtype=DTYPE)


def feeder_rating(
    temp_hourly: pd.Series,
    *,
    kva: float = TRANSFORMER_KVA,
    res_minutes: int = ANNUAL_RES_MINUTES,
) -> tuple[float, np.ndarray | None]:
    """Return ``(nameplate_kw, rating_series)`` per the declared convention.

    ONE place decides how the study judges a transformer against its limit.
    Callers pass both results straight through to the kernels: the scalar keeps
    error messages and reports meaningful, and ``rating_series`` is ``None``
    under the 'static' convention so the scalar code path runs unchanged.

    Args:
        temp_hourly: The committed TMY ambient series.
        kva: Transformer nameplate (default: the governed feeder unit).
        res_minutes: Step width of the annual arrays.

    Returns:
        ``(usable kW at nameplate, per-step rating in kW or None)``.

    Raises:
        ValueError: If ``RATING_CONVENTION`` is not a recognised convention.
    """
    nameplate_kw = float(kva) * float(POWER_FACTOR)
    if RATING_CONVENTION == "static":
        return nameplate_kw, None
    if RATING_CONVENTION == "hourly_kt":
        return nameplate_kw, nameplate_kw * cold_capability_curve(
            temp_hourly, res_minutes=res_minutes
        )
    raise ValueError(
        f"RATING_CONVENTION={RATING_CONVENTION!r} is not recognised; expected "
        "'hourly_kt' (IEEE C57.91 capability at each step's ambient) or "
        "'static' (nameplate). Remediation: set it in config.py."
    )


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


def climate_bin_days(
    temp_hourly: pd.Series, bin_edges: Sequence[float]
) -> list[dict[str, Any]]:
    """Group the year's days into daily-mean-temperature bins.

    Args:
        temp_hourly: Hourly ambient series for the year (24 values per day).
        bin_edges: Ascending bin edges (°C); days fall in half-open
            ``[edge_i, edge_{i+1})`` bins.

    Returns:
        One dict per NON-empty bin, ascending by ``bin_lo``:
        ``{"bin_lo", "bin_hi", "day_idx" (median-temp day), "mean_temp_c"
        (that day's mean), "n_days", "day_indices" (all day indices in the bin)}``.
    """
    # Compute daily mean temperatures (flexible for any hourly length).
    arr = temp_hourly.to_numpy(dtype=DTYPE)
    n_hours = arr.size
    n_days = n_hours // 24
    tday = arr[: n_days * 24].reshape(n_days, 24).mean(axis=1)

    out: list[dict[str, Any]] = []
    edges = list(bin_edges)
    for lo, hi in zip(edges[:-1], edges[1:]):
        members = np.where((tday >= lo) & (tday < hi))[0]
        if members.size == 0:
            continue
        member_temps = tday[members]
        # median-temperature day (lower-median for even counts, deterministic)
        order = members[np.argsort(member_temps, kind="stable")]
        median_day = int(order[(order.size - 1) // 2])
        out.append(
            {
                "bin_lo": float(lo),
                "bin_hi": float(hi),
                "day_idx": median_day,
                "mean_temp_c": float(tday[median_day]),
                "n_days": int(members.size),
                "day_indices": [int(d) for d in members],
            }
        )
    return out


def valley_fill_shift(
    net_load_kw: np.ndarray,
    ev_energy_kwh: np.ndarray,
    rating_kw: float | np.ndarray,
    charger_kw: np.ndarray,
) -> np.ndarray:
    """Redistribute enrolled EVs' daily energy into the lowest-net-load hours.

    Greedy water-filling: raise the lowest ``net_load_kw`` hours toward
    ``rating_kw`` (bounded by the aggregate charger power) until the total
    enrolled energy is placed. If the energy does not fit under the rating (no
    valley), the residual stacks on the least-loaded remaining hours up to the
    charger cap — i.e. shift cannot relieve the peak (the physical point).
    Energy is preserved exactly.

    Args:
        net_load_kw: ``(H,)`` base + non-enrolled load (kW).
        ev_energy_kwh: ``(E,)`` per-enrolled-EV daily energy (kWh; hourly steps).
        rating_kw: Feeder usable rating (kW). May be a scalar or a
            per-hour array when the rating follows the ambient
            (see ``RATING_CONVENTION``); the valley is then filled
            toward each hour's OWN limit.
        charger_kw: ``(E,)`` per-enrolled-EV charger power (kW).

    Returns:
        ``(H,)`` aggregate shifted EV kW profile (sums to the total energy).
    """
    net = np.asarray(net_load_kw, dtype=DTYPE)
    horizon = net.shape[0]
    total_e = float(np.sum(ev_energy_kwh))
    cap = float(np.sum(charger_kw))  # aggregate per-hour power cap
    agg = np.zeros(horizon, dtype=DTYPE)
    remaining = total_e
    # Pass 1: fill under the rating, lowest-load hours first.
    for h in np.argsort(net, kind="stable"):
        if remaining <= 1e-12:
            break
        rate_h = float(np.asarray(rating_kw).reshape(-1)[h % np.asarray(rating_kw).size])
        headroom = min(max(rate_h - float(net[h]), 0.0), cap)
        put = min(headroom, remaining)
        agg[h] = put
        remaining -= put
    # Pass 2 (no valley): stack the residual on the least-loaded resulting hours.
    if remaining > 1e-9:
        for h in np.argsort(net + agg, kind="stable"):
            if remaining <= 1e-12:
                break
            put = min(cap - float(agg[h]), remaining)
            put = max(put, 0.0)
            agg[h] += put
            remaining -= put
    return agg


def adoption_at_year(year: float) -> float:
    """EV/home adoption at ``year`` under the configured ramp (logistic S-curve
    0 -> RAMP_MAX_EV_PER_HOME, or linear over RAMP_HORIZON_YEARS)."""
    mx = float(RAMP_MAX_EV_PER_HOME)
    if str(RAMP_SHAPE) == "linear":
        return float(np.clip(mx * float(year) / float(RAMP_HORIZON_YEARS), 0.0, mx))
    k, m = float(RAMP_STEEPNESS), float(RAMP_MIDPOINT_YEAR)
    return float(mx / (1.0 + np.exp(-k * (float(year) - m))))


def year_at_adoption(adoption: float) -> float:
    """Inverse of :func:`adoption_at_year`: the year the ramp first reaches
    ``adoption``. Returns 0.0 at/below 0 and ``inf`` at/above the ceiling
    (never reached in finite time)."""
    mx = float(RAMP_MAX_EV_PER_HOME)
    a = float(adoption)
    if a <= 0.0:
        return 0.0
    if a >= mx:
        return float("inf")
    if str(RAMP_SHAPE) == "linear":
        return a / mx * float(RAMP_HORIZON_YEARS)
    k, m = float(RAMP_STEEPNESS), float(RAMP_MIDPOINT_YEAR)
    return float(m - (1.0 / k) * np.log(mx / a - 1.0))


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
    agg = sum(
        results[uid]["p_heat_kw"]
        + results[uid]["p_cool_kw"]
        + BG_SCALE * results[uid]["p_bg_kw"]
        for uid in results
    )
    stepped = agg.resample(f"{int(res_minutes)}min").mean().to_numpy(dtype=DTYPE)
    dhw = dhw_tank_annual(
        np.random.default_rng(int(seed) + DHW_SEED_SALT),
        int(n_homes),
        temp,
        res_minutes=int(res_minutes),
    )
    stepped = stepped + dhw[: stepped.shape[0]]
    n_steps = N_DAYS * (24 * 60 // int(res_minutes))
    # The 1-min resample ends at the TMY's last hourly stamp, so the final
    # ``60/res - 1`` steps of the year (the last <1 h) have no interpolation
    # anchor; deterministically edge-pad to the full step grid (those steps are
    # the 23:xx tail of Dec 31, never a binding cold-evening slot).
    if stepped.shape[0] < n_steps:
        stepped = np.pad(stepped, (0, n_steps - stepped.shape[0]), mode="edge")
    return stepped[:n_steps].astype(DTYPE)


def design_day_base_per_home(
    temp_hourly: pd.Series,
    n_homes: int,
    seed: int,
    design_day_idx: int,
    *,
    lead_days: int = 1,
) -> np.ndarray:
    """Return the design day's ``(24,)`` per-home base profile in LOCAL-hour order.

    Simulates the SDK agent over the ``[design_day_idx − lead_days …
    design_day_idx]`` window at 1-min (the lead gives the thermostats real
    burn-in state), aggregates the DESIGN day to hourly means, divides by
    ``n_homes``, and reorders by local hour-of-day (index h = local clock hour
    h). Used by the network-wide AC family to give each transformer the
    diversified per-home base of ITS OWN downstream-home count — the honest
    replacement for broadcasting the 6-home feeder profile (2026-07-07).

    Args:
        temp_hourly: Output of :func:`load_annual_tmy`.
        n_homes: Downstream-home count of the transformer size being modeled.
        seed: Per-size reproducible seed.
        design_day_idx: Day-of-year index of the design (coldest) day.
        lead_days: Burn-in lead days prepended to the window.

    Returns:
        A ``(24,)`` float64 per-home hourly base trace in kW, local-hour-ordered.

    Raises:
        ImportError: If the SDK agent cannot be imported (no silent fallback).
    """
    try:
        from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
    except ImportError as exc:  # no silent fallback (T-13-03)
        raise ImportError(
            "design_day_base_per_home could not import the SDK building "
            f"generator. Remediation: install the gridalyn SDK. Error: {exc}"
        ) from exc

    start = max(0, int(design_day_idx) - int(lead_days))
    window = temp_hourly.iloc[start * 24 : (int(design_day_idx) + 1) * 24]
    window_1min = window.resample("1min").interpolate()

    buildings = make_buildings(int(n_homes), seed=int(seed))
    for building in buildings:
        building.R = R_STUDY_B
        building.p_heat_max = P_HEAT_QUEBEC
    results = simulate_buildings(
        buildings, window_1min, burnin_hours=6, random_seed=int(seed)
    )
    agg = sum(
        results[uid]["p_heat_kw"]
        + results[uid]["p_cool_kw"]
        + BG_SCALE * results[uid]["p_bg_kw"]
        for uid in results
    )
    hourly = agg.resample("60min").mean()
    dhw = dhw_tank_annual(
        np.random.default_rng(int(seed) + DHW_SEED_SALT),
        int(n_homes),
        window,
        res_minutes=60,
    )
    hourly = hourly + dhw[: len(hourly)]
    # keep only the design day, reorder by local hour-of-day
    design_day = hourly.iloc[-24:]
    per_home = design_day.to_numpy(dtype=DTYPE) / float(n_homes)
    local_hours = design_day.index.hour.to_numpy()
    ordered = np.zeros(24, dtype=DTYPE)
    ordered[local_hours] = per_home
    return ordered


def dhw_draw_profile() -> np.ndarray:
    """Return the normalized ``(24,)`` continuous hot-water draw profile by local
    hour: an all-day baseline plus smooth morning and evening occupancy Gaussians
    (no zero hours). Replaces the sparse on/off DHW_DRAW_WEIGHTS whose coincident
    on/off produced an unphysical aggregate step."""
    h = np.arange(24, dtype=DTYPE)
    w = (
        float(DHW_BASE_WEIGHT)
        + float(DHW_MORNING_AMP)
        * np.exp(-0.5 * ((h - float(DHW_MORNING_HOUR)) / float(DHW_MORNING_SIGMA)) ** 2)
        + float(DHW_EVENING_AMP)
        * np.exp(-0.5 * ((h - float(DHW_EVENING_HOUR)) / float(DHW_EVENING_SIGMA)) ** 2)
    )
    return (w / w.sum()).astype(DTYPE)


def dhw_tank_annual(
    rng: np.random.Generator,
    n_homes: int,
    temp_hourly: pd.Series,
    *,
    res_minutes: int = ANNUAL_RES_MINUTES,
) -> np.ndarray:
    """Return one stochastic electric DHW-tank feeder trace ``(n_steps,)`` kW.

    Per home: a single-node thermostatic hot-water tank whose parameters (tank
    volume, element power, setpoint, deadband) are drawn per home with jitter
    around ``DHW_TANK_L``/``DHW_ELEMENT_KW``/``DHW_T_SET``/``DHW_T_LOW``. Draws
    follow the continuous ``dhw_draw_profile()`` occupancy curve (all-day baseline
    + smooth morning/evening peaks, no zero hours); per step the draw removes hot
    water (energy ``V*cp*(T-T_inlet)``), standby loses ``UA*(T-T_amb)``, and the
    element reheats toward the home's setpoint when ``T`` falls below its cut-in.
    The smooth profile + per-home diversity STAGGER the reheats so the aggregate
    has no coincident on/off step (the 2026-07-16 realism fix). Deterministic
    given ``rng``. Project-local — no SDK import.

    The SDK now hosts the canonical form of this model as
    ``gridalyn.assets.datagen.agents.make_dhw_tank_fleet``, parameterised by
    ``DHWTankParams``/``DHWDrawProfile`` instead of module constants. This
    project-local copy is retained DELIBERATELY: switching to the SDK kernel
    changes the RNG stream and would re-base all 81 pinned metrics of this
    study. Migrating is a separate, deliberate decision, not a tidy-up.

    Args:
        rng: Pinned generator (derive from the base seed in the caller).
        n_homes: Dwelling count (feeder aggregate = sum of the per-home tanks).
        temp_hourly: Outdoor TMY series (drives the seasonal cold-water inlet).
        res_minutes: Step resolution in minutes.

    Returns:
        A ``(n_steps,)`` float64 feeder-aggregate DHW trace in kW, where
        ``n_steps`` matches ``temp_hourly`` resampled to ``res_minutes``.
    """
    res = int(res_minutes)
    steps_per_day = 24 * 60 // res
    steps_per_hour = max(1, steps_per_day // 24)
    dt_h = res / 60.0
    cp = 4.186  # kJ/(kg*K); 1 L water ~ 1 kg
    # LOCAL-hour phase anchor: array position p is local clock hour
    # (hod0 + p) % 24 (the study-B _HOD0 convention; the TMY starts 19:00 local).
    # The occupancy draw weights are clock-hour keyed, so they MUST be shifted by
    # hod0 or the morning/evening reheat peak lands ~5 h early.
    hod0 = int(temp_hourly.index[0].hour)

    t_res = (
        temp_hourly.resample(f"{res}min").interpolate().to_numpy(dtype=DTYPE)
    )
    n_steps = int(t_res.shape[0])
    inlet = DHW_INLET_MIN_C + (DHW_INLET_MAX_C - DHW_INLET_MIN_C) * np.clip(
        (t_res + 20.0) / 50.0, 0.0, 1.0
    )

    weights = dhw_draw_profile()

    t_amb = float(DHW_T_AMB)
    ua = float(DHW_UA_KW_PER_K)
    base_deadband = float(DHW_T_SET) - float(DHW_T_LOW)

    feeder = np.zeros(n_steps, dtype=DTYPE)
    for _ in range(int(n_homes)):
        daily_l = max(
            float(DHW_DAILY_L_MIN),
            float(rng.normal(DHW_DAILY_L_MEAN, DHW_DAILY_L_STD)),
        )
        # per-home tank diversity (fixed draw order for determinism)
        t_set = float(rng.normal(DHW_T_SET, DHW_SETPOINT_JITTER_C))
        deadband = max(1.0, float(rng.normal(base_deadband, DHW_DEADBAND_JITTER_C)))
        t_low = t_set - deadband
        element = max(1.0, float(rng.normal(DHW_ELEMENT_KW, DHW_ELEMENT_JITTER_KW)))
        tank_l = max(100.0, float(rng.normal(DHW_TANK_L, DHW_TANK_L_JITTER_L)))
        c_tank = tank_l * cp / 3600.0  # kWh/K
        tank = t_set
        for k in range(n_steps):
            hod = (hod0 + k // steps_per_hour) % 24
            exp_l = daily_l * float(weights[hod]) / steps_per_hour
            vol = float(rng.gamma(2.0, exp_l / 2.0)) if exp_l > 0.0 else 0.0
            e_draw = vol * cp * (tank - float(inlet[k])) / 3600.0
            e_loss = ua * (tank - t_amb) * dt_h
            tank -= (e_draw + e_loss) / c_tank
            if tank < t_low:
                e_in = min(element * dt_h, c_tank * (t_set - tank))
                tank += e_in / c_tank
                feeder[k] += e_in / dt_h
    return feeder.astype(DTYPE)


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
    plugin_kcold: float = PLUGIN_KCOLD,
    ev_kwh_kcold: float = EV_KWH_KCOLD,
) -> np.ndarray:
    """Return the per-EV annual demand pool ``(n_evs, n_steps)`` kW.

    Ports study-B ``fleet()`` (D-B4): per EV per day, the plug-in probability
    and the lognormal session energy BOTH rise with the day's cold intensity;
    arrival is an evening Gaussian; the session charges at the sampled charger
    power with exact MINUTE overlap allocation into ``res_minutes`` bins,
    phase-aligned to the TMY's hour-of-day anchor. Each stored value is the
    step's AVERAGE kW (``occupied_fraction × charger_kw``), so
    ``sum(step_kW) × res/60`` reproduces the session energy.

    The SDK now hosts the canonical form of this model as
    ``gridalyn.assets.datagen.agents.make_cold_coupled_ev_fleet`` — window- and
    resolution-agnostic, driven by real timestamps rather than an ``hod0``
    phase anchor. This project-local copy is retained DELIBERATELY: switching
    to the SDK kernel changes the RNG stream and would re-base all 81 pinned
    metrics of this study. Migrating is a separate, deliberate decision, not a
    tidy-up.

    The cold-coupling slopes are parameters so a NAIVE (cold-agnostic) fleet —
    the cold-coupling comparison's counterfactual — is generated by passing
    ``plugin_kcold=0`` and ``ev_kwh_kcold=0`` (the plug-in probability and
    session energy then stay at their mild-day values year-round, the standard
    hosting-study assumption).

    Args:
        rng: Pinned generator (``default_rng(SEED)`` in the stage).
        n_evs: Pool size (``POOL_MAX_ANNUAL``).
        tday_mean_c: ``(365,)`` per-day mean temperatures.
        hod0: TMY hour-of-day phase anchor (:func:`tmy_hour_of_day`).
        res_minutes: Step width in minutes (default: the governed resolution).
        plugin_kcold: Plug-in-probability cold slope (default: governed;
            0 disables the plug-in cold coupling).
        ev_kwh_kcold: Session-energy cold slope (default: governed; 0 disables
            the session-energy cold coupling).

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
            plug_p = min(float(PLUGIN_MAX), float(PLUGIN_BASE) + float(plugin_kcold) * cp)
            if rng.random() > plug_p:
                continue
            charger_kw = float(rng.choice(chargers, p=shares))
            median_kwh = float(EV_KWH_BASE) * (1.0 + float(ev_kwh_kcold) * cp)
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
    rating_series: np.ndarray | None = None,
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
        rating_series: Optional ``(horizon,)`` per-step usable rating in kW,
            overriding ``rating_kw``. Use it to carry a temperature-dependent
            rating (IEEE C57.91): in a heating-dominated system the load peak
            and the thermal capability are both driven by ambient temperature,
            so a fixed nameplate judges a winter peak against a 30 °C basis.
            ``None`` keeps the scalar behaviour exactly.

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
    # A transformer's usable rating depends on its ambient: in a cold climate
    # the peak and the thermal capability are driven by the SAME variable and
    # rise together. `rating_series` opts into that (IEEE C57.91 K(T)); when it
    # is None the scalar path below is unchanged, so governed callers that pass
    # a nameplate keep byte-identical results.
    if rating_series is None:
        rating_t = np.full(horizon, float(rating_kw), dtype=DTYPE)
    else:
        rating_t = np.asarray(rating_series, dtype=DTYPE)
        if rating_t.shape != (horizon,):
            raise ValueError(
                f"simulate_curtailment received rating_series {rating_t.shape}, "
                f"expected ({horizon},) matching the load horizon. Remediation: "
                "build it as rating_kw × K(ambient) at the same resolution."
            )

    curtailed = np.zeros(n_evs, dtype=DTYPE)  # kWh
    events = np.zeros(n_evs, dtype=int)
    curtailed_steps = np.zeros(horizon, dtype=bool)
    residual_steps = 0
    free_draw = demand[~enrolled, :].sum(axis=0)
    served_ev_kw = demand.sum(axis=0).astype(DTYPE)  # curtailments subtract below
    for t in range(horizon):
        cap_t = float(rating_t[t])
        headroom = cap_t - (base[t] + free_draw[t])
        if base[t] <= cap_t and (base[t] + free_draw[t]) > cap_t:
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
        "base_floor_hours": float((base > rating_t).sum()) * hours_per_step,
        "served_ev_kw": served_ev_kw,
    }


def p95_cold_evening_loading(
    load_kw: np.ndarray,
    rating_kw: float,
    tday_mean_c: np.ndarray,
    *,
    hod0: int = 0,
    res_minutes: int = 60,
    rating_series: np.ndarray | None = None,
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
    if rating_series is None:
        evening_peaks = daily[cold_days][:, window].max(axis=1)
        return float(np.percentile(evening_peaks / float(rating_kw) * 100.0, 95))
    # Time-varying rating: divide BEFORE taking the window max. With a rating
    # that moves, the peak LOAD step is not necessarily the peak LOADING step —
    # in a cold climate the biggest load lands in the coldest hour, which is
    # also the hour of greatest capability.
    rating_t = np.asarray(rating_series, dtype=DTYPE)
    pct = np.asarray(load_kw, dtype=DTYPE)[: N_DAYS * steps_per_day] / rating_t[
        : N_DAYS * steps_per_day
    ] * 100.0
    daily_pct = pct.reshape(N_DAYS, steps_per_day)
    return float(np.percentile(daily_pct[cold_days][:, window].max(axis=1), 95))


def firm_annual(
    base: np.ndarray,
    ev_pool: np.ndarray,
    rating_kw: float,
    tday_mean_c: np.ndarray,
    *,
    hod0: int = 0,
    res_minutes: int = 60,
    rating_series: np.ndarray | None = None,
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
            base, rating_kw, tday_mean_c, hod0=hod0, res_minutes=res_minutes,
            rating_series=rating_series,
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
                rating_series=rating_series,
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

"""Design-day Monte-Carlo generation kernel for ``ev_hosting_flex`` (Phase 13).

The empirical crux of the v1.3 generative-MC transformer pivot (GEN-01..04). This
module is the governed port of the validated 2026-06-26 throwaway probes
(``.planning/tmp/exp_firmsweep.py`` / ``exp_genseam.py``): it selects the binding
cold design day from the committed Trois-Rivières TMY, recalibrates the SDK
building agent to the Québec all-electric archetype, draws the project-local MDPI
EV truth in a nested/cumulative pool, and assembles the idx-62 transformer-load
ensemble ``Q_real (K, n_steps)`` plus the day-ahead forecast ``Q_design``.

The operating point is EMPIRICALLY LOCKED (``R = 7.0`` °C/kW, ``p_heat_max = 13.0``
kW, design day ``1990-01-19``, EV-free base ~82–87% of the 71.25 kW rating /
~8.4 kW/home, firm=3, no CLPU): this kernel IMPLEMENTS it byte-stably — it does not
re-discover or re-tune it. See ``config.R_QUEBEC`` / ``config.P_HEAT_QUEBEC`` and
``CALIBRATION.md`` (Generative-MC design-day seam, Phase 13).

Determinism contract (GEN-01, feeds SEAL-01): every random draw flows through an
explicit ``np.random.Generator`` seeded from ``config.SEED`` (never the global
``np.random``); the per-EV MDPI draw order is pinned (the byte-stability contract);
all arrays are float64; rounding happens only at write-time (callers/stage round
via ``config.ROUND_DECIMALS`` — this kernel returns unrounded float64). Two calls
with the same seed return byte-identical arrays.

GUARD-02 / no-silent-fallback (GEN-01): there are NO module-scope heavy imports.
The SDK building agent (``make_buildings`` / ``simulate_buildings``) and
``select_peak_load_day`` are imported DEFERRED inside the functions that use them
(the ``_twostage.py`` ``require_capabilities`` precedent), and the governed path
RAISES (``MissingCapabilityError`` or a located ``ImportError``) if a required SDK
symbol is unavailable — it NEVER substitutes a hand-rolled base.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts._stochastic import _session
from projects.ev_hosting_flex.scripts.config import (
    ARRIVAL_CLIP,
    ARRIVAL_MEAN_H,
    ARRIVAL_STD_H,
    CHARGER_MIX,
    DESIGN_DAY_EV_MAX,
    DESIGN_DAY_RES_MINUTES,
    DTYPE,
    EV_KWH_MEDIAN,
    EV_KWH_MIN,
    EV_KWH_SIGMA,
    K_DESIGN,
    N_HOMES_FALLBACK,
    P_HEAT_QUEBEC,
    PLUGIN_PROB,
    R_QUEBEC,
    SEED,
    SIGMA_DAILY,
    SIGMA_HOURLY,
    TMY_INPUT_PATH,
)

# Charger value/probability arrays built ONCE, sorted by key for determinism so
# rng.choice draws from a stable, reproducible support (mirrors _stochastic). The
# probabilities are renormalized in case the mix shares do not sum to exactly 1.0.
_CHG_KW = np.array(sorted(CHARGER_MIX), dtype=DTYPE)
_CHG_P = np.array([CHARGER_MIX[k] for k in _CHG_KW], dtype=DTYPE)
_CHG_P = _CHG_P / _CHG_P.sum()

# Per-realization EV-pool seed stride (a large prime) so the nested-EV pool for
# realization ``r`` is keyed independently of the building seed ``SEED + r`` yet
# stays byte-stable and reproducible — ported from the probes' ``SEED + 7919 * r``.
_EV_SEED_STRIDE = 7919


def load_design_tmy(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return the committed Trois-Rivières TMY with a tz-aware ``DatetimeIndex``.

    Reads the committed project-local CSV (``config.TMY_INPUT_PATH``) — never a
    network weather download / ``download_tmy()`` auto-fetch (the REPRO guard
    inherited from ``_stochastic.tmy_base``). The ``timestamp`` column carries a
    UTC-offset string (``-05:00``); it is parsed ``utc=True`` and set as the index
    so ``select_peak_load_day`` can resample/window it.

    Args:
        df: Optional pre-loaded TMY frame (tests inject malformed frames); when
            ``None`` the committed ``TMY_INPUT_PATH`` CSV is read.

    Returns:
        A copy of the TMY frame indexed by a tz-aware ``DatetimeIndex`` with a
        ``temp_air`` column (°C).

    Raises:
        ValueError: If the frame is missing the ``timestamp`` / ``temp_air``
            column or has fewer than 24 hourly rows (located + remediating —
            never silently truncating; T-13-01).
    """
    if df is None:
        df = pd.read_csv(TMY_INPUT_PATH)
    missing = [c for c in ("timestamp", "temp_air") if c not in df.columns]
    if missing:
        raise ValueError(
            "load_design_tmy received a TMY frame missing required column(s) "
            f"{missing} (have {list(df.columns)}); cannot select the design day. "
            "Remediation: regenerate / re-copy the committed TMY at "
            f"{TMY_INPUT_PATH} with 'timestamp' and 'temp_air' columns (PVGIS "
            "SARAH-3 schema)."
        )
    if len(df) < 24:
        raise ValueError(
            f"load_design_tmy received a short TMY frame ({len(df)} rows); the "
            "design-day selection needs at least a full winter year of hourly "
            "rows and refuses to silently truncate. Remediation: re-copy the full "
            f"8760-row committed TMY at {TMY_INPUT_PATH}."
        )
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.set_index("timestamp")


def select_design_day(tmy: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return the binding cold design day at the TMY's native (1-min) resolution.

    Thin wrapper over the SDK ``select_peak_load_day`` (deferred import; GUARD-02):
    over the committed Trois-Rivières TMY it selects the occupied-HDH peak-demand
    day, empirically **1990-01-19** (−20.1 °C mean), returned as a 1-min frame with
    a ``temp_air`` column.

    Args:
        tmy: Optional pre-loaded tz-aware TMY frame (``load_design_tmy`` output);
            when ``None`` the committed TMY is loaded.

    Returns:
        A 1-min ``DataFrame`` (``temp_air`` column, tz-aware ``DatetimeIndex``)
        for the design day.

    Raises:
        ImportError: If the SDK ``select_peak_load_day`` cannot be imported (the
            no-silent-fallback guard — never substitutes a hand-rolled selector).
    """
    if tmy is None:
        tmy = load_design_tmy()
    try:
        from gridalyn.assets.datagen.data.weather import select_peak_load_day
    except ImportError as exc:  # no silent fallback (GEN-01 / T-13-03)
        raise ImportError(
            "select_design_day could not import the SDK "
            "'gridalyn.assets.datagen.data.weather.select_peak_load_day'; the "
            "governed design-day seam refuses to substitute a hand-rolled "
            "selector. Remediation: install the gridalyn SDK so the design-day "
            f"selection runs against the committed TMY. Original error: {exc}"
        ) from exc
    return select_peak_load_day(tmy)


def recalibrated_buildings(n_homes: int, seed: int) -> list[Any]:
    """Return ``n_homes`` SDK ``Building`` objects recalibrated to the Québec archetype.

    Builds the SDK building population via ``make_buildings(n_homes, seed)`` (deferred
    import; GUARD-02), then overrides each ``Building.R`` to ``config.R_QUEBEC``
    (7.0 °C/kW) and ``Building.p_heat_max`` to ``config.P_HEAT_QUEBEC`` (13.0 kW) —
    the LOCKED GEN-02 operating point (the SDK defaults ``R ≈ 11`` / ``p_heat_max ≤
    8`` under-load the 7-home idx-62 unit to ~60% rating; the override lands the
    design-day base at ~82–87% rating / firm=3). No CLPU.

    Args:
        n_homes: Number of all-electric dwellings on the idx-62 subtree.
        seed: The reproducible per-realization building seed (``SEED + r``).

    Returns:
        A list of ``n_homes`` recalibrated ``Building`` objects.

    Raises:
        ImportError: If the SDK ``make_buildings`` cannot be imported (no silent
            fallback — never substitutes a hand-rolled building model; T-13-03).
    """
    try:
        from gridalyn.assets.datagen.agents import make_buildings
    except ImportError as exc:  # no silent fallback (GEN-01 / T-13-03)
        raise ImportError(
            "recalibrated_buildings could not import the SDK "
            "'gridalyn.assets.datagen.agents.make_buildings'; the governed "
            "design-day seam refuses to substitute a hand-rolled building base. "
            "Remediation: install the gridalyn SDK so the recalibrated building "
            f"agent drives the design-day base. Original error: {exc}"
        ) from exc
    buildings = make_buildings(int(n_homes), seed=int(seed))
    for b in buildings:
        b.R = R_QUEBEC
        b.p_heat_max = P_HEAT_QUEBEC
    return buildings


def building_realization(
    design_day: pd.DataFrame,
    n_homes: int,
    seed: int,
    res_minutes: int = DESIGN_DAY_RES_MINUTES,
    *,
    t_offset: np.ndarray | float | None = None,
) -> np.ndarray:
    """Return one feeder-aggregated building base realization in kW (no EV).

    Runs a single ``simulate_buildings`` realization (deferred import; GUARD-02)
    over the design day's 1-min ``temp_air`` series at ``burnin_hours = 6`` /
    ``random_seed = seed``, aggregates ``p_total_kw`` across the ``n_homes``
    dwellings, and resamples to ``res_minutes`` via the mean. Ports
    ``exp_firmsweep.bld_hourly`` (and ``exp_genseam.building_hourly_kw``).

    Args:
        design_day: The 1-min design-day frame (``select_design_day`` output) with
            a ``temp_air`` column and tz-aware ``DatetimeIndex``.
        n_homes: Number of dwellings on the idx-62 subtree.
        seed: The reproducible per-realization seed (``SEED + r``).
        res_minutes: Aggregation resolution in minutes (default
            ``DESIGN_DAY_RES_MINUTES`` = 60 → 24 steps).
        t_offset: Optional day-ahead temperature-forecast-error trace added to the
            outdoor temperature before simulation (a ``(n_1min,)`` array or a
            scalar); ``None`` uses the unperturbed TMY temperature.

    Returns:
        A ``(n_steps,)`` float64 feeder-aggregated building base trace (kW), where
        ``n_steps = 24 * 60 // res_minutes`` for the 24-h design day.

    Raises:
        ImportError: If the SDK ``simulate_buildings`` cannot be imported (no
            silent fallback; T-13-03).
    """
    try:
        from gridalyn.assets.datagen.agents import simulate_buildings
    except ImportError as exc:  # no silent fallback (GEN-01 / T-13-03)
        raise ImportError(
            "building_realization could not import the SDK "
            "'gridalyn.assets.datagen.agents.simulate_buildings'; the governed "
            "design-day seam refuses to substitute a hand-rolled building "
            "simulation. Remediation: install the gridalyn SDK. Original error: "
            f"{exc}"
        ) from exc
    buildings = recalibrated_buildings(n_homes, seed)
    temp = design_day["temp_air"].astype(DTYPE)
    if t_offset is not None:
        temp = temp + np.asarray(t_offset, dtype=DTYPE)
    results = simulate_buildings(buildings, temp, burnin_hours=6, random_seed=int(seed))
    agg = np.zeros(len(design_day), dtype=DTYPE)
    for uid in results:
        agg += results[uid]["p_total_kw"].to_numpy(dtype=DTYPE)
    series = pd.Series(agg, index=design_day.index)
    hourly = series.resample(f"{int(res_minutes)}min").mean().to_numpy(dtype=DTYPE)
    return hourly.astype(DTYPE)


def _ev_session_24h(rng: np.random.Generator) -> np.ndarray:
    """Return one 24h MDPI EV draw (kW) in the PINNED draw order, or zeros if skipped.

    The byte-stability contract (GEN-03): the per-EV draw order is
    ``rng.random()`` (plug-in skip if ``> PLUGIN_PROB``) → ``rng.choice`` (charger
    mix) → ``rng.lognormal`` (session energy, floored at ``EV_KWH_MIN``) →
    ``rng.normal`` (arrival, clipped to ``ARRIVAL_CLIP``). Identical to
    ``_stochastic._ev_day`` for a single EV; reused here so the pool keys off the
    same MDPI stream. The drawn session is placed via the kept ``_session`` shape.

    Args:
        rng: A seeded ``np.random.Generator`` (NEVER the global ``np.random``).

    Returns:
        A ``(24,)`` float64 hourly draw vector (kW); all-zero if the EV skips the
        evening (the plug-in draw is consumed regardless to keep the order pinned).
    """
    if rng.random() > PLUGIN_PROB:  # 1st draw — plug-in (order is load-bearing)
        return np.zeros(24, dtype=DTYPE)
    charger = float(rng.choice(_CHG_KW, p=_CHG_P))  # 2nd — charger mix
    energy = max(  # 3rd — lognormal session energy
        EV_KWH_MIN, rng.lognormal(np.log(EV_KWH_MEDIAN), EV_KWH_SIGMA)
    )
    start = float(  # 4th — Gaussian arrival, clipped
        np.clip(rng.normal(ARRIVAL_MEAN_H, ARRIVAL_STD_H), *ARRIVAL_CLIP)
    )
    return _session(charger, start, energy).astype(DTYPE)


def ev_nested_pool(
    rng: np.random.Generator,
    n_ev_max: int = DESIGN_DAY_EV_MAX,
    res_minutes: int = DESIGN_DAY_RES_MINUTES,
) -> np.ndarray:
    """Return the nested cumulative MDPI EV pool ``(n_ev_max + 1, n_steps)`` in kW.

    Row ``n`` is the aggregate hourly draw for the FIRST ``n`` EVs (a cumulative
    sum), so ``P(overload)`` is MONOTONIC in EV count — adding an EV never removes
    load (GEN-03). Row 0 is all-zero. Each per-EV draw is taken in the pinned MDPI
    order (see ``_ev_session_24h``); the daily 24h shapes are cumulatively summed,
    a zero row is prepended, and the result is mapped to ``n_steps`` matching the
    design-day resolution. Ports ``exp_genseam.ev_nested_cumsum``.

    For the default hourly resolution (``res_minutes = 60``) the 24h ``_session``
    shape maps directly (``n_steps = 24``). For a finer resolution the hourly draw
    is upsampled DETERMINISTICALLY by repeating each hour across its sub-steps
    (a piecewise-constant power hold — the same energy, no extra draws), so the
    draw order (and byte-stability) is untouched.

    Args:
        rng: A seeded ``np.random.Generator`` (NEVER the global ``np.random``).
        n_ev_max: The nested-pool ceiling (default ``DESIGN_DAY_EV_MAX``).
        res_minutes: The design-day resolution in minutes (default
            ``DESIGN_DAY_RES_MINUTES``). Must divide 60 evenly.

    Returns:
        A ``(n_ev_max + 1, n_steps)`` float64 nested cumulative EV pool (kW), where
        ``n_steps = 24 * 60 // res_minutes``.

    Raises:
        ValueError: If ``res_minutes`` does not evenly divide 60 (the 24h hourly
            shape cannot be mapped to sub-hour steps without an integer factor).
    """
    res = int(res_minutes)
    if res <= 0 or 60 % res != 0:
        raise ValueError(
            f"ev_nested_pool received res_minutes={res_minutes!r}; the 24h MDPI "
            "session shape maps to sub-hour steps only for a resolution that "
            "evenly divides 60 (e.g. 5, 10, 15, 30, 60). Remediation: pass "
            "config.DESIGN_DAY_RES_MINUTES or a divisor of 60."
        )
    n_max = int(n_ev_max)
    per_ev = np.zeros((n_max, 24), dtype=DTYPE)
    for j in range(n_max):
        per_ev[j] = _ev_session_24h(rng)
    cum = np.cumsum(per_ev, axis=0)  # (n_max, 24) — row n = first n+1 EVs
    pool_hourly = np.vstack([np.zeros((1, 24), dtype=DTYPE), cum])  # (n_max+1, 24)
    if res == 60:
        return pool_hourly.astype(DTYPE)
    sub = 60 // res  # sub-steps per hour
    # Piecewise-constant power hold: repeat each hour across its sub-steps (same
    # power, hence same energy at the finer step) — deterministic, no extra draws.
    return np.repeat(pool_hourly, sub, axis=1).astype(DTYPE)


def make_q_design(
    q_real: np.ndarray,
    rng: np.random.Generator,
    *,
    sigma_daily: float = SIGMA_DAILY,
    sigma_hourly: float = SIGMA_HOURLY,
) -> np.ndarray:
    """Return the day-ahead forecast ``Q_design (n_steps,)`` of ``Q_real``'s mean.

    A SMOOTHING / forecast of ``Q_real``'s predictable part (GEN-04), NEVER an
    independent load model: the macro shape is a gaussian-smoothed per-step mean of
    the ``Q_real`` ensemble, plus a single day-ahead temperature-forecast-error term
    — one ``N(0, sigma_daily)`` whole-day offset (a small per-step multiplicative
    perturbation derived from the daily °C error) drawn from the supplied dedicated
    seeded ``Generator``. The result tracks ``Q_real.mean(axis=0)`` closely
    (corr ≥ 0.9) so a day-ahead reserve planned on it is meaningful, yet carries the
    genuine forecast uncertainty that makes the downstream scheme two-stage.

    Args:
        q_real: The ``(K, n_steps)`` float64 transformer-load ensemble.
        rng: A dedicated seeded ``np.random.Generator`` for the forecast-error draw
            (NEVER the global ``np.random``).
        sigma_daily: Day-ahead per-day temperature-forecast offset std in °C
            (default ``config.SIGMA_DAILY``); scales the whole-day perturbation.
        sigma_hourly: Per-hour temperature-forecast noise std in °C (default
            ``config.SIGMA_HOURLY``); scales the smoothed per-step perturbation.

    Returns:
        A ``(n_steps,)`` float64 day-ahead forecast trace (kW).
    """
    arr = np.asarray(q_real, dtype=DTYPE)
    mean_shape = arr.mean(axis=0)  # (n_steps,) the predictable per-step mean
    n_steps = mean_shape.shape[0]
    # Gaussian-smooth the macro shape (deferred SDK-free import: scipy is a base
    # numeric dep). A modest sigma keeps the day's coincident peak while removing
    # per-step MC jitter — the forecast is a smoothing, not a re-model.
    from scipy.ndimage import gaussian_filter1d

    macro = gaussian_filter1d(mean_shape, sigma=1.0, mode="nearest")
    # Day-ahead temperature-forecast error: a single whole-day offset + a smoothed
    # per-step noise, expressed as a small fractional perturbation of the macro
    # shape (the forecast does not know the realized weather). The °C errors are
    # mapped to a fractional load perturbation via the design-day base sensitivity
    # (~3%/°C of the predictable mean — heating-dominated), capped so Q_design stays
    # a faithful tracker of the mean (GEN-04).
    frac_per_degc = 0.03
    daily_offset = float(rng.normal(0.0, float(sigma_daily)))
    hourly_noise = rng.normal(0.0, float(sigma_hourly), size=n_steps)
    smooth_hourly = gaussian_filter1d(hourly_noise, sigma=2.0, mode="nearest")
    perturb = 1.0 + frac_per_degc * (daily_offset + smooth_hourly)
    return (macro * perturb).astype(DTYPE)


def make_design_day_ensemble(
    n_homes: int | None = None,
    *,
    k: int = K_DESIGN,
    seed: int = SEED,
    res_minutes: int = DESIGN_DAY_RES_MINUTES,
    n_ev_max: int = DESIGN_DAY_EV_MAX,
    design_day: pd.DataFrame | None = None,
    with_forecast_error: bool = True,
) -> dict[str, Any]:
    """Assemble the design-day MC ensemble: ``Q_real``, ``Q_design`` + the EV pool.

    The K-loop (the structural model of ``flexibility_cls`` stage-00): for each
    realization ``r`` the SDK building agent is re-seeded ``SEED + r`` and (when
    ``with_forecast_error``) an optional smoothed temperature-forecast-error offset
    perturbs the design-day temperature; the recalibrated 7-home building base is
    aggregated to ``Q_real[r]``. A separate, independently-seeded
    (``SEED + _EV_SEED_STRIDE * r``) nested MDPI EV pool is returned per realization
    so the Phase-14 congestion sweep can overlay any EV count up to ``n_ev_max``
    (the building base ensemble is the ``Q_real`` headline; the EV overlay is exposed,
    not summed into ``Q_real``, so the firm denominator is the building base ⊕ count).

    ``Q_design`` is the day-ahead forecast (``make_q_design``) of ``Q_real``'s
    predictable mean, drawn from a dedicated forecast-seeded ``Generator`` so it is
    reproducible and independent of the building/EV streams.

    Determinism (GEN-01): every draw flows through an explicit ``Generator`` keyed
    from ``seed``; float64 throughout; two calls with the same ``seed`` return
    byte-identical ``Q_real`` / ``Q_design`` / ``ev_pool``. No global ``np.random``.

    Args:
        n_homes: Downstream-home count on the idx-62 subtree; ``None`` falls back to
            ``config.N_HOMES_FALLBACK`` (7) for cache-free unit tests.
        k: Monte-Carlo realization count (default ``config.K_DESIGN``).
        seed: The locked base seed (default ``config.SEED``).
        res_minutes: Design-day aggregation resolution (default
            ``config.DESIGN_DAY_RES_MINUTES``).
        n_ev_max: Nested-EV pool ceiling (default ``config.DESIGN_DAY_EV_MAX``).
        design_day: Optional pre-selected 1-min design-day frame (tests/stage may
            inject it to avoid re-selecting); ``None`` selects it via
            ``select_design_day``.
        with_forecast_error: When ``True`` each realization perturbs the design-day
            temperature by a smoothed day-ahead forecast-error trace (the genuine
            two-stage uncertainty); ``False`` runs the unperturbed base.

    Returns:
        A dict with keys:
            ``"Q_real"``: ``(k, n_steps)`` float64 building-base transformer-load
                ensemble (kW).
            ``"Q_design"``: ``(n_steps,)`` float64 day-ahead forecast (kW).
            ``"ev_pool"``: ``(k, n_ev_max + 1, n_steps)`` float64 per-realization
                nested cumulative MDPI EV pool (kW) for the Phase-14 overlay.
            ``"n_homes"``: the resolved home count (int).
            ``"res_minutes"``: the resolution used (int).
            ``"design_date"``: the selected design-day date (``str``).
    """
    homes = int(N_HOMES_FALLBACK if n_homes is None else n_homes)
    if design_day is None:
        design_day = select_design_day()
    n_real = int(k)

    q_real_rows: list[np.ndarray] = []
    ev_rows: list[np.ndarray] = []
    for r in range(n_real):
        t_offset: np.ndarray | None = None
        if with_forecast_error:
            macro_rng = np.random.default_rng(int(seed) + r)
            n_1min = len(design_day)
            from scipy.ndimage import gaussian_filter1d

            noise = macro_rng.normal(0.0, float(SIGMA_HOURLY), n_1min)
            smooth = gaussian_filter1d(noise, sigma=120.0, mode="nearest")
            t_offset = float(macro_rng.normal(0.0, float(SIGMA_DAILY))) + smooth
        q_real_rows.append(
            building_realization(
                design_day, homes, int(seed) + r, res_minutes, t_offset=t_offset
            )
        )
        ev_rng = np.random.default_rng(int(seed) + _EV_SEED_STRIDE * r)
        ev_rows.append(ev_nested_pool(ev_rng, n_ev_max, res_minutes))

    q_real = np.stack(q_real_rows).astype(DTYPE)  # (k, n_steps)
    ev_pool = np.stack(ev_rows).astype(DTYPE)  # (k, n_ev_max+1, n_steps)

    # Q_design from a dedicated forecast-seeded Generator (independent stream).
    design_rng = np.random.default_rng(int(seed) + 1)
    q_design = make_q_design(q_real, design_rng)

    return {
        "Q_real": q_real,
        "Q_design": q_design,
        "ev_pool": ev_pool,
        "n_homes": homes,
        "res_minutes": int(res_minutes),
        "design_date": str(design_day.index[0].date()),
    }

"""Two-stage chance-constrained EV-curtailment numeric kernel for ev_hosting_flex.

The genuinely-new layer of Phase 10.2 (TWOSTAGE-01..07, D-01..D-10): the
manuscript two-stage stochastic program (``twostage_prototype.py``) ported into
the governed pipeline over the Phase-10.1 re-calibrated HQ/TMY/stochastic model.

The program is per-hour-independent:

* ``required_t(ω) = (d_t(ω) + g_t(ω) − S̄)⁺`` — power to curtail to avoid overload.
* Stage 1 (day-ahead): ``r_t = Q_{1−ε}[required_t(·)]`` — reserved cap (TWOSTAGE-01).
* Stage 2 (real-time):  ``a_t(ω) = min(r_t, required_t(ω))`` — activate only what's needed.
* Reported cost: ``c_r·Σ_t r_t + c_a·E_ω[Σ_t a_t(ω)]`` (illustrative prices, D-06).

Because the program decouples per hour and ``c_a > 0``, the optimum is the
CLOSED-FORM ``r* = Q_{1−ε}``, ``a* = min(r*, required)`` — PRICE-INDEPENDENT
(D-06). This closed form (``twostage_oracle``) is the byte-stable reproducibility
ORACLE the user-chosen cvxpy solve (D-08) must reproduce to ≤1e-6, with a
documented fall-back to the oracle if cvxpy diverges or is non-optimal (D-08c).

Scenarios ``ω`` carry BOTH uncertainties (D-03): a day-ahead temperature-forecast
error (a per-day ``N(0, SIGMA_DAILY)`` offset + a per-hour ``N(0, SIGMA_HOURLY)``
noise perturbing the cold TMY day → heating base ``d``) composed with the
Phase-10.1 stochastic EV model (``_stochastic._ev_day`` → ``g``). The EV/heating
physics are REUSED, never re-implemented, so the scenarios stay byte-consistent
with the rest of the pipeline.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. ``numpy`` is the numeric core, ``pandas`` reads the committed
TMY. ``cvxpy`` is ALLOWED at module scope by GUARD-02 but is DEFERRED inside
``solve_twostage_cvxpy`` (the ``der_voltage.py`` precedent) and gated behind
``require_capabilities("ops")`` so ``import gridalyn`` / the kernel stays cheap on
a non-``ops`` install. The RNG is ALWAYS the explicit ``rng`` argument (a
generator built once from the pinned ``SEED``) — the global numpy random state is
NEVER used (every kernel comment forbids the global, D-10).

Reproducibility (D-10): single ``np.random.default_rng(SEED=42)``, a pinned
per-scenario draw order (temperature offset → temperature hourly noise → EV day),
float64 throughout, deterministic reductions, ``np.quantile(..., method="linear")``
(NOT the deprecated ``interpolation=`` alias, Pitfall 1; the env is numpy 2.1.3).
The kernel rounds NOTHING (the stage rounds pre-write).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts._stochastic import _ev_day, _occ
from projects.ev_hosting_flex.scripts.config import (
    BG_KW,
    C_ACTIVATE,
    C_RESERVE,
    CALENDAR_HOURS,
    DTYPE,
    EPS_SHOW,
    N_SCENARIOS,
    R_THERM,
    SIGMA_DAILY,
    SIGMA_HOURLY,
    T_BALANCE,
    TMY_INPUT_PATH,
    TWOSTAGE_SOLVER,
)

_RESIDUAL_TOL = 1e-6  # strict-> residual tolerance for the reliability count (D-05).


def _validate_eps(eps: float) -> None:
    """Raise a located ValueError unless ``eps`` is a valid reliability level.

    Args:
        eps: The per-hour exceedance probability; must lie strictly in (0, 1).

    Raises:
        ValueError: If ``eps`` is not in the open interval (0, 1).
    """
    if not (0.0 < float(eps) < 1.0):
        raise ValueError(
            f"two-stage program received eps={eps!r}; the per-hour reliability "
            "level must lie strictly in the open interval (0, 1) so that "
            "Q_{1-eps} is a well-defined interior quantile. Remediation: pass a "
            "value such as EPS_HEADLINE=0.05 or a member of EPS_FRONTIER."
        )


def twostage_oracle(required: np.ndarray, eps: float) -> dict[str, Any]:
    """Return the exact, byte-stable closed-form two-stage policy (the oracle, D-08).

    The optimum of the per-hour-independent chance-constrained program is closed
    form (``r* = Q_{1−ε}``, ``a* = min(r*, required)``) and PRICE-INDEPENDENT for
    any ``C_ACTIVATE > 0`` (D-06). This is the headline source AND the cvxpy
    validation target AND the D-08 fall-back. Ports ``twostage_prototype.py``
    L113-122 with ``np.quantile(..., method="linear")`` (Pitfall 1).

    Args:
        required: ``(n_scen, 24)`` float64 power-to-curtail ensemble
            ``(d + g − S̄)⁺``.
        eps: The per-hour exceedance level ``ε`` in (0, 1); the reserve is the
            ``1 − ε`` quantile per hour.

    Returns:
        A dict with ``r`` (24,), ``a`` (n_scen, 24), ``rel_hour``/``rel_day``
        reliabilities (D-05), ``reservation_cost`` (``C_RESERVE·Σr``),
        ``activation_cost`` (``C_ACTIVATE·E[Σa]``), and ``activated_mean_kwh``.

    Raises:
        ValueError: If ``eps`` is outside (0, 1).
    """
    _validate_eps(eps)
    req = np.ascontiguousarray(required, dtype=DTYPE)
    r = np.quantile(req, 1.0 - eps, axis=0, method="linear")  # (24,) stage-1 reserve
    a = np.minimum(r[None, :], req)  # (n_scen, 24) stage-2 activation
    residual = req - a
    return {
        "r": r,
        "a": a,
        "rel_hour": float(1.0 - (residual > _RESIDUAL_TOL).mean()),  # D-05
        "rel_day": float(
            1.0 - (residual.max(axis=1) > _RESIDUAL_TOL).mean()
        ),
        "reservation_cost": float(C_RESERVE * r.sum()),
        "activation_cost": float(C_ACTIVATE * a.sum(axis=1).mean()),
        "activated_mean_kwh": float(a.sum(axis=1).mean()),
    }


def cold_day_temp(
    *, df: pd.DataFrame | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return the 24h temperature + hour-of-day window at the annual coldest day.

    Reads the committed project-local TMY (network-free; never an auto/download
    source) and returns the day-aligned 24h slice containing the annual coldest
    hour, the cold winter day the day-ahead forecast ensemble perturbs (D-03).
    Mirrors ``twostage_prototype.py:_cold_day_temp`` L61-67 and validates columns
    the way ``_stochastic.tmy_base`` does (V5, located + remediating).

    Args:
        df: Optional pre-loaded TMY frame (tests inject fixtures); when ``None``
            the committed ``TMY_INPUT_PATH`` CSV is read.

    Returns:
        ``(temp, hod)``: a 24-length float64 temperature vector and a 24-length
        int hour-of-day vector for the annual coldest day.

    Raises:
        ValueError: If the TMY is missing ``temp_air``/``timestamp`` or has fewer
            than ``CALENDAR_HOURS`` rows (never silently truncating).
    """
    if df is None:
        df = pd.read_csv(TMY_INPUT_PATH)
    missing = [c for c in ("timestamp", "temp_air") if c not in df.columns]
    if missing:
        raise ValueError(
            "cold_day_temp received a TMY frame missing required column(s) "
            f"{missing} (have {list(df.columns)}); cannot locate the cold day. "
            f"Remediation: re-copy the committed TMY at {TMY_INPUT_PATH} with "
            "'timestamp' and 'temp_air' columns (PVGIS SARAH-3 schema)."
        )
    if len(df) < CALENDAR_HOURS:
        raise ValueError(
            f"cold_day_temp received a short TMY frame ({len(df)} rows); it needs "
            f"at least {CALENDAR_HOURS} hourly rows and refuses to silently "
            f"truncate. Remediation: re-copy the full {CALENDAR_HOURS}-row "
            f"committed TMY at {TMY_INPUT_PATH}."
        )
    df = df.iloc[:CALENDAR_HOURS]
    temp = df["temp_air"].to_numpy(DTYPE)
    hod = df["timestamp"].astype(str).str.slice(11, 13).astype(int).to_numpy()
    start = int(np.argmin(temp)) // 24 * 24  # day-aligned to a 0..23 window
    return temp[start : start + 24], hod[start : start + 24]


def compose_scenarios(
    rng: np.random.Generator,
    *,
    n_ev: int,
    n_homes: int,
    feeder_kw: float,
    eps: float | None = None,
    df: pd.DataFrame | None = None,
    n_scenarios: int = N_SCENARIOS,
    sigma_daily: float = SIGMA_DAILY,
    sigma_hourly: float = SIGMA_HOURLY,
) -> np.ndarray:
    """Return the composed ``required`` ensemble of shape ``(n_scenarios, 24)``.

    Each scenario draws — on the SINGLE passed ``rng`` in a PINNED order (Pitfall
    4) — a day-ahead temperature forecast error (``N(0, sigma_daily)`` offset →
    ``N(0, sigma_hourly)`` per-hour noise), builds the heating base ``d = n_homes
    · (BG_KW·_occ(hod) + max(0, T_BALANCE − temp)/R_THERM)`` (REUSING
    ``_stochastic._occ`` and the locked 10.1 heating-degree form), draws the
    stochastic EV day ``g = _ev_day(rng, n_ev)`` (REUSING the 10.1 EV physics —
    never re-implemented), and forms ``required = (d + g − feeder_kw)⁺``. Ports
    ``twostage_prototype.py:scenarios`` L92-106; the per-scenario draw order
    (temperature offset → temperature hourly noise → EV) is load-bearing for
    byte-stability.

    ``n_homes`` is the feeder's ``downstream_home_count`` (the caller sources it
    from the selected feeder) — NOT the prototype-only ``N_HOMES`` constant (which
    does NOT exist in ``config.py``) and NOT silently ``TARGET_HOMES`` (only the
    manuscript rank target). ``feeder_kw`` is the feeder's MODELED kW rating (the
    ``feeder_transformer_modeled_kw`` / 71.25 kW = ``TRANSFORMER_KVA·POWER_FACTOR``
    basis Stage 4/5 use) — supplied explicitly, never assumed.

    Args:
        rng: A seeded ``np.random.Generator`` (NEVER the global ``np.random``).
        n_ev: EV count sampled per scenario (the penetration's feeder EV count).
        n_homes: The feeder's downstream home count (the base-load multiplier).
        feeder_kw: The feeder's modeled kW rating ``S̄`` subtracted to form
            ``required``.
        eps: Unused here (kept for call-site symmetry); the quantile level is
            applied by ``twostage_oracle`` / ``eps_frontier`` over the ensemble.
        df: Optional pre-loaded TMY frame; when ``None`` the committed TMY is read.
        n_scenarios: Monte-Carlo scenario count (default ``N_SCENARIOS``).
        sigma_daily: Day-ahead per-day temperature-forecast offset std (°C).
        sigma_hourly: Per-hour temperature-forecast noise std (°C).

    Returns:
        A ``(n_scenarios, 24)`` float64 ``required`` ensemble.

    Raises:
        ValueError: If ``n_scenarios <= 0``, ``n_ev < 0``, ``n_homes <= 0``,
            ``feeder_kw < 0``, or either sigma is negative (V5).
    """
    if int(n_scenarios) <= 0:
        raise ValueError(
            f"compose_scenarios received n_scenarios={n_scenarios!r}; the "
            "Monte-Carlo scenario count must be a positive integer. Remediation: "
            "pass N_SCENARIOS (default 4000) or another positive count."
        )
    if int(n_ev) < 0:
        raise ValueError(
            f"compose_scenarios received n_ev={n_ev!r}; the per-scenario EV count "
            "must be a non-negative integer. Remediation: pass round(penetration "
            "* downstream_home_count)."
        )
    if int(n_homes) <= 0:
        raise ValueError(
            f"compose_scenarios received n_homes={n_homes!r}; the feeder home "
            "count (base-load multiplier) must be a positive integer. "
            "Remediation: pass the selected feeder's downstream_home_count."
        )
    if float(feeder_kw) < 0.0:
        raise ValueError(
            f"compose_scenarios received feeder_kw={feeder_kw!r}; the modeled "
            "feeder rating must be non-negative. Remediation: pass the feeder's "
            "feeder_transformer_modeled_kw (e.g. TRANSFORMER_KVA*POWER_FACTOR)."
        )
    if float(sigma_daily) < 0.0 or float(sigma_hourly) < 0.0:
        raise ValueError(
            f"compose_scenarios received sigma_daily={sigma_daily!r}, "
            f"sigma_hourly={sigma_hourly!r}; forecast-error standard deviations "
            "must be non-negative. Remediation: pass SIGMA_DAILY / SIGMA_HOURLY."
        )
    t0, hod = cold_day_temp(df=df)
    occ = _occ(hod)  # (24,) reused 10.1 occupancy shape
    req = np.zeros((int(n_scenarios), 24), dtype=DTYPE)
    for w in range(int(n_scenarios)):
        # PINNED draw order (Pitfall 4): daily offset -> hourly noise -> EV day.
        toff = rng.normal(0.0, sigma_daily) + rng.normal(0.0, sigma_hourly, 24)
        temp = t0 + toff
        d = int(n_homes) * (
            BG_KW * occ + np.maximum(0.0, T_BALANCE - temp) / R_THERM
        )
        g = _ev_day(rng, int(n_ev))  # reused 10.1 EV physics (never re-implemented)
        req[w] = np.maximum(0.0, d + g - float(feeder_kw))
    return req


def solve_twostage_cvxpy(
    required: np.ndarray,
    eps: float,
    *,
    solver: str = TWOSTAGE_SOLVER,
    c_a: float = C_ACTIVATE,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Return ``(r, a, status)`` from the gated cvxpy two-stage solve (D-08).

    The chance constraint ``P(overload_t) ≤ ε`` is a quantile — NOT directly
    LP-representable without a non-deterministic big-M MILP. The provably
    oracle-equivalent formulation (RESEARCH Pattern 2 / A1) FIXES ``r = Q_{1−ε}``
    in numpy and lets cvxpy solve only the trivial recourse LP
    ``min c_a·Σa/n_scen  s.t.  0 ≤ a ≤ required, a ≤ r``, whose optimum is exactly
    ``a = min(r, required)``. This makes the cvxpy↔oracle equivalence a theorem,
    not a hope, and keeps it byte-stable. cvxpy is gated behind
    ``require_capabilities("ops")`` and imported DEFERRED inside this function (the
    ``der_voltage.py`` precedent).

    Args:
        required: ``(n_scen, 24)`` float64 power-to-curtail ensemble.
        eps: The per-hour exceedance level in (0, 1).
        solver: The pinned deterministic cvxpy solver (default ``TWOSTAGE_SOLVER``
            = CLARABEL); must be in ``cvxpy.installed_solvers()`` (V5).
        c_a: Illustrative activation price scaling the (trivial) recourse objective.

    Returns:
        ``(r, a, status)``: the (numpy) reserve (24,), the cvxpy activation
        ``a.value`` (n_scen, 24), and ``str(prob.status)``.

    Raises:
        MissingCapabilityError: If the ``ops`` extra (cvxpy) is not installed.
        ValueError: If ``eps`` is outside (0, 1) or ``solver`` is not installed.
    """
    _validate_eps(eps)
    from gridalyn.foundation.platform.capabilities import require_capabilities

    require_capabilities("ops", context="the two-stage EV-flexibility program")
    import cvxpy as cp  # deferred (der_voltage precedent); GUARD-02 allows it

    if solver not in cp.installed_solvers():
        raise ValueError(
            f"solve_twostage_cvxpy received solver={solver!r} which is not in "
            f"cvxpy.installed_solvers()={cp.installed_solvers()}. Remediation: "
            "pass TWOSTAGE_SOLVER (CLARABEL) or another installed deterministic "
            "solver; ECOS is intentionally dropped (RESEARCH Open-Q1)."
        )
    req = np.ascontiguousarray(required, dtype=DTYPE)
    n_scen, n_hour = req.shape
    # Fix r to the empirical quantile (numpy) — the chance-constraint optimum.
    r = np.quantile(req, 1.0 - eps, axis=0, method="linear")
    a = cp.Variable((n_scen, n_hour), nonneg=True)
    cons = [a <= req, a <= np.broadcast_to(r, (n_scen, n_hour))]
    obj = cp.Minimize(c_a * cp.sum(a) / n_scen)
    prob = cp.Problem(obj, cons)
    prob.solve(solver=getattr(cp, solver))
    return r, np.asarray(a.value, dtype=DTYPE), str(prob.status)


def assert_cvxpy_matches_oracle(
    required: np.ndarray, eps: float, *, atol: float = 1e-6
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the gated cvxpy solve against the oracle; fall back on divergence.

    Computes the closed-form oracle, runs the gated cvxpy solve, and compares the
    reserves. On ``status != "optimal"`` or ``‖r_cvx − r_oracle‖∞ > atol`` it
    records the divergence and signals the D-08c fall-back (the stage emits the
    oracle values); otherwise it confirms the ≤1e-6 equivalence (TWOSTAGE-06).

    Args:
        required: ``(n_scen, 24)`` float64 power-to-curtail ensemble.
        eps: The per-hour exceedance level in (0, 1).
        atol: The equivalence tolerance on the reserve (default 1e-6).

    Returns:
        ``(oracle, meta)`` where ``oracle`` is ``twostage_oracle(required, eps)``
        and ``meta`` carries ``cvxpy_status``, ``drift``, and ``fellback``.
    """
    oracle = twostage_oracle(required, eps)
    r_cvx, _a_cvx, status = solve_twostage_cvxpy(required, eps)
    drift = float(np.abs(r_cvx - oracle["r"]).max())
    fellback = status != "optimal" or drift > atol
    return oracle, {"cvxpy_status": status, "drift": drift, "fellback": fellback}


def eps_frontier(
    required: np.ndarray, eps_grid: tuple[float, ...]
) -> list[dict[str, Any]]:
    """Return one cost-vs-reliability frontier row per ε (TWOSTAGE-05).

    Ports ``twostage_prototype.py`` L113-129: for each ε, the oracle reserve /
    activation give the per-hour and per-day reliabilities, the reservation /
    activation / total costs (illustrative labelled prices), the reserved peak,
    and the activated mean energy. As ε decreases the per-hour reliability rises
    monotonically.

    Args:
        required: ``(n_scen, 24)`` float64 power-to-curtail ensemble.
        eps_grid: The ε sweep (e.g. ``EPS_FRONTIER``).

    Returns:
        A list of frontier-row dicts, one per ε.
    """
    rows: list[dict[str, Any]] = []
    for eps in eps_grid:
        o = twostage_oracle(required, eps)
        rows.append(
            {
                "eps": float(eps),
                "reliability_hour": o["rel_hour"],
                "reliability_day": o["rel_day"],
                "reservation_cost": o["reservation_cost"],
                "activation_cost": o["activation_cost"],
                "total_cost": o["reservation_cost"] + o["activation_cost"],
                "reserved_peak_kw": float(o["r"].max()),
                "activated_mean_kwh": o["activated_mean_kwh"],
            }
        )
    return rows


def coldday_panel(required: np.ndarray, *, eps: float = EPS_SHOW) -> dict[str, Any]:
    """Return the reserve-vs-activation cold-day panel series (D-07, TWOSTAGE-05).

    Ports ``twostage_prototype.py`` L133-137: the day-ahead reserve ``r_s``, the
    real-time mean activation ``a_mean = E[min(r_s, required)]``, and the required
    P50/P90 bands — the mechanism-evidence panel (reserve the tail, activate only
    a fraction).

    Args:
        required: ``(n_scen, 24)`` float64 power-to-curtail ensemble.
        eps: The panel epsilon (default ``EPS_SHOW`` = 0.10).

    Returns:
        Tidy keys ``hour, r_s, a_mean, req_p50, req_p90`` (each a 24-length array).
    """
    _validate_eps(eps)
    req = np.ascontiguousarray(required, dtype=DTYPE)
    r_s = np.quantile(req, 1.0 - eps, axis=0, method="linear")
    a_mean = np.minimum(r_s[None, :], req).mean(axis=0)
    return {
        "hour": np.arange(24),
        "r_s": r_s,
        "a_mean": a_mean,
        "req_p50": np.quantile(req, 0.5, axis=0, method="linear"),
        "req_p90": np.quantile(req, 0.9, axis=0, method="linear"),
    }


def annual_twostage_headline(
    base: np.ndarray,
    ev_stack: np.ndarray,
    feeder_indicator: np.ndarray,
    feeder_kw: float,
    *,
    eps: float,
    downstream_home_count: int,
    firm_ev_count: int,
    flexible_ev_count: int,
) -> dict[str, Any]:
    """Return the optimal annual hosting headline, streaming per day (D-09, Pitfall 3).

    STREAMS per day over the full annual 8760h — NEVER materializing the
    ``(365, n_scen, 24)`` cube (Pitfall 3). For each of the 365 days it builds the
    per-day ``required`` ensemble from the deterministic per-day base slice
    (projected onto the feeder via ``feeder_indicator @ base``) broadcast against
    the EV scenario stack, takes the per-hour ``Q_{1−ε}`` reserve, activates, and
    accumulates the annual activated energy and per-day reserved peak as scalars.
    The hosting headline (``hosting_expansion_percent``) is the optimal
    ``flexible_ev_count`` (re-derived under this scheme at ``eps`` by the caller)
    over the firm count (D-02).

    Args:
        base: ``(n_bus, 8760)`` float64 base demand (kW).
        ev_stack: ``(n_scen, n_bus, 8760)`` or ``(n_scen, 8760)`` float64 EV
            scenario stack (kW); summed to the feeder if per-bus.
        feeder_indicator: ``(n_bus,)`` float64 feeder downstream selector.
        feeder_kw: The feeder's modeled kW rating ``S̄``.
        eps: The fixed headline reliability level (e.g. ``EPS_HEADLINE``).
        downstream_home_count: The feeder home count (headline EV-count basis).
        firm_ev_count: The Phase-10.1 firm hosting EV count (the denominator).
        flexible_ev_count: The optimal flexible EV count under this scheme.

    Returns:
        A headline dict ``{flexible_ev_count, firm_ev_count,
        hosting_expansion_percent, annual_activated_kwh, seasonal_peak_kw,
        reservation_days, downstream_home_count}``.

    Raises:
        ValueError: If ``eps`` is outside (0, 1) or ``firm_ev_count <= 0``.
    """
    _validate_eps(eps)
    if int(firm_ev_count) <= 0:
        raise ValueError(
            f"annual_twostage_headline received firm_ev_count={firm_ev_count!r}; "
            "the hosting-expansion denominator must be a positive integer. "
            "Remediation: pass the Phase-10.1 firm_ev_count (>= 1)."
        )
    base_feeder = np.asarray(feeder_indicator, dtype=DTYPE) @ np.asarray(
        base, dtype=DTYPE
    )  # (8760,)
    ev = np.asarray(ev_stack, dtype=DTYPE)
    if ev.ndim == 3:
        ev_feeder = np.einsum("b,sbt->st", np.asarray(feeder_indicator, DTYPE), ev)
    else:
        ev_feeder = ev  # already (n_scen, 8760)
    n_days = CALENDAR_HOURS // 24
    annual_activated = 0.0
    daily_peak = np.zeros(n_days, dtype=DTYPE)
    for day in range(n_days):
        sl = slice(day * 24, (day + 1) * 24)
        # per-day required: (n_scen, 24); stream — never the full-year cube.
        req_d = np.maximum(
            0.0, base_feeder[sl][None, :] + ev_feeder[:, sl] - float(feeder_kw)
        )
        r_d = np.quantile(req_d, 1.0 - eps, axis=0, method="linear")  # (24,)
        a_d = np.minimum(r_d[None, :], req_d)
        annual_activated += float(a_d.mean(axis=0).sum())
        daily_peak[day] = float(r_d.max())
    hosting_expansion_percent = (
        int(flexible_ev_count) - int(firm_ev_count)
    ) / int(firm_ev_count)
    return {
        "flexible_ev_count": int(flexible_ev_count),
        "firm_ev_count": int(firm_ev_count),
        "hosting_expansion_percent": float(hosting_expansion_percent),
        "annual_activated_kwh": float(annual_activated),
        "seasonal_peak_kw": float(daily_peak.max()),
        "reservation_days": int((daily_peak > _RESIDUAL_TOL).sum()),
        "downstream_home_count": int(downstream_home_count),
    }

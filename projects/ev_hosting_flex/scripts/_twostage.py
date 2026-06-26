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

from projects.ev_hosting_flex.scripts._stochastic import _ev_day
from projects.ev_hosting_flex.scripts.config import (
    C_ACTIVATE,
    C_RESERVE,
    DTYPE,
    EPS_SHOW,
    K_DESIGN,
    SIGMA_DAILY,
    SIGMA_HOURLY,
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
        "rel_day": float(1.0 - (residual.max(axis=1) > _RESIDUAL_TOL).mean()),
        "reservation_cost": float(C_RESERVE * r.sum()),
        "activation_cost": float(C_ACTIVATE * a.sum(axis=1).mean()),
        "activated_mean_kwh": float(a.sum(axis=1).mean()),
    }


def compose_scenarios(
    rng: np.random.Generator,
    *,
    n_ev: int,
    feeder_kw: float,
    q_design: np.ndarray,
    n_homes: int | None = None,
    eps: float | None = None,
    df: pd.DataFrame | None = None,
    n_scenarios: int = K_DESIGN,
    sigma_daily: float = SIGMA_DAILY,
    sigma_hourly: float = SIGMA_HOURLY,
) -> np.ndarray:
    """Return the composed ``required`` ensemble of shape ``(n_scenarios, n_steps)``.

    RE-ANCHORED (Phase 15 RETIRE-02, D-07): the base is now the emitted
    ``q_design`` building-mean trajectory (the governed day-ahead forecast from
    ``_generators.make_q_design``), NOT the retired ``cold_day_temp`` + CLPU
    heating reconstruction. Each scenario draws — on the SINGLE passed ``rng`` in
    a PINNED order (Pitfall 4) — a day-ahead forecast-error perturbation applied in
    **kW space** as a fractional multiplier on ``q_design``, then draws the
    stochastic EV day ``g = _ev_day(rng, n_ev)`` (REUSING the 10.1 EV physics —
    never re-implemented), and forms ``required = (q_design·perturb + g −
    feeder_kw)⁺``.

    The kW-space perturbation MIRRORS ``_generators.make_q_design`` (the governed
    forecast-error model) so the plan ensemble stays byte-consistent with the
    emitted ``Q_design`` family (RESEARCH Open-Q2): with ``frac_per_degc = 0.03``,
    ``perturb = 1 + frac_per_degc · (N(0, sigma_daily) +
    gaussian_filter1d(N(0, sigma_hourly, n_steps), sigma=2))``. The temperature
    forecast-error draws come BEFORE ``g = _ev_day(rng, n_ev)`` so the per-scenario
    draw order (daily offset → hourly noise → EV) is preserved — the byte-stability
    machinery (``SIGMA_DAILY``/``SIGMA_HOURLY``) is reused, only its target base
    changed from temperature to the kW ``q_design`` trajectory.

    ``feeder_kw`` is the feeder's MODELED kW rating (the
    ``feeder_transformer_modeled_kw`` / 71.25 kW = ``TRANSFORMER_KVA·POWER_FACTOR``
    basis Stage 4/5 use) — supplied explicitly, never assumed. ``n_homes`` is no
    longer a base-load multiplier (the base is the per-feeder ``q_design`` already)
    and is accepted only for call-site symmetry; it does not enter the kernel.

    Args:
        rng: A seeded ``np.random.Generator`` (NEVER the global ``np.random``).
        n_ev: EV count sampled per scenario (the penetration's feeder EV count).
        feeder_kw: The feeder's modeled kW rating ``S̄`` subtracted to form
            ``required``.
        q_design: The ``(n_steps,)`` float64 day-ahead forecast trajectory (kW) —
            the emitted ``Q_design`` building mean the ensemble is anchored on.
        n_homes: Unused in the re-anchored kernel (kept for call-site symmetry);
            when supplied it must be a positive integer.
        eps: Unused here (kept for call-site symmetry); the quantile level is
            applied by ``twostage_oracle`` / ``eps_frontier`` over the ensemble.
        df: Unused in the re-anchored kernel (kept for call-site symmetry; the base
            is ``q_design``, no TMY read).
        n_scenarios: Monte-Carlo scenario count (default ``K_DESIGN`` = 60).
        sigma_daily: Day-ahead per-day forecast-error offset std (°C).
        sigma_hourly: Per-hour forecast-error noise std (°C).

    Returns:
        A ``(n_scenarios, n_steps)`` float64 ``required`` ensemble (``n_steps`` is
        ``q_design.shape[0]``).

    Raises:
        ValueError: If ``n_scenarios <= 0``, ``n_ev < 0``, ``feeder_kw < 0``,
            either sigma is negative, ``q_design`` is not a 1-D positive-length
            array, or ``n_homes`` (when supplied) is non-positive (V5).
    """
    if int(n_scenarios) <= 0:
        raise ValueError(
            f"compose_scenarios received n_scenarios={n_scenarios!r}; the "
            "Monte-Carlo scenario count must be a positive integer. Remediation: "
            "pass K_DESIGN (default 60) or another positive count."
        )
    if int(n_ev) < 0:
        raise ValueError(
            f"compose_scenarios received n_ev={n_ev!r}; the per-scenario EV count "
            "must be a non-negative integer. Remediation: pass round(penetration "
            "* downstream_home_count)."
        )
    if n_homes is not None and int(n_homes) <= 0:
        raise ValueError(
            f"compose_scenarios received n_homes={n_homes!r}; when supplied the "
            "feeder home count must be a positive integer. Remediation: pass the "
            "selected feeder's downstream_home_count or omit it (the re-anchored "
            "kernel takes its base from q_design)."
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
    q0 = np.ascontiguousarray(q_design, dtype=DTYPE)
    if q0.ndim != 1 or q0.shape[0] <= 0:
        raise ValueError(
            "compose_scenarios received a q_design with shape "
            f"{q0.shape}; it must be a 1-D (n_steps,) day-ahead forecast "
            "trajectory in kW. Remediation: pass the emitted q_design.npy "
            "(make_q_design / make_design_day_ensemble['Q_design'])."
        )
    n_steps = int(q0.shape[0])
    # Deferred SDK-free import (scipy is a base numeric dep); mirrors make_q_design.
    from scipy.ndimage import gaussian_filter1d

    # kW-space fractional forecast-error sensitivity (mirrors make_q_design, D-07).
    frac_per_degc = 0.03
    req = np.zeros((int(n_scenarios), n_steps), dtype=DTYPE)
    for w in range(int(n_scenarios)):
        # PINNED draw order (Pitfall 4): daily offset -> hourly noise -> EV day.
        daily_offset = float(rng.normal(0.0, float(sigma_daily)))
        hourly_noise = rng.normal(0.0, float(sigma_hourly), n_steps)
        smooth_hourly = gaussian_filter1d(hourly_noise, sigma=2.0, mode="nearest")
        # kW-space fractional perturbation on the q_design base (heating-dominated
        # ~3 %/degC sensitivity), reproducing the forecast-error model of the
        # emitted Q_design family; the EV day below is drawn AFTER so the order
        # (and byte-stability) is preserved.
        perturb = 1.0 + frac_per_degc * (daily_offset + smooth_hourly)
        d = q0 * perturb  # (n_steps,) re-anchored base trajectory
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

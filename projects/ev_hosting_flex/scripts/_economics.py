"""Non-wires economics + energy-preserving deferral hosting kernel for ev_hosting_flex.

The ECON-01 analytical heart of Phase 16 (D-16-1..D-16-5). Two cooperating layers,
both pure-numpy at module scope, both consuming the GOVERNED design-day ensemble
(``make_design_day_ensemble`` → ``Q_real`` / ``ev_pool``) and the ECON-02 governed
constants — never the manuscript's self-contained Monte-Carlo:

* **Deferral hosting (D-16-1/D-16-2):** the hosting count WITH flexibility under the
  manuscript / deck / Phase-10 model — **power-limiting with deferral**. Participating
  chargers are power-limited at the congested evening peak and that EV energy is
  shifted into the off-peak overnight headroom envelope. The gate is the EV energy
  that does NOT fit under the headroom envelope (the truly-undeliverable /
  non-deferrable energy) — **energy-preserving**, NOT curtailed energy and NOT a
  per-hour reserve-reliability test. The flexible count is the last-in-tolerance EV
  count whose undeliverable fraction stays ≤ ``tol_fraction`` (mirrors
  ``firm_transformer_count``, NO early break). The realistic count is bounded by the
  governed ``DEFERRAL_ENROLLMENT_FRACTION`` (D-16-2a: enrollment 0.30 → flex 6,
  +100% vs firm 3) — enrollment is the single binding lever.

* **Non-wires economics ledger (ECON-01):** the two manuscript figure scripts'
  economics (``nonwires_economics.py`` + ``breakeven_nonwires.py``) ported onto the
  governed ensemble + the GOVERNED firm basis (firm=3, 7 homes), NOT the manuscript
  hardcoded ``P_FIRM=1.0``. The contract-cost ledger ``flex_cost = c_r·Σr + c_a·Σa``
  lives in ONE function (no double-count, the ECON-03 anchor), CRF-annualized
  reinforcement, the break-even-penetration vs ``c_r`` sweep, and the adoption-ramp
  deferral NPV.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` / ``lightsim2grid``.
``numpy`` is the sole numeric core; the chosen deferral model is a pure-numpy FLUID
headroom-fill so NO ``cvxpy`` gate is needed. (If a windowed-LP variant were ever
chosen it would be deferred + ``require_capabilities("ops")`` exactly like
``solve_twostage_cvxpy`` — but the chosen model is numpy.) The overload / headroom
feasibility gate routes through ``_congestion.is_overloaded`` / ``transformer_loading``
— the SINGLE source of truth for the ``> rating`` convention (strict ``>``), never
re-implemented here.

Reproducibility (D-16, mirroring ``_twostage.py``): any RNG is ALWAYS the explicit
``rng`` argument (the global numpy random state is NEVER used); float64 throughout;
``np.quantile(..., method="linear")`` (NOT the deprecated ``interpolation=`` alias,
Pitfall 1); deterministic reductions. The kernel rounds NOTHING — the stage rounds
pre-write. No matplotlib (figures live in the Plan-03 stage). No file IO (the stage
loads the ensemble npys and passes arrays).
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from projects.ev_hosting_flex.scripts._congestion import (
    is_overloaded,
    transformer_loading,
)
from projects.ev_hosting_flex.scripts.config import (
    C_A,
    C_R_BASE,
    CAPEX_UPGRADE,
    DEFERRAL_ENROLLMENT_FRACTION,
    DISCOUNT_RATE,
    DTYPE,
    LIFE_YEARS,
    P0_ADOPT,
    PMAX_ADOPT,
    TOL_FRACTION,
)


def _validate_rating(rating_kw: float) -> None:
    """Raise a located ValueError unless ``rating_kw`` is a positive rating.

    Args:
        rating_kw: The modeled usable transformer rating in kW; must be > 0.

    Raises:
        ValueError: If ``rating_kw`` is not strictly positive.
    """
    if not (float(rating_kw) > 0.0):
        raise ValueError(
            f"deferral kernel received rating_kw={rating_kw!r}; the modeled "
            "transformer rating must be strictly positive so loading = "
            "q_total / rating is well-defined. Remediation: pass the pf-pinned "
            "feeder_transformer_modeled_kw (e.g. TRANSFORMER_KVA*POWER_FACTOR = "
            "71.25)."
        )


def _validate_enrollment(enrollment_fraction: float) -> None:
    """Raise a located ValueError unless ``enrollment_fraction`` is in (0, 1].

    Args:
        enrollment_fraction: The fraction of EVs enrolled in managed/deferred
            charging; must lie in the half-open interval (0, 1].

    Raises:
        ValueError: If ``enrollment_fraction`` is outside (0, 1].
    """
    if not (0.0 < float(enrollment_fraction) <= 1.0):
        raise ValueError(
            f"deferral kernel received enrollment_fraction={enrollment_fraction!r}; "
            "the enrolled-EV fraction must lie in the half-open interval (0, 1]. "
            "Remediation: pass DEFERRAL_ENROLLMENT_FRACTION=0.30 (the governed "
            "headline) or a sensitivity value in (0, 1]."
        )


def _validate_n_ev(n_ev: int, ev_max: int) -> None:
    """Raise a located ValueError unless ``n_ev`` indexes the EV pool.

    Args:
        n_ev: The EV count to overlay (indexes the EV-pool middle axis).
        ev_max: The maximum EV count (the EV-pool middle axis is ``ev_max + 1``).

    Raises:
        ValueError: If ``n_ev`` is negative or exceeds ``ev_max``.
    """
    if not (0 <= int(n_ev) <= int(ev_max)):
        raise ValueError(
            f"deferral kernel received n_ev={n_ev!r} outside [0, {int(ev_max)}]; "
            "it indexes the nested-cumulative EV-pool middle axis (ev_max + 1 rows). "
            "Remediation: pass an EV count in range(ev_max + 1)."
        )


def headroom_envelope(q_real: np.ndarray, rating_kw: float) -> np.ndarray:
    """Return the per-step off-peak headroom envelope ``(rating - base)⁺``.

    The available transformer headroom under the EV-free building base, clipped at
    zero (a step where the base alone overloads has 0 headroom — it cannot absorb any
    deferred EV energy). This is the fluid off-peak envelope the deferred EV energy is
    filled into (D-16-1). Float64, same shape as ``q_real``.

    Args:
        q_real: ``(K, n_steps)`` float64 EV-free building-base ensemble (kW).
        rating_kw: The modeled usable transformer rating in kW (> 0).

    Returns:
        A ``(K, n_steps)`` float64 non-negative headroom array.

    Raises:
        ValueError: If ``rating_kw`` is not strictly positive.
    """
    _validate_rating(rating_kw)
    q = np.asarray(q_real, dtype=DTYPE)
    return np.clip(float(rating_kw) - q, 0.0, None)


def undeliverable_energy(
    q_real: np.ndarray,
    ev_pool: np.ndarray,
    n_ev: int,
    rating_kw: float,
    res_minutes: int,
    *,
    enrollment_fraction: float = DEFERRAL_ENROLLMENT_FRACTION,
) -> float:
    """Return the mean truly-undeliverable EV energy (kWh) after deferral (D-16-1).

    Energy-preserving power-limiting-with-deferral. For each realization:

    * The enrolled fraction of the cumulative EV demand ``ev_pool[:, n_ev, :]`` is
      deferrable; the un-enrolled remainder charges naturally (it stays on the base
      and is not power-limited).
    * Form the residual load ``Q_real + unenrolled_EV``; the off-peak headroom of THAT
      residual (``(rating - residual)⁺``) is the envelope the enrolled EV energy can be
      shifted into. The headroom gate routes through ``transformer_loading`` /
      ``is_overloaded`` (the single ``> rating`` convention).
    * The enrolled EV energy that does NOT fit under the residual headroom envelope is
      the truly-undeliverable (non-deferrable) energy. Deferred energy is energy-
      preserving (it is NOT counted as undeliverable); only the genuine surplus is
      gated. The un-enrolled EV that pushes the residual over rating contributes its
      over-rating energy to the undeliverable total (it cannot be power-limited).

    Returns a plain ``float`` mean over the ``K`` realizations. With a zero EV pool the
    result is 0.0 (no EV ⇒ nothing to defer ⇒ nothing undeliverable). When the off-peak
    headroom envelope can absorb all enrolled EV energy AND the residual never overloads
    the result is 0.0 (energy fits ⇒ fully deferrable, energy-preserving).

    Args:
        q_real: ``(K, n_steps)`` float64 EV-free building-base ensemble (kW).
        ev_pool: ``(K, ev_max + 1, n_steps)`` float64 nested cumulative EV pool (kW).
        n_ev: The EV count to overlay (indexes the EV-pool middle axis).
        rating_kw: The modeled usable transformer rating in kW (> 0).
        res_minutes: The aggregation resolution in minutes (kWh = kW · res/60).
        enrollment_fraction: The fraction of EVs enrolled in deferred charging; only
            enrolled EVs are deferrable (D-16-2). Default
            ``DEFERRAL_ENROLLMENT_FRACTION``.

    Returns:
        The mean truly-undeliverable EV energy over ``K`` as a plain ``float`` (kWh).

    Raises:
        ValueError: If ``rating_kw`` <= 0, ``enrollment_fraction`` is outside (0, 1],
            or ``n_ev`` is outside ``[0, ev_max]``.
    """
    _validate_rating(rating_kw)
    _validate_enrollment(enrollment_fraction)
    q = np.asarray(q_real, dtype=DTYPE)
    pool = np.asarray(ev_pool, dtype=DTYPE)
    ev_max = int(pool.shape[1]) - 1
    _validate_n_ev(n_ev, ev_max)
    res_h = float(res_minutes) / 60.0

    ev = pool[:, int(n_ev), :]  # (K, n_steps) cumulative demand of the first n_ev EVs
    if int(n_ev) == 0:
        return 0.0

    # Split the aggregate EV demand into enrolled (deferrable) + un-enrolled (natural).
    enrolled = ev * float(enrollment_fraction)
    unenrolled = ev * (1.0 - float(enrollment_fraction))

    # The un-enrolled EVs charge naturally on top of the building base; the enrolled EV
    # energy is shifted into the off-peak headroom of THAT residual load.
    residual = q + unenrolled  # (K, n_steps)
    # Headroom of the residual (single > rating convention via transformer_loading).
    residual_loading = transformer_loading(residual, rating_kw)  # fraction
    headroom = np.clip(
        float(rating_kw) * (1.0 - residual_loading), 0.0, None
    )  # (K, n_steps) kW, 0 where the residual already overloads

    # Energy bookkeeping (kWh), per realization (sum over steps).
    enrolled_energy = enrolled.sum(axis=1) * res_h  # (K,)
    headroom_cap = headroom.sum(axis=1) * res_h  # (K,)
    # Enrolled energy that does NOT fit under the off-peak envelope (energy-preserving).
    enrolled_undeliverable = np.clip(enrolled_energy - headroom_cap, 0.0, None)  # (K,)

    # Un-enrolled EVs cannot be power-limited: their over-rating energy is undeliverable
    # (it overloads the residual and the un-enrolled chargers are not managed).
    unenrolled_overload = np.where(
        is_overloaded(residual, rating_kw),
        residual - float(rating_kw),
        0.0,
    )  # (K, n_steps) kW over rating attributable to the un-enrolled residual
    unenrolled_undeliverable = unenrolled_overload.sum(axis=1) * res_h  # (K,)

    undeliverable = enrolled_undeliverable + unenrolled_undeliverable  # (K,)
    return float(undeliverable.mean())  # over K


def total_ev_energy(ev_pool: np.ndarray, n_ev: int, res_minutes: int) -> float:
    """Return the mean total EV energy (kWh) at ``n_ev`` over the ensemble.

    The denominator of the undeliverable FRACTION: the mean over ``K`` of the per-
    realization summed EV energy ``Σ_t ev_pool[:, n_ev, t] · res/60``.

    Args:
        ev_pool: ``(K, ev_max + 1, n_steps)`` float64 nested cumulative EV pool (kW).
        n_ev: The EV count to overlay (indexes the EV-pool middle axis).
        res_minutes: The aggregation resolution in minutes (kWh = kW · res/60).

    Returns:
        The mean total EV energy over ``K`` as a plain ``float`` (kWh).
    """
    pool = np.asarray(ev_pool, dtype=DTYPE)
    ev = pool[:, int(n_ev), :]
    return float((ev.sum(axis=1) * (float(res_minutes) / 60.0)).mean())


def deferral_hosting_count(
    q_real: np.ndarray,
    ev_pool: np.ndarray,
    rating_kw: float,
    tol_fraction: float,
    ev_max: int,
    res_minutes: int,
    *,
    enrollment_fraction: float = DEFERRAL_ENROLLMENT_FRACTION,
) -> dict[str, Any]:
    """Return the flexible hosting count via the last-in-tolerance deferral sweep.

    The hosting count WITH flexibility (D-16-1/D-16-2). Sweeps integer EV counts ``n``
    in ``range(ev_max + 1)``, accumulating the undeliverable FRACTION
    ``undeliverable_energy(n) / total_ev_energy(n)`` into a curve, and assigns
    ``flexible = n`` for EVERY count whose undeliverable fraction ``<= tol_fraction`` —
    a LAST-IN-TOLERANCE accumulation with NO early break (mirrors
    ``firm_transformer_count``, NOT the retired first-overload break). The deferral
    undeliverable fraction is monotone non-decreasing in ``n`` over the nested
    cumulative pool, so "largest with frac ≤ tol" is the well-defined flexible count.
    The ``n = 0`` step has zero EV energy ⇒ zero undeliverable ⇒ in tolerance.

    Args:
        q_real: ``(K, n_steps)`` float64 EV-free building-base ensemble (kW).
        ev_pool: ``(K, ev_max + 1, n_steps)`` float64 nested cumulative EV pool (kW).
        rating_kw: The modeled usable transformer rating in kW (> 0).
        tol_fraction: The deferral feasibility tolerance on the undeliverable fraction
            (``TOL_FRACTION``).
        ev_max: The maximum EV count (the EV-pool middle axis is ``ev_max + 1``).
        res_minutes: The aggregation resolution in minutes (kWh = kW · res/60).
        enrollment_fraction: The fraction of EVs enrolled in deferred charging (the
            single binding lever, D-16-2a). Default ``DEFERRAL_ENROLLMENT_FRACTION``.

    Returns:
        ``{flexible_ev_count (int), undeliverable_fraction_curve (list[float]),
        ev_sweep (list[int]), enrollment_fraction (float),
        threshold_convention ("undeliverable_le_tol")}``.

    Raises:
        ValueError: If ``rating_kw`` <= 0 or ``enrollment_fraction`` is outside (0, 1].
    """
    _validate_rating(rating_kw)
    _validate_enrollment(enrollment_fraction)
    flexible = 0
    frac_curve: list[float] = []
    for n in range(int(ev_max) + 1):
        ev_energy = total_ev_energy(ev_pool, n, res_minutes)
        if ev_energy <= 0.0:
            frac = 0.0  # no EV energy ⇒ nothing undeliverable
        else:
            undeliverable = undeliverable_energy(
                q_real,
                ev_pool,
                n,
                rating_kw,
                res_minutes,
                enrollment_fraction=enrollment_fraction,
            )
            frac = undeliverable / ev_energy
        frac_curve.append(float(frac))
        if frac <= float(tol_fraction):
            flexible = n  # last-in-tolerance: keep updating, NO break (D-16-1)
    return {
        "flexible_ev_count": int(flexible),
        "undeliverable_fraction_curve": [float(v) for v in frac_curve],
        "ev_sweep": list(range(int(ev_max) + 1)),
        "enrollment_fraction": float(enrollment_fraction),
        "threshold_convention": "undeliverable_le_tol",
    }


# ───────────────────── Non-wires economics ledger (ECON-01) ─────────────────────
# Ported from the two manuscript figure scripts (nonwires_economics.py +
# breakeven_nonwires.py) onto the GOVERNED design-day ensemble + ECON-02 constants +
# the GOVERNED firm basis (p_firm = firm/n_homes, NOT the manuscript P_FIRM=1.0). The
# contract-cost ledger lives in ONE function (flex_cost) used everywhere a cost is
# needed (the no-double-count guarantee, T-16-03 / ECON-03). The kernel rounds
# nothing, reads no files, has no matplotlib.


def crf(discount_rate: float = DISCOUNT_RATE, life_years: int = LIFE_YEARS) -> float:
    """Return the capital-recovery factor ``d(1+d)^L / ((1+d)^L - 1)``.

    Ports the manuscript CRF formula (``nonwires_economics.py`` L68). Annualizes a
    one-off capital cost over ``life_years`` at ``discount_rate``.

    Args:
        discount_rate: The annual discount rate ``d`` (> 0). Default ``DISCOUNT_RATE``.
        life_years: The asset life in years ``L`` (> 0). Default ``LIFE_YEARS``.

    Returns:
        The capital-recovery factor as a plain ``float``.

    Raises:
        ValueError: If ``discount_rate`` <= 0 or ``life_years`` <= 0.
    """
    if float(discount_rate) <= 0.0 or int(life_years) <= 0:
        raise ValueError(
            f"crf received discount_rate={discount_rate!r}, life_years={life_years!r}; "
            "both must be strictly positive so the capital-recovery factor is "
            "well-defined. Remediation: pass DISCOUNT_RATE=0.05 and LIFE_YEARS=30."
        )
    d = float(discount_rate)
    L = int(life_years)
    return float(d * (1.0 + d) ** L / ((1.0 + d) ** L - 1.0))


def reinforcement_annual(crf_val: float, capex: float = CAPEX_UPGRADE) -> float:
    """Return the annualized reinforcement cost ``crf · capex`` ($/yr).

    Ports ``REINF_ANNUAL = CRF * CAPEX_UPGRADE`` (``nonwires_economics.py`` L69).

    Args:
        crf_val: The capital-recovery factor from ``crf(...)``.
        capex: The reinforcement capital cost in $ (default ``CAPEX_UPGRADE``).

    Returns:
        The annualized reinforcement cost as a plain ``float`` ($/yr).
    """
    return float(float(crf_val) * float(capex))


def flex_cost(
    kw_days: np.ndarray,
    activated: np.ndarray,
    c_r: float = C_R_BASE,
    c_a: float = C_A,
) -> np.ndarray:
    """Return the contract-cost ledger ``c_r·Σr + c_a·Σa`` ($/yr), elementwise.

    THE single ledger identity (T-16-03 / ECON-03): reservation availability fee on
    the reserved kW-days ``Σr`` plus the activation energy fee on the shifted/activated
    kWh ``Σa``. Every cost in this module routes through this one function so there is
    NO double-count and a divergent re-derivation fails the ECON-03 reconciliation. No
    rounding (the stage rounds pre-write).

    Args:
        kw_days: ``(n_p,)`` float64 reserved kW-days per penetration ``Σr``.
        activated: ``(n_p,)`` float64 activated/shifted energy per penetration ``Σa``
            (kWh).
        c_r: The reservation price ($/kW per reservation-day). Default ``C_R_BASE``.
        c_a: The activation price ($/kWh). Default ``C_A``.

    Returns:
        A ``(n_p,)`` float64 array of total flexibility cost ($/yr).
    """
    return float(c_r) * np.asarray(kw_days, dtype=DTYPE) + float(c_a) * np.asarray(
        activated, dtype=DTYPE
    )


def per_penetration_quantities(
    q_real: np.ndarray,
    ev_pool: np.ndarray,
    rating_kw: float,
    eps: float,
    res_minutes: int,
    pen_grid: Sequence[float],
    n_homes: int,
    *,
    enrollment_fraction: float = DEFERRAL_ENROLLMENT_FRACTION,
) -> dict[str, np.ndarray]:
    """Return the per-penetration price-independent quantities from the ensemble.

    REPLACES the manuscript ``mc_quantities()`` + ``annual_base()`` + ``ev_pool()``
    self-contained Monte-Carlo (``nonwires_economics.py`` L109-124) with the governed
    design-day ensemble. For each penetration ``p`` in ``pen_grid``:

    * ``n_ev = round(p · n_homes)`` (clipped to the EV-pool ceiling).
    * Overlay ``ev_pool[:, n_ev, :]`` onto ``q_real`` → ``required = (total − rating)⁺``.
    * ``r = Q_{1−eps}[required]`` over the ``K`` axis
      (``np.quantile(..., method="linear")``), ``a = min(r, required)``.
    * ``kw_days`` = the reserved peak ``max_t r`` (the single design-day collapses the
      manuscript's ``Σ_d max_t r_{d,t}`` to one day), ``activated`` = ``E_K[Σ_t a]``
      (kWh, via ``res/60``), ``undeliverable_fraction`` = the Task-1 deferral
      undeliverable energy / total EV energy.

    Args:
        q_real: ``(K, n_steps)`` float64 EV-free building-base ensemble (kW).
        ev_pool: ``(K, ev_max + 1, n_steps)`` float64 nested cumulative EV pool (kW).
        rating_kw: The modeled usable transformer rating in kW (> 0).
        eps: The per-step exceedance level ``ε`` in (0, 1); the reserve is the
            ``1 − ε`` quantile.
        res_minutes: The aggregation resolution in minutes (kWh = kW · res/60).
        pen_grid: The EV-per-home penetration grid.
        n_homes: The downstream-home count (the EV-count denominator).
        enrollment_fraction: The deferral enrollment fraction for the undeliverable
            fraction (D-16-2). Default ``DEFERRAL_ENROLLMENT_FRACTION``.

    Returns:
        A dict of float64 arrays ``{penetration, n_ev, kw_days, activated,
        undeliverable_fraction}``, each length ``len(pen_grid)``.

    Raises:
        ValueError: If ``rating_kw`` <= 0, ``eps`` is outside (0, 1), or
            ``n_homes`` <= 0.
    """
    _validate_rating(rating_kw)
    if not (0.0 < float(eps) < 1.0):
        raise ValueError(
            f"per_penetration_quantities received eps={eps!r}; the exceedance level "
            "must lie strictly in (0, 1) so Q_{1-eps} is a well-defined interior "
            "quantile. Remediation: pass EPS_HEADLINE=0.05."
        )
    if int(n_homes) <= 0:
        raise ValueError(
            f"per_penetration_quantities received n_homes={n_homes!r}; the "
            "downstream-home count must be a positive integer. Remediation: pass the "
            "selected feeder's downstream_home_count (e.g. 7)."
        )
    q = np.asarray(q_real, dtype=DTYPE)
    pool = np.asarray(ev_pool, dtype=DTYPE)
    ev_max = int(pool.shape[1]) - 1
    res_h = float(res_minutes) / 60.0
    pens = [float(p) for p in pen_grid]

    pen_out: list[float] = []
    n_ev_out: list[int] = []
    kw_days_out: list[float] = []
    activated_out: list[float] = []
    undeliv_out: list[float] = []
    for p in pens:
        n_ev = int(min(round(p * int(n_homes)), ev_max))
        total = q + pool[:, n_ev, :]  # (K, n_steps)
        required = np.maximum(0.0, total - float(rating_kw))  # (K, n_steps)
        r = np.quantile(required, 1.0 - float(eps), axis=0, method="linear")  # (steps,)
        a = np.minimum(r[None, :], required)  # (K, n_steps)
        kw_days = float(r.max())  # single design-day reserved peak (kW)
        activated = float((a.sum(axis=1) * res_h).mean())  # E_K[Σ a] (kWh)
        ev_energy = total_ev_energy(ev_pool, n_ev, res_minutes)
        if ev_energy <= 0.0:
            undeliv_frac = 0.0
        else:
            undeliverable = undeliverable_energy(
                q_real,
                ev_pool,
                n_ev,
                rating_kw,
                res_minutes,
                enrollment_fraction=enrollment_fraction,
            )
            undeliv_frac = undeliverable / ev_energy
        pen_out.append(float(p))
        n_ev_out.append(int(n_ev))
        kw_days_out.append(kw_days)
        activated_out.append(activated)
        undeliv_out.append(float(undeliv_frac))
    return {
        "penetration": np.asarray(pen_out, dtype=DTYPE),
        "n_ev": np.asarray(n_ev_out, dtype=DTYPE),
        "kw_days": np.asarray(kw_days_out, dtype=DTYPE),
        "activated": np.asarray(activated_out, dtype=DTYPE),
        "undeliverable_fraction": np.asarray(undeliv_out, dtype=DTYPE),
    }


def _cross(x: np.ndarray, y: np.ndarray, level: float) -> float | None:
    """Return the linear-interp crossing of ``y(x)`` through ``level`` (or ``None``).

    Ports the manuscript ``_cross`` (``breakeven_nonwires.py`` L133-142): scans
    ascending segments for the first sign change of ``y − level`` and linearly
    interpolates the crossing ``x``. Returns ``None`` if no segment crosses.

    Args:
        x: ``(n,)`` float64 abscissa (e.g. penetration grid).
        y: ``(n,)`` float64 ordinate (e.g. flex cost or undeliverable fraction).
        level: The crossing level (e.g. ``reinf_annual`` or ``TOL_FRACTION``).

    Returns:
        The crossing ``x`` as a ``float``, or ``None`` if ``y`` never crosses
        ``level``.
    """
    xa = np.asarray(x, dtype=DTYPE)
    ya = np.asarray(y, dtype=DTYPE)
    lvl = float(level)
    for i in range(1, int(xa.shape[0])):
        if (float(ya[i - 1]) - lvl) * (float(ya[i]) - lvl) < 0.0:
            t = (lvl - float(ya[i - 1])) / (float(ya[i]) - float(ya[i - 1]))
            return float(xa[i - 1] + t * (xa[i] - xa[i - 1]))
    return None


def breakeven_sweep(
    pen_grid: Sequence[float],
    kw_days: np.ndarray,
    activated: np.ndarray,
    c_r_grid: Sequence[float],
    c_a: float,
    reinf_annual: float,
) -> list[dict[str, Any]]:
    """Return one break-even-penetration row per reservation price ``c_r``.

    Ports the manuscript ``p_star`` break-even sweep (``nonwires_economics.py``
    L140-149): for each ``c_r`` form the flex cost ``flex_cost(...)`` on the
    penetration grid and find the penetration ``p*`` where it crosses
    ``reinf_annual``. The ledger ALWAYS routes through ``flex_cost`` (no double-count).
    Below-grid (flex never cheaper) → the first penetration; above-grid (flex always
    cheaper in range) → the last penetration; otherwise the linear-interp crossing.
    As ``c_r`` rises the break-even penetration is monotone non-increasing (the
    ECON-03 monotonicity anchor).

    Args:
        pen_grid: The EV-per-home penetration grid (ascending).
        kw_days: ``(n_p,)`` float64 reserved kW-days per penetration ``Σr``.
        activated: ``(n_p,)`` float64 activated energy per penetration ``Σa`` (kWh).
        c_r_grid: The reservation-price sweep (ascending).
        c_a: The activation price ($/kWh).
        reinf_annual: The annualized reinforcement cost ($/yr) to break even against.

    Returns:
        A list of ``{c_r, p_star}`` rows (one per swept ``c_r``), each ``float``-cast.
    """
    pen = np.asarray([float(p) for p in pen_grid], dtype=DTYPE)
    kw = np.asarray(kw_days, dtype=DTYPE)
    ac = np.asarray(activated, dtype=DTYPE)
    if not (pen.shape == kw.shape == ac.shape):
        raise ValueError(
            f"breakeven_sweep received mismatched lengths pen_grid={pen.shape}, "
            f"kw_days={kw.shape}, activated={ac.shape}; the per-penetration "
            "quantities must be co-indexed with the penetration grid. Remediation: "
            "pass per_penetration_quantities(...)['kw_days'/'activated'] computed on "
            "the SAME pen_grid."
        )
    rows: list[dict[str, Any]] = []
    for c_r in c_r_grid:
        fc = flex_cost(kw, ac, float(c_r), float(c_a))  # (n_p,) ledger
        if float(reinf_annual) <= float(fc[0]):
            p_star = float(pen[0])  # flex never cheaper than reinforcement in range
        elif float(reinf_annual) >= float(fc[-1]):
            p_star = float(pen[-1])  # flex always cheaper in range
        else:
            p_star = float(np.interp(float(reinf_annual), fc, pen))
        rows.append({"c_r": float(c_r), "p_star": float(p_star)})
    return rows


def adoption_ramp(
    adopt_years: float,
    t: np.ndarray,
    *,
    p0: float = P0_ADOPT,
    pmax: float = PMAX_ADOPT,
) -> np.ndarray:
    """Return the EV-adoption ramp ``p(t)`` clipped to ``[p0, pmax]``.

    Ports the manuscript ``adoption(T)`` (``nonwires_economics.py`` L156-157): a linear
    ramp from ``p0`` today to ``pmax`` over ``adopt_years``, clipped at both ends.

    Args:
        adopt_years: Years to reach ``pmax`` (``T``).
        t: ``(n_t,)`` float64 time grid (years).
        p0: Today's penetration (EV/home). Default ``P0_ADOPT``.
        pmax: The adoption target (EV/home). Default ``PMAX_ADOPT``.

    Returns:
        A ``(n_t,)`` float64 penetration ramp.
    """
    ta = np.asarray(t, dtype=DTYPE)
    return np.clip(
        float(p0) + (float(pmax) - float(p0)) * ta / float(adopt_years),
        float(p0),
        float(pmax),
    )


def deferral_npv(
    adopt_years: float,
    pen_grid: Sequence[float],
    kw_days: np.ndarray,
    activated: np.ndarray,
    *,
    c_r: float = C_R_BASE,
    c_a: float = C_A,
    discount_rate: float = DISCOUNT_RATE,
    p0: float = P0_ADOPT,
    pmax: float = PMAX_ADOPT,
    horizon: int = LIFE_YEARS,
    p_firm: float,
    reinf_annual: float,
    p_feas: float,
) -> float:
    """Return the present value of deferral over the adoption ramp ($).

    Ports the manuscript ``deferral_npv(T, c_r)`` (``nonwires_economics.py`` L159-165)
    onto the governed firm basis. An EV-adoption ramp ``p(t)`` crosses the firm limit
    ``p_firm``; with flexibility the reinforcement is deferred — paying ``flex_cost``
    each year — until the year flex cost exceeds the annualized reinforcement (the
    economically rational switch) or the deferral feasibility ceiling ``p_feas`` is
    exceeded. The discounted ``reinf_annual − flex_cost`` over the deferral years is the
    flexibility value.

    CRITICAL convention delta (D-16-4): ``p_firm`` is the GOVERNED firm basis
    ``firm_ev_count / n_homes`` (e.g. 3/7 ≈ 0.43 EV/home) passed in by the stage —
    NOT the manuscript hardcoded ``P_FIRM = 1.0``. The flex cost ALWAYS routes through
    ``flex_cost`` (no double-count). Monthly steps (smooth), discounted at
    ``discount_rate``.

    Args:
        adopt_years: Years to reach ``pmax`` (``T``).
        pen_grid: The EV-per-home penetration grid the quantities are tabulated on.
        kw_days: ``(n_p,)`` float64 reserved kW-days per penetration ``Σr``.
        activated: ``(n_p,)`` float64 activated energy per penetration ``Σa`` (kWh).
        c_r: The reservation price ($/kW·day). Default ``C_R_BASE``.
        c_a: The activation price ($/kWh). Default ``C_A``.
        discount_rate: The annual discount rate. Default ``DISCOUNT_RATE``.
        p0: Today's penetration (EV/home). Default ``P0_ADOPT``.
        pmax: The adoption target (EV/home). Default ``PMAX_ADOPT``.
        horizon: The planning horizon in years. Default ``LIFE_YEARS``.
        p_firm: The GOVERNED firm penetration (firm_ev_count / n_homes) — NOT 1.0.
        reinf_annual: The annualized reinforcement cost ($/yr).
        p_feas: The deferral feasibility ceiling penetration (EV/home).

    Returns:
        The present value of deferral as a plain ``float`` ($); ``0.0`` if deferral is
        never beneficial over the ramp.
    """
    dt = 1.0 / 12.0  # monthly steps (smooth), mirrors the manuscript DT
    t = np.arange(0.0, float(horizon) + dt / 2.0, dt)
    p_t = adoption_ramp(adopt_years, t, p0=p0, pmax=pmax)
    pen = np.asarray([float(p) for p in pen_grid], dtype=DTYPE)
    kw = np.interp(p_t, pen, np.asarray(kw_days, dtype=DTYPE))
    ac = np.interp(p_t, pen, np.asarray(activated, dtype=DTYPE))
    fc_t = flex_cost(kw, ac, float(c_r), float(c_a))  # ledger over the ramp
    disc = (1.0 + float(discount_rate)) ** t
    # Defer while congestion exists (p > p_firm) AND flex is cheaper than annualized
    # reinforcement AND the deferral is feasible (p <= p_feas).
    active = (
        (p_t > float(p_firm)) & (fc_t < float(reinf_annual)) & (p_t <= float(p_feas))
    )
    return float(np.sum(np.where(active, float(reinf_annual) - fc_t, 0.0) * dt / disc))


def deferral_npv_sweep(
    adopt_grid: Sequence[float],
    pen_grid: Sequence[float],
    kw_days: np.ndarray,
    activated: np.ndarray,
    *,
    c_r: float = C_R_BASE,
    c_a: float = C_A,
    discount_rate: float = DISCOUNT_RATE,
    p0: float = P0_ADOPT,
    pmax: float = PMAX_ADOPT,
    horizon: int = LIFE_YEARS,
    p_firm: float,
    reinf_annual: float,
    p_feas: float,
) -> list[dict[str, Any]]:
    """Return one deferral-NPV row per adoption speed (``adopt_years``).

    Ports the manuscript adoption-speed sweep (``nonwires_economics.py`` L167): for
    each ``adopt_years`` in ``adopt_grid`` compute ``deferral_npv(...)``. Mirrors the
    ``eps_frontier`` row-per-swept-value pattern (one ``float``-cast row each).

    Args:
        adopt_grid: The adoption-speed sweep (years-to-``pmax``).
        pen_grid: The EV-per-home penetration grid.
        kw_days: ``(n_p,)`` float64 reserved kW-days per penetration ``Σr``.
        activated: ``(n_p,)`` float64 activated energy per penetration ``Σa`` (kWh).
        c_r: The reservation price ($/kW·day). Default ``C_R_BASE``.
        c_a: The activation price ($/kWh). Default ``C_A``.
        discount_rate: The annual discount rate. Default ``DISCOUNT_RATE``.
        p0: Today's penetration (EV/home). Default ``P0_ADOPT``.
        pmax: The adoption target (EV/home). Default ``PMAX_ADOPT``.
        horizon: The planning horizon in years. Default ``LIFE_YEARS``.
        p_firm: The GOVERNED firm penetration (firm_ev_count / n_homes) — NOT 1.0.
        reinf_annual: The annualized reinforcement cost ($/yr).
        p_feas: The deferral feasibility ceiling penetration (EV/home).

    Returns:
        A list of ``{adopt_years, deferral_npv}`` rows, one per swept adoption speed.
    """
    rows: list[dict[str, Any]] = []
    for adopt_years in adopt_grid:
        npv = deferral_npv(
            float(adopt_years),
            pen_grid,
            kw_days,
            activated,
            c_r=c_r,
            c_a=c_a,
            discount_rate=discount_rate,
            p0=p0,
            pmax=pmax,
            horizon=horizon,
            p_firm=p_firm,
            reinf_annual=reinf_annual,
            p_feas=p_feas,
        )
        rows.append({"adopt_years": float(adopt_years), "deferral_npv": float(npv)})
    return rows


def feasibility_ceiling(
    undeliverable_fraction: np.ndarray,
    pen_grid: Sequence[float],
    tol_fraction: float = TOL_FRACTION,
    *,
    pmax: float = PMAX_ADOPT,
) -> float:
    """Return the deferral feasibility ceiling penetration ``p_feas`` (EV/home).

    Ports the manuscript ``p_feas`` (``nonwires_economics.py`` L137): the penetration
    where the undeliverable fraction crosses ``tol_fraction``. If the fraction never
    exceeds the tolerance in range, deferral is feasible up to ``pmax``.

    Args:
        undeliverable_fraction: ``(n_p,)`` float64 undeliverable fraction per
            penetration.
        pen_grid: The EV-per-home penetration grid (ascending).
        tol_fraction: The feasibility tolerance. Default ``TOL_FRACTION``.
        pmax: The adoption target used as the ceiling when never infeasible. Default
            ``PMAX_ADOPT``.

    Returns:
        The feasibility ceiling penetration as a plain ``float`` (EV/home).
    """
    pen = np.asarray([float(p) for p in pen_grid], dtype=DTYPE)
    frac = np.asarray(undeliverable_fraction, dtype=DTYPE)
    if float(frac[-1]) > float(tol_fraction):
        return float(np.interp(float(tol_fraction), frac, pen))
    return float(pmax)

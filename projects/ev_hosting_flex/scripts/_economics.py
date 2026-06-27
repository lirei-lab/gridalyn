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
    DEFERRAL_ENROLLMENT_FRACTION,
    DTYPE,
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

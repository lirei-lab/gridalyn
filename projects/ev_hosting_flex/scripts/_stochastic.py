"""Stochastic EV-session numeric primitives for ev_hosting_flex.

The surviving MDPI EV-sampler primitives the design-day MC seam reuses (the
annual TMY-tiled generation path is RETIRED — Phase 15 RETIRE-02 fully closes
it: ``tmy_base``/``clpu_factor`` were removed in Plan 01, ``blend_ev_per_bus``
in Plan 02, and ``tmy_start_hod``/``ev_realizations``/``blend_ev_aggregate`` in
Plan 03 when their last consumer — the old stage-5 ``apply_flexibility_contracts``
body — was re-pointed onto the controller). What remains is the per-session MDPI
kernel ``_generators.ev_nested_pool`` draws the design-day EV pool from:

* ``_ev_day`` (D-05/D-13): one stochastic 24 h aggregate EV draw. Per EV the
  PINNED draw order is ``rng.random()`` (plug-in skip) → ``rng.choice`` (charger
  mix) → ``rng.lognormal`` (session energy) → ``rng.normal`` (arrival) — the
  byte-stability contract (Pitfall 2). A single ``np.random.default_rng`` makes
  the output reproducible for the Phase-17 1e-6 baseline.
* ``_session`` / ``_occ``: the per-session hourly placement + the occupancy
  background shape ``_ev_day`` is built on.
* ``mc_p95`` (D-07): pinned-interpolation 95th percentile — the
  ``interpolation=`` keyword is mandatory on the pinned numpy 1.21.5 (Pitfall 1).

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. ``numpy`` is the numeric core. The RNG is ALWAYS the explicit
``rng`` argument (a generator built once from the pinned ``SEED``) — the global
numpy random state / its seed setter are NEVER used (every kernel comment forbids
the global, D-13).
"""

from __future__ import annotations

import numpy as np

from projects.ev_hosting_flex.scripts.config import (
    ARRIVAL_CLIP,
    ARRIVAL_MEAN_H,
    ARRIVAL_STD_H,
    CHARGER_MIX,
    DTYPE,
    EV_KWH_MEDIAN,
    EV_KWH_MIN,
    EV_KWH_SIGMA,
    PLUGIN_PROB,
)

# Charger value/probability arrays built ONCE, sorted by key for determinism so
# rng.choice draws from a stable, reproducible support (D-13). Probabilities are
# renormalized in case the mix shares do not sum to exactly 1.0.
_CHG_KW = np.array(sorted(CHARGER_MIX), dtype=DTYPE)
_CHG_P = np.array([CHARGER_MIX[k] for k in _CHG_KW], dtype=DTYPE)
_CHG_P = _CHG_P / _CHG_P.sum()


def _occ(hour: np.ndarray) -> np.ndarray:
    """Return the occupancy-shape multiplier on the background load.

    A Gaussian bump peaking at hour 19 (evening), floored at 0.7. Ported
    verbatim from ``congestion_temperature_correlation.py:_occ`` (L54).

    Args:
        hour: Hour-of-day array (or scalar) in [0, 23].

    Returns:
        The float64 occupancy multiplier aligned to ``hour``.
    """
    return 0.7 + 0.3 * np.exp(
        -0.5 * ((np.asarray(hour, dtype=DTYPE) - 19.0) / 4.0) ** 2
    )


def _session(charger: float, start: float, energy: float) -> np.ndarray:
    """Return a 24h hourly draw (kW) for one EV charging session.

    Places ``energy`` kWh at ``charger`` kW from hour ``start``, splitting the
    fractional first/last hour by overlap. Deterministic given its inputs.
    Ported verbatim from ``congestion_tradecurve_mc.py:_session`` (L69-76).

    Args:
        charger: Charger power in kW (> 0).
        start: Session start hour-of-day (may be fractional).
        energy: Session energy in kWh.

    Returns:
        A ``(24,)`` float64 hourly draw vector (kW).
    """
    out = np.zeros(24, dtype=DTYPE)
    if energy <= 0:
        return out
    h0, h1 = start, start + energy / charger
    for h in range(int(np.floor(h0)), int(np.ceil(h1))):
        out[h % 24] += max(0.0, min(h1, h + 1) - max(h0, h)) * charger
    return out


def _ev_day(rng: np.random.Generator, n_ev: int) -> np.ndarray:
    """Return one stochastic 24h aggregate EV draw (kW) for ``n_ev`` EVs.

    PINNED per-EV draw order (the byte-stability contract, Pitfall 2 / D-13):
    ``rng.random()`` (plug-in skip if ``> PLUGIN_PROB``) → ``rng.choice`` from
    the charger mix → ``rng.lognormal`` session energy clamped to ``EV_KWH_MIN``
    → ``rng.normal`` arrival clipped to ``ARRIVAL_CLIP``. Per-EV loop order is
    deliberately kept (matches the validated manuscript stream ``_ev_total``
    L79-88, A4) so the established baseline is reproducible.

    Args:
        rng: A seeded ``np.random.Generator`` (NEVER the global ``np.random``).
        n_ev: Number of EVs to sample on this realization-day.

    Returns:
        A ``(24,)`` float64 aggregate EV draw vector (kW).
    """
    out = np.zeros(24, dtype=DTYPE)
    for _ in range(n_ev):
        if rng.random() > PLUGIN_PROB:  # 1st draw — plug-in (order is load-bearing)
            continue
        charger = float(rng.choice(_CHG_KW, p=_CHG_P))  # 2nd — charger mix
        energy = max(  # 3rd — lognormal session energy
            EV_KWH_MIN, rng.lognormal(np.log(EV_KWH_MEDIAN), EV_KWH_SIGMA)
        )
        start = float(  # 4th — Gaussian arrival, clipped
            np.clip(rng.normal(ARRIVAL_MEAN_H, ARRIVAL_STD_H), *ARRIVAL_CLIP)
        )
        out += _session(charger, start, energy)
    return out


def mc_p95(values_over_k: np.ndarray) -> float:
    """Return the 95th percentile over the realization axis (D-07).

    Pinned to ``interpolation="linear"`` — the ``interpolation=`` keyword is
    MANDATORY on the project's numpy 1.21.5 (``method=`` would raise; the
    default interpolation could silently change on upgrade, Pitfall 1). P95 is
    the conservative headline statistic (D-07).

    Args:
        values_over_k: A 1-D array (or sequence) of per-realization values.

    Returns:
        The float64 ``interpolation="linear"`` 95th percentile.
    """
    return float(
        np.percentile(np.asarray(values_over_k, DTYPE), 95, interpolation="linear")
    )

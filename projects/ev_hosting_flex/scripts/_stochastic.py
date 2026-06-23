"""Stochastic / TMY annual-profile numeric kernel for ev_hosting_flex.

The genuinely-new ~20% of Phase 10.1 (D-02 seam preserved): the TMY
temperature-driven heating-degree base (D-08, RECAL-03), the calibrated
stochastic EV K-realization sampler (D-05/D-13, RECAL-04), and the byte-stable
Monte-Carlo reducer ``mc_p95`` (D-07, RECAL-06/RECAL-11). These layers only
FILL the ``demand[n_bus, 8760]`` array that ``_congestion.proxy_loading``
already consumes — the proxy is never bypassed (D-02).

Design (CONTEXT.md decisions, amends Phase-9 D-01 per D-08/D-14):

* ``tmy_base`` (D-08): per-home load = occupancy-shaped background + electric
  heating proportional to heating-degree ``max(0, T_BALANCE - T_out) / R_THERM``,
  read network-free from the committed Trois-Rivieres TMY. Addressable per bus
  (``nameplate_share[:, None] * per_home``) so the downstream-sum proxy can
  aggregate it — superseding the deterministic ``_profiles.base_load_8760``.
* ``ev_realizations`` (D-05/D-13): a seeded stochastic EV K-realization stack.
  Per EV the PINNED draw order is ``rng.random()`` (plug-in skip) →
  ``rng.choice`` (charger mix) → ``rng.lognormal`` (session energy) →
  ``rng.normal`` (arrival) — the byte-stability contract (Pitfall 2). A fixed
  ``K`` + a single ``np.random.default_rng(SEED)`` make the output reproducible
  for the Phase-12 1e-6 baseline.
* ``mc_p95`` (D-07): pinned-interpolation 95th percentile — the
  ``interpolation=`` keyword is mandatory on the pinned numpy 1.21.5 (Pitfall 1).

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. ``numpy`` is the numeric core, ``pandas`` reads the committed
TMY. The RNG is ALWAYS the explicit ``rng`` argument (or
``np.random.default_rng(SEED)`` built once) — ``np.random.seed`` / the global
``np.random`` are NEVER used (every kernel comment forbids the global, D-13).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    ARRIVAL_CLIP,
    ARRIVAL_MEAN_H,
    ARRIVAL_STD_H,
    BG_KW,
    CALENDAR_HOURS,
    CHARGER_MIX,
    DTYPE,
    EV_KWH_MEDIAN,
    EV_KWH_MIN,
    EV_KWH_SIGMA,
    PLUGIN_PROB,
    R_THERM,
    T_BALANCE,
    TMY_INPUT_PATH,
)

_DAYS_PER_YEAR = CALENDAR_HOURS // 24  # 365 (non-leap).

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
    return 0.7 + 0.3 * np.exp(-0.5 * ((np.asarray(hour, dtype=DTYPE) - 19.0) / 4.0) ** 2)


def tmy_base(
    nameplate_share: np.ndarray,
    *,
    df: pd.DataFrame | None = None,
) -> np.ndarray:
    """Return the per-bus TMY heating-degree annual base load in kW.

    Per-home load = ``BG_KW * _occ(hod) + max(0, T_BALANCE - temp) / R_THERM``,
    read network-free from the committed Trois-Rivieres TMY (D-08/D-09). The
    result is addressable per bus — ``base[bus] = nameplate_share[bus] *
    per_home`` — so ``_congestion.proxy_loading`` aggregates it over the feeder
    subtree (the D-02 seam). Reads only the committed project-local CSV — never
    a network weather download / auto-fetch source (REPRO guard, D-09).

    Args:
        nameplate_share: Per-bus nameplate share (relative home weight), SORTED-
            bus order, shape ``(n_bus,)``.
        df: Optional pre-loaded TMY frame (tests inject malformed frames); when
            ``None`` the committed ``TMY_INPUT_PATH`` CSV is read.

    Returns:
        A ``(n_bus, CALENDAR_HOURS)`` float64 per-bus hourly base-load array.

    Raises:
        ValueError: If the TMY is missing ``temp_air``/``timestamp`` or has
            fewer than ``CALENDAR_HOURS`` rows (V5 validation, located +
            remediating — never silently truncating).
    """
    if df is None:
        df = pd.read_csv(TMY_INPUT_PATH)
    missing = [c for c in ("timestamp", "temp_air") if c not in df.columns]
    if missing:
        raise ValueError(
            "tmy_base received a TMY frame missing required column(s) "
            f"{missing} (have {list(df.columns)}); cannot build the "
            "heating-degree base. Remediation: regenerate / re-copy the "
            f"committed TMY at {TMY_INPUT_PATH} with 'timestamp' and "
            "'temp_air' columns (PVGIS SARAH-3 schema)."
        )
    if len(df) < CALENDAR_HOURS:
        raise ValueError(
            f"tmy_base received a short TMY frame ({len(df)} rows); the "
            f"heating-degree base needs at least {CALENDAR_HOURS} hourly rows "
            "and refuses to silently truncate. Remediation: re-copy the full "
            f"8760-row committed TMY at {TMY_INPUT_PATH}."
        )
    df = df.iloc[:CALENDAR_HOURS]
    temp = df["temp_air"].to_numpy(DTYPE)
    # tz-proof local hour-of-day: slice "YYYY-MM-DD HH:MM:SS-05:00"[11:13].
    hod = df["timestamp"].astype(str).str.slice(11, 13).astype(int).to_numpy()
    heat = np.maximum(0.0, T_BALANCE - temp) / R_THERM
    per_home = (BG_KW * _occ(hod) + heat).astype(DTYPE)
    share = np.asarray(nameplate_share, dtype=DTYPE)
    return share[:, None] * per_home[None, :]


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


def ev_realizations(
    rng: np.random.Generator,
    k: int,
    *,
    n_ev: int,
    n_bus: int = 1,
) -> np.ndarray:
    """Return a byte-stable stochastic EV K-realization stack in kW.

    Builds ``k`` independent Monte-Carlo realizations from a SINGLE seeded
    ``rng`` drawn in the pinned per-EV order (see ``_ev_day``); each realization
    is the daily evening EV shape tiled across all 365 days, then broadcast to a
    per-bus ``(n_bus,)`` axis (the stage scales it by the largest-remainder
    ``allocate_ev_per_bus`` allocation downstream, so each bus carries the same
    per-EV-unit shape here). Two calls with identical inputs and seeds produce
    byte-identical stacks (same ``content_sha256``) — the D-05/D-13 contract.

    Args:
        rng: A seeded ``np.random.Generator`` (e.g.
            ``np.random.default_rng(SEED)``); NEVER the global ``np.random``.
        k: Number of Monte-Carlo realizations (the K axis, fixed for repro).
        n_ev: EV count sampled per realization.
        n_bus: Per-bus axis width to broadcast the EV-unit shape across.

    Returns:
        A ``(k, n_bus, CALENDAR_HOURS)`` float64 EV-draw stack.
    """
    n_days = CALENDAR_HOURS // 24
    stack = np.zeros((k, n_bus, CALENDAR_HOURS), dtype=DTYPE)
    for kk in range(k):
        day = _ev_day(rng, n_ev)  # (24,) drawn in the pinned order
        annual = np.tile(day, n_days)  # (8760,)
        stack[kk, :, :] = annual[None, :]
    return stack


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

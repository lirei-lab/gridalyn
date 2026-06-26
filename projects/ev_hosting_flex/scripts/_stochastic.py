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
TMY. The RNG is ALWAYS the explicit ``rng`` argument (a generator built once
from the pinned ``SEED``) — the global numpy random state / its seed setter are
NEVER used (every kernel comment forbids the global, D-13).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    ARRIVAL_CLIP,
    ARRIVAL_MEAN_H,
    ARRIVAL_STD_H,
    CALENDAR_HOURS,
    CHARGER_MIX,
    DTYPE,
    EV_COINCIDENCE_RHO,
    EV_KWH_MEDIAN,
    EV_KWH_MIN,
    EV_KWH_SIGMA,
    PLUGIN_PROB,
    SEED,
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
    return 0.7 + 0.3 * np.exp(
        -0.5 * ((np.asarray(hour, dtype=DTYPE) - 19.0) / 4.0) ** 2
    )


def tmy_start_hod(*, df: pd.DataFrame | None = None) -> int:
    """Return the committed TMY's first-row clock hour-of-day (the canonical phase).

    RETIRED (Phase 13 RETIRE-01): part of the annual-tiling generation path
    (``ev_realizations`` phase alignment) the design-day MC seam supersedes. KEPT
    importable because the not-yet-migrated Plan-03 stage-5
    ``apply_flexibility_contracts`` still calls it; physically deleted in Plan 03
    when that last consumer migrates.

    The TMY annual series is the canonical clock for the whole pipeline: it carries
    real timestamps, so its array index ``i`` maps to clock hour-of-day
    ``(start_hod + i) % 24`` where ``start_hod`` is THIS first-row hour (the
    committed Trois-Rivieres file starts at ``1989-12-31 19:00`` → 19). The
    midnight-based stochastic EV daily shape must be phased to this value before it
    is tiled and summed with the base by raw index, so the EV evening charging peak
    coincides with the TMY cold-evening base (CR-01). Derived FROM THE TIMESTAMPS —
    never hardcoded — so it tracks any future TMY re-copy.

    Args:
        df: Optional pre-loaded TMY frame; when ``None`` the committed
            ``TMY_INPUT_PATH`` CSV is read.

    Returns:
        The integer first-row hour-of-day in ``[0, 23]``.

    Raises:
        ValueError: If the TMY is missing the ``timestamp`` column.
    """
    if df is None:
        df = pd.read_csv(TMY_INPUT_PATH)
    if "timestamp" not in df.columns:
        raise ValueError(
            "tmy_start_hod received a TMY frame missing the required 'timestamp' "
            f"column (have {list(df.columns)}); cannot derive the EV phase. "
            f"Remediation: re-copy the committed TMY at {TMY_INPUT_PATH} with a "
            "'timestamp' column (PVGIS SARAH-3 schema)."
        )
    first = str(df["timestamp"].iloc[0])
    return int(first[11:13])


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
    start_hod: int = 0,
) -> np.ndarray:
    """Return a byte-stable stochastic EV K-realization stack in kW.

    RETIRED (Phase 13 RETIRE-01): the annual daily-shape-tiled EV generation path
    is REMOVED from the new pipeline — the design-day MC seam draws the
    nested/cumulative MDPI EV pool over the design day instead
    (``_generators.ev_nested_pool``, reusing the kept ``_session``/``_ev_day``
    primitives). KEPT importable (not physically deleted) because
    ``blend_ev_aggregate`` (its last live consumer after Plan 02) still calls it;
    physically deleted in Plan 03 when ``apply_flexibility_contracts`` (the stage-5
    consumer of ``blend_ev_aggregate``) migrates.

    Builds ``k`` independent Monte-Carlo realizations from a SINGLE seeded
    ``rng`` drawn in the pinned per-EV order (see ``_ev_day``); each realization
    is the daily evening EV shape PHASE-ALIGNED to the TMY clock then tiled across
    all 365 days, then broadcast to a per-bus ``(n_bus,)`` axis (the stage scales
    it by the largest-remainder ``allocate_ev_per_bus`` allocation downstream, so
    each bus carries the same per-EV-unit shape here). Two calls with identical
    inputs and seeds produce byte-identical stacks (same ``content_sha256``) — the
    D-05/D-13 contract.

    CR-01 phase alignment: ``_ev_day`` builds a MIDNIGHT-based 24 h shape (``day[h]``
    is clock hour ``h``). The TMY base array index ``i`` carries clock hour
    ``(start_hod + i) % 24`` (the canonical clock, carried by the committed
    timestamps). To make the EV draw at annual index ``i`` correspond to the SAME
    clock hour as ``base[i]`` — so the EV evening charging peak coincides with the
    TMY cold-evening base — the daily shape is rolled by ``-start_hod`` BEFORE
    tiling: ``np.tile(np.roll(day, -start_hod), n_days)[i] == day[(i + start_hod)
    % 24] == day[clock_hour(i)]``. The phase shift is applied AFTER all draws, so
    the pinned RNG draw ORDER (and thus byte-stability) is untouched — only the
    placement phase of the already-drawn daily shape changes. ``start_hod=0``
    (the default) is the legacy midnight phase, so unit fixtures are unaffected.

    Args:
        rng: A seeded ``np.random.Generator`` (e.g.
            ``np.random.default_rng(SEED)``); NEVER the global ``np.random``.
        k: Number of Monte-Carlo realizations (the K axis, fixed for repro).
        n_ev: EV count sampled per realization.
        n_bus: Per-bus axis width to broadcast the EV-unit shape across.
        start_hod: The TMY's first-row clock hour-of-day (``tmy_start_hod()``) the
            midnight-based daily shape is phased to. Default 0 (legacy midnight).

    Returns:
        A ``(k, n_bus, CALENDAR_HOURS)`` float64 EV-draw stack.
    """
    n_days = CALENDAR_HOURS // 24
    phase = int(start_hod) % 24
    stack = np.zeros((k, n_bus, CALENDAR_HOURS), dtype=DTYPE)
    for kk in range(k):
        day = _ev_day(rng, n_ev)  # (24,) drawn in the pinned order
        # Phase the already-drawn shape to the TMY clock (CR-01); draws unchanged.
        day_phased = np.roll(day, -phase)  # day_phased[i%24] == day[(i+phase)%24]
        annual = np.tile(day_phased, n_days)  # (8760,)
        stack[kk, :, :] = annual[None, :]
    return stack


def blend_ev_aggregate(
    ev_unit: np.ndarray,
    count: int,
    rho: float = EV_COINCIDENCE_RHO,
    *,
    seed: int = SEED,
    start_hod: int = 0,
    k: int | None = None,
) -> np.ndarray:
    """Return the partial-coincidence ρ-blended per-feeder EV aggregate (kW).

    RETIRED (Phase 13 RETIRE-01): the annual EV-aggregate blend over the tiled
    ``ev_realizations`` stack is REMOVED from the new pipeline path — the
    design-day MC seam exposes the nested-EV pool the Phase-14 sweep overlays
    directly. KEPT importable (not physically deleted) because the Plan-03 stage-5
    ``apply_flexibility_contracts`` retarget is now its LAST live consumer (stage 6
    migrated off it in Plan 02); physically deleted in Plan 03 when it migrates.

    Replaces the implicit full-coincidence ``count · ev_unit`` pattern at the four
    EV-demand consume sites (EV-COINCIDENCE-RECAL). For an integer EV ``count`` and
    each Monte-Carlo realization ``k`` the blended feeder aggregate is the convex
    mix of a COINCIDENT and an INDEPENDENT term: ``ρ · count · ev_unit_k  +
    (1 − ρ) · independent_aggregate_k(count)``. The coincident term scales the
    existing ``(K, 8760)`` ``n_ev=1`` per-EV-unit stack (every EV identical and
    simultaneous, model coincidence factor ≈ 1). The independent term is ``count``
    INDEPENDENTLY-drawn per-EV days SUMMED — exactly
    ``ev_realizations(rng_count, K, n_ev=count, n_bus=1, start_hod=start_hod)[:, 0,
    :]`` — reusing the SAME pinned per-EV draw order (``_ev_day``: ``rng.random`` →
    ``rng.choice`` → ``rng.lognormal`` → ``rng.normal``); it is NEVER re-implemented
    here.

    ρ semantics. ``ρ = 1`` reproduces the legacy coincident path bit-for-bit
    (the diversified term is multiplied by 0, so the result is exactly ``count ·
    ev_unit`` with identical ``content_sha256``) — the reproducibility guard.
    ``ρ = 0`` is fully independent (maximally diversified). The default ``ρ`` is
    ``config.EV_COINCIDENCE_RHO`` (the citable partial-coincidence value).

    Per-count byte-stability (D-05/D-13). The independent draw for a given
    ``count`` is keyed by ``np.random.SeedSequence([int(seed), int(count)])`` →
    ``np.random.default_rng(...)`` so it is byte-stable AND independent of sweep
    order: two calls for the same count produce byte-identical aggregates, and
    drawing some other count first never perturbs this count's result. ``count =
    0`` returns an all-zero ``(K, 8760)`` array WITHOUT drawing.

    CR-01 phase alignment. ``start_hod`` is applied to BOTH terms: the coincident
    ``ev_unit`` is assumed already phased to the TMY clock (the persisted
    ``ev_stack_K.npy`` is), and the independent term is drawn through
    ``ev_realizations`` with the same ``start_hod`` so the EV evening peak of both
    components stays on the TMY cold-evening base.

    Args:
        ev_unit: The ``(K, 8760)`` float64 ``n_ev=1`` per-EV-unit realization stack
            (the coincident shape; the persisted ``ev_stack_K.npy``).
        count: The integer feeder EV count (>= 0); ``0`` yields zeros.
        rho: The coincidence mixing weight ρ in [0, 1] (default
            ``EV_COINCIDENCE_RHO``).
        seed: The locked base seed the per-count independent draw is keyed from
            (default ``config.SEED``).
        start_hod: The TMY first-row clock hour-of-day both terms are phased to
            (default 0, the legacy midnight phase).
        k: The K realization-axis width; inferred from ``ev_unit.shape[0]`` when
            ``None``.

    Returns:
        A ``(K, 8760)`` float64 blended per-realization feeder EV aggregate (kW),
        unrounded (callers round pre-write).

    Raises:
        ValueError: If ``rho`` is outside [0, 1], ``count`` is negative, or
            ``ev_unit`` is not a 2-D ``(K, 8760)`` array.
    """
    rho_f = float(rho)
    if not (0.0 <= rho_f <= 1.0):
        raise ValueError(
            f"blend_ev_aggregate received rho={rho!r}; the coincidence mixing "
            "weight must lie in the closed interval [0, 1] (rho=1 is the legacy "
            "full-coincidence edge, rho=0 fully independent). Remediation: pass "
            "config.EV_COINCIDENCE_RHO or a value in [0, 1]."
        )
    unit = np.ascontiguousarray(ev_unit, dtype=DTYPE)
    if unit.ndim != 2:
        raise ValueError(
            "blend_ev_aggregate received an ev_unit with ndim="
            f"{unit.ndim} (shape {unit.shape}); it must be a 2-D (K, 8760) per-EV-"
            "unit realization stack. Remediation: pass the (K, 8760) ev_stack_K.npy "
            "(or ev_realizations(rng, K, n_ev=1, n_bus=1, start_hod=...)[:, 0, :])."
        )
    k_eff = int(unit.shape[0]) if k is None else int(k)
    n_count = int(count)
    if n_count < 0:
        raise ValueError(
            f"blend_ev_aggregate received count={count!r}; the feeder EV count "
            "must be a non-negative integer. Remediation: pass round(penetration * "
            "downstream_home_count)."
        )
    n_hour = int(unit.shape[1])
    if n_count == 0:
        # No EVs: blend is identically zero (and we draw nothing — order-free).
        return np.zeros((k_eff, n_hour), dtype=DTYPE)

    coincident = rho_f * float(n_count) * unit  # (K, 8760) coincident term
    if rho_f >= 1.0:
        # ρ == 1: the diversified term is multiplied by 0 — reproduce the legacy
        # coincident path bit-for-bit WITHOUT drawing (the reproducibility guard).
        return coincident.astype(DTYPE)

    # Per-count byte-stable, sweep-order-independent independent aggregate. The
    # SeedSequence([seed, count]) child keys the draw to THIS count only, drawn in
    # the SAME pinned per-EV order as the coincident unit (ev_realizations/_ev_day).
    rng_count = np.random.default_rng(np.random.SeedSequence([int(seed), n_count]))
    independent = ev_realizations(
        rng_count, k_eff, n_ev=n_count, n_bus=1, start_hod=start_hod
    )[
        :, 0, :
    ]  # (K, 8760) — count independent per-EV days summed
    blended = coincident + (1.0 - rho_f) * independent
    return blended.astype(DTYPE)


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

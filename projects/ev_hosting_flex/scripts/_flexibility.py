"""Deterministic closed-form per-node cap/curtailment kernel for ev_hosting_flex.

The flexibility sibling of the Phase-9 ``_congestion.py`` proxy kernel. Implements
the three Phase-10 flexibility gaps, all pure-numpy, float64, deterministic to
1e-6 (FLEX-01/02/03, D-01..D-10):

* **FLEX-01 (the cap):** ``flex_curtailment`` is the closed-form shed-to-limit
  cap. For one congested element E with downstream EV demand ``D_ev`` and total
  demand ``D``, every node under E sheds the SAME fraction
  ``f_E = (D - rating) / D_ev`` clamped to ``[0, 1]`` (D-01/D-03). Because each
  node sheds at least what every element above it needs, the multi-element case
  collapses to a single per-node value
  ``cap_fraction[node, hour] = max(f_E)`` over every congested element above that
  node, relieving ALL congested elements to <= limit in ONE pass — the
  "node-level, once per hour, never per shared upstream line" rule (D-02).
* **FLEX-02 (the metrics):** ``flex_metrics`` returns the per-contract metric set
  (curtailed energy, fraction, activation hours, active contracts, peak shed) with
  a reconciliation guard that fails loudly on per-node energy < 0 or above the
  node's annual EV demand (D-05/D-10).
* **FLEX-03 (the sweep):** ``flexible_ev_count`` scans EVERY ``EV_SWEEP`` point
  (the integer step-20 grid, no break, no interpolation/bisection, D-08),
  recomputes the congested set per N from the UNCAPPED proxy (D-04), and classifies
  each swept point passing iff it is feasible AND the active tolerance holds (the
  primary ``curtailed_energy_fraction`` strict-``<`` gate, D-06). Curtailment is
  asserted monotonic non-decreasing in N (the trade-curve correctness guarantee,
  SC4). ``flexible_ev_count`` = the largest swept passing N (D-08).

The ``>`` vs ``>=`` threshold convention is REUSED from
``_congestion.is_congested`` (strict ``>``, no second epsilon); the downstream-sum
proxy is REUSED from ``_congestion.proxy_loading``.

GUARD-02: NO module-scope heavy-dependency import (no pandapower / geopandas /
lightsim2grid at module scope). ``numpy`` is the numeric core; the only imports
are numpy + the sibling ``_congestion`` / ``config`` project modules.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

from projects.ev_hosting_flex.scripts._congestion import is_congested, proxy_loading
from projects.ev_hosting_flex.scripts.config import (
    DTYPE,
    LINE_LOADING_LIMIT_PERCENT,
    PLUGIN_WINDOW,
    ROUND_DECIMALS,
    TOLERANCE_ACTIVATION_HOURS_MAX,
    TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
    TOLERANCE_PRIMARY,
)


def flex_curtailment(
    indicator: np.ndarray,
    demand: np.ndarray,
    ev_demand: np.ndarray,
    elem_kw: np.ndarray,
    limit: float = float(LINE_LOADING_LIMIT_PERCENT),
) -> dict[str, Any]:
    """Return the closed-form per-node cap fraction + curtailed EV demand.

    The shed-to-limit cap (D-01/D-02/D-03). Per congested element-hour the shed
    fraction is ``f_E = (elem_total_demand - rating) / elem_ev_demand`` clamped to
    ``[0, 1]``; every node under E sheds the same ``f_E`` so the per-node value is
    the MAX of ``f_E`` over every congested element above that node — a node-level
    reduction applied once per hour, NEVER per shared upstream line. Recomputing
    ``proxy_loading`` on ``(demand - curtailed)`` yields every element <= ``limit``
    whenever the result is feasible.

    Args:
        indicator: ``(n_elem, n_bus)`` float64 0/1 downstream matrix (the SAME
            matrix the proxy uses).
        demand: ``(n_bus, n_hour)`` float64 total per-bus demand in kW.
        ev_demand: ``(n_bus, n_hour)`` float64 per-bus EV demand in kW (the only
            sheddable portion).
        elem_kw: ``(n_elem,)`` float64 per-element kW rating (all > 0).
        limit: The loading-percent congestion limit (strict ``>``, routed through
            ``is_congested``).

    Returns:
        ``{cap_fraction, curtailed, feasible, residual_overload_kw}`` where
        ``cap_fraction`` and ``curtailed`` are ``(n_bus, n_hour)`` float64,
        ``feasible`` is a bool (no element-hour where base alone overloads), and
        ``residual_overload_kw`` is the max post-clamp overload over the capped
        loading (``0.0`` when feasible).

    Raises:
        ValueError: If ``elem_kw`` is empty or has a non-positive entry.
    """
    elem_kw = np.asarray(elem_kw, dtype=DTYPE)
    if elem_kw.size == 0:
        raise ValueError(
            "flex_curtailment received an empty elem_kw array. Remediation: pass "
            "the per-element kW ratings for the feeder subtree from "
            "line_transformer_ratings_kw.json."
        )
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "flex_curtailment received a non-positive elem_kw "
            f"(min={float(elem_kw.min())}); f_E would divide by a <= 0 rating. "
            "Remediation: verify line_transformer_ratings_kw.json was built at "
            "pf>0 from the load_aware cache."
        )
    indicator = np.asarray(indicator, dtype=DTYPE)
    demand = np.asarray(demand, dtype=DTYPE)
    ev_demand = np.asarray(ev_demand, dtype=DTYPE)

    # Per-element downstream sums (reuse the proxy's single-matmul reduction).
    elem_total_demand = indicator @ demand  # (n_elem, n_hour)
    elem_ev_demand = indicator @ ev_demand  # (n_elem, n_hour)
    loading_uncapped, _ = proxy_loading(indicator, demand, elem_kw)
    congested = is_congested(loading_uncapped, limit)  # (n_elem, n_hour) strict >

    overload = elem_total_demand - elem_kw[:, None]  # kW above rating
    # f_E only defined where there is sheddable EV demand under the element.
    safe_ev = elem_ev_demand > 0.0
    f_raw = np.where(safe_ev, overload / np.where(safe_ev, elem_ev_demand, 1.0), 0.0)
    # Only congested element-hours shed.
    f_raw = np.where(congested, f_raw, 0.0)
    # Infeasible: a congested element that cannot be relieved by shedding all EV
    # under it — either its pre-clamp f_E exceeds 1, or it carries NO sheddable EV
    # demand at all (``~safe_ev``), in which case base load alone overloads it and
    # f_raw was forced to 0 by the divide-by-zero guard above.
    infeasible_mask = congested & ((f_raw > 1.0) | ~safe_ev)
    f_clamped = np.clip(f_raw, 0.0, 1.0)

    # Node-level reduction: cap_fraction[node, hour] = max over elements above the
    # node of f_E. The indicator's column membership says which elements sit above
    # a node; a masked broadcast max over the element axis gives the per-node cap.
    # (n_elem, n_bus, n_hour): f_E broadcast to a node only where indicator == 1.
    contrib = np.where(
        indicator[:, :, None] > 0.0,
        f_clamped[:, None, :],
        0.0,
    )
    cap_fraction = contrib.max(axis=0).astype(DTYPE)  # (n_bus, n_hour)
    curtailed = (ev_demand * cap_fraction).astype(DTYPE)

    feasible = not bool(infeasible_mask.any())
    if feasible:
        residual_overload_kw = 0.0
    else:
        loading_capped, _ = proxy_loading(indicator, demand - curtailed, elem_kw)
        capped_overload = (loading_capped - float(limit)) / 100.0 * elem_kw[:, None]
        residual_overload_kw = float(max(0.0, float(capped_overload.max())))

    return {
        "cap_fraction": cap_fraction,
        "curtailed": curtailed,
        "feasible": feasible,
        "residual_overload_kw": residual_overload_kw,
    }


def _overnight_session_ids(n_hour: int, window: set[int], start_hod: int) -> np.ndarray:
    """Return a per-hour overnight-plug-in-session id (or -1 for out-of-window).

    The physically-correct deferral unit is the CONTIGUOUS overnight session
    18:00(day D) → 07:00(day D+1) — NOT a calendar day split at midnight (CR-02).
    Each in-window hour is keyed to the session anchored on the calendar day whose
    18:00 lead edge opens it: an evening hour (clock 18..23) anchors on its OWN
    day; a morning hour (clock 0..17, in practice 0..7 for the wrap-midnight
    ``PLUGIN_WINDOW``) anchors on the PREVIOUS day's 18:00 session. Excess from a
    congested hour may only refill spare in-window headroom carrying the SAME id.

    The annual array index ``i`` carries clock hour ``(start_hod + i) % 24`` (the
    TMY canonical clock after CR-01). For a lone 24 h call the whole vector is one
    session (the documented per-day contract the unit fixtures encode): all
    in-window hours get id 0.

    Args:
        n_hour: Length of the ev/base vector.
        window: The resolved plug-in-window hour-of-day set (membership mod 24).
        start_hod: The TMY's first-row clock hour-of-day (0 for midnight-based
            fixtures).

    Returns:
        An ``(n_hour,)`` int array: the overnight-session id of each in-window hour,
        ``-1`` for out-of-window hours. Ids are contiguous from the leading session.
    """
    idx = np.arange(n_hour)
    clock = (int(start_hod) + idx) % 24
    in_window = np.array([int(c) in window for c in clock])
    if n_hour <= 24:
        # A lone day is a single overnight session (per-day contract): every
        # in-window hour shares id 0; out-of-window hours are -1.
        return np.where(in_window, 0, -1)
    # Absolute hour / day so the wrap-midnight session groups day-D evening with
    # day-(D+1) morning. Evening hours (clock >= 18) anchor on their own absolute
    # day; morning hours (clock < 18) anchor on the previous absolute day.
    abs_hour = int(start_hod) + idx
    abs_day = abs_hour // 24
    anchor_day = np.where(clock >= 18, abs_day, abs_day - 1)
    # Re-base anchor_day to a 0-based contiguous session id over the present hours.
    session = anchor_day - int(anchor_day.min())
    return np.where(in_window, session, -1)


def flex_deferral(
    ev: np.ndarray,
    base: np.ndarray,
    rating: float,
    *,
    plugin_window: Sequence[int] = PLUGIN_WINDOW,
    limit: float = float(LINE_LOADING_LIMIT_PERCENT),
    annual_ev_demand: float | None = None,
    start_hod: int = 0,
) -> dict[str, Any]:
    """Valley-fill over-cap EV energy into the EV's in-window plug-in hours (D-11).

    The genuinely-new deferral mechanism beside the kept ``flex_curtailment``. It is
    NEITHER manuscript variant: NOT the fixed off-peak ``[22..6]`` refill (which
    ignores early departures), NOT the whole-day ``np.argsort`` valley-fill (which
    overstates by assuming all-day availability). Energy is re-placed ONLY into hours
    inside the EV's plug-in window — ``plugin_window`` wraps midnight
    (``[18..23] ∪ [0..7]`` per day) — so nothing is ever placed after an early
    departure or in a daytime out-of-window hour.

    Per-session confinement (CR-02): deferred energy may only be re-placed into the
    in-window hours of the SAME CONTIGUOUS OVERNIGHT plug-in session it originated
    from — 18:00(day D) → 07:00(day D+1), the physical plug-in unit — never pooled
    across the whole multi-day vector. A December cold-evening's excess can NOT
    valley-fill into a July night. Excess that cannot fit its own session's spare
    in-window headroom is irreducible-lost for that session; the reported
    ``remaining`` is the sum over sessions. A lone 24 h vector is a single session
    (the per-day unit-test contract).

    Mechanism (per the manuscript ``_relief`` first half, then a PER-SESSION refill):

    1. The headroom at each hour is ``max(0, rating - base[h])``; the EV draw placed
       at its own hour is ``placed[h] = min(ev[h], headroom[h])``; the over-cap
       excess per session is ``Σ_session (ev - placed)`` at the congested hours.
    2. Each session's excess is refilled into THAT session's in-window hours sorted
       lowest-base-first, each taking ``min(remaining, max(0, rating - base[h] -
       placed[h]))`` of spare headroom until the session's excess is exhausted or
       the session window is full.
    3. The unfittable per-session excess summed over sessions is the IRREDUCIBLE
       lost energy (D-12); ``irreducible_lost_fraction = remaining / annual_ev``.

    The over-cap determination routes through the kept ``is_congested`` (strict
    ``>``, no second epsilon, T-10.1-07): an hour whose loading sits exactly at the
    limit is NOT over-cap.

    Args:
        ev: ``(n_hour,)`` float64 per-hour EV draw in kW (hour-of-day or annual).
        base: ``(n_hour,)`` float64 per-hour non-EV base demand in kW.
        rating: The element kW rating (the deferral headroom denominator, > 0).
        plugin_window: Hours (0..23) the EV is plugged in and may host deferred
            energy; membership is taken modulo 24 so it applies per day.
        limit: The loading-percent congestion limit (strict ``>``, routed through
            ``is_congested``).
        annual_ev_demand: The ``irreducible_lost_fraction`` denominator; defaults to
            ``ev.sum()`` when ``None``.
        start_hod: The annual array's clock hour-of-day at index 0 (``tmy_start_hod()``
            after CR-01); used to segment overnight sessions. Default 0 (midnight).

    Returns:
        ``{placed, remaining, irreducible_lost_fraction, headroom_kw,
        inwindow_hours, threshold_convention}`` where ``placed`` is the
        ``(n_hour,)`` post-deferral hourly EV draw, ``remaining`` is the irreducible
        unfittable energy in kWh, and ``inwindow_hours`` is the resolved in-window
        hour set.

    Raises:
        ValueError: If ``rating`` is non-positive or ``ev``/``base`` shapes differ.
    """
    ev = np.asarray(ev, dtype=DTYPE)
    base = np.asarray(base, dtype=DTYPE)
    if float(rating) <= 0.0:
        raise ValueError(
            "flex_deferral received a non-positive rating "
            f"({float(rating)}); the deferral headroom (rating - base) would be "
            "ill-defined. Remediation: pass the feeder element's positive kW rating "
            "from line_transformer_ratings_kw.json."
        )
    if ev.shape != base.shape:
        raise ValueError(
            "flex_deferral received mismatched ev/base shapes "
            f"(ev={ev.shape}, base={base.shape}); they must align hour-for-hour. "
            "Remediation: pass per-hour ev and base vectors of identical length."
        )

    n_hour = ev.shape[0]
    # The over-cap mask routes through the kept strict-> helper (no second epsilon).
    # loading% = (base + ev) / rating * 100; is_congested flags the strictly-over
    # hours so a value exactly at the limit is NOT treated as over-cap (T-10.1-07).
    loading = (base + ev) / float(rating) * 100.0
    over_cap = is_congested(loading, limit)

    headroom = np.maximum(0.0, float(rating) - base)
    placed = np.minimum(ev, headroom).astype(DTYPE)
    # Over-cap excess is only the portion at hours that strictly exceed the limit;
    # at non-over-cap hours ev already fits under headroom (placed == ev there).
    excess = np.where(over_cap, ev - placed, 0.0)

    # In-window hour set (wraps midnight): membership taken modulo 24 so the
    # plug-in window applies to every day of a multi-day vector (D-11).
    window = {int(h) % 24 for h in plugin_window}
    inwindow_hours = [h for h in range(n_hour) if (h % 24) in window]

    # CR-02: segment into contiguous overnight plug-in sessions and valley-fill
    # WITHIN each session only — a congested hour's excess can refill only spare
    # in-window headroom of its OWN session (never the whole year).
    session_ids = _overnight_session_ids(n_hour, window, int(start_hod))
    remaining_total = 0.0
    for sid in sorted({int(s) for s in session_ids if s >= 0}):
        members = np.where(session_ids == sid)[0]
        session_excess = float(excess[members].sum())
        if session_excess <= 1e-12:
            continue
        # Refill lowest-base-first (valley-fill) into THIS session's spare headroom.
        for h in sorted(members, key=lambda hh: float(base[hh])):
            if session_excess <= 1e-12:
                break
            spare = max(0.0, float(rating) - float(base[h]) - float(placed[h]))
            take = min(session_excess, spare)
            placed[h] += take
            session_excess -= take
        remaining_total += max(0.0, session_excess)
    # Out-of-window excess (no session can host it) is fully irreducible-lost.
    remaining_total += float(excess[session_ids < 0].sum())
    remaining = remaining_total

    denom = float(ev.sum()) if annual_ev_demand is None else float(annual_ev_demand)
    if denom <= 0.0:
        irreducible_lost_fraction = 0.0
    else:
        irreducible_lost_fraction = remaining / denom

    return {
        "placed": placed.astype(DTYPE),
        "remaining": float(max(0.0, remaining)),
        "irreducible_lost_fraction": float(irreducible_lost_fraction),
        "headroom_kw": headroom.astype(DTYPE),
        "inwindow_hours": inwindow_hours,
        "threshold_convention": "strict_gt_limit",
    }


def flex_metrics(
    curtailed: np.ndarray,
    ev_demand: np.ndarray,
    node_annual_ev_demand: np.ndarray,
    *,
    total_annual_ev_demand: float,
) -> dict[str, Any]:
    """Return the FLEX-02 per-contract metric set + reconciliation guard.

    Modeled on ``congestion_metrics`` (D-10). Floats are rounded to
    ``ROUND_DECIMALS``; counts are plain Python ``int`` so the Phase-12 regression
    numeric branch applies. A contract is active exactly where its cap strictly
    binds (``curtailed > 0``, D-05).

    Args:
        curtailed: ``(n_bus, n_hour)`` float64 per-node-hour curtailed EV demand
            in kW.
        ev_demand: ``(n_bus, n_hour)`` float64 per-node-hour EV demand in kW.
        node_annual_ev_demand: ``(n_bus,)`` float64 per-node annual EV demand in
            kW (``== ev_demand.sum(axis=1)``) — the explicit D-10 reconciliation
            upper bound.
        total_annual_ev_demand: Scalar annual EV demand at the tested EV count, the
            ``curtailed_energy_fraction`` denominator (keyword-only).

    Returns:
        ``{curtailed_energy_mwh, curtailed_energy_fraction,
        contract_activation_hours, contract_activation_hours_per_node,
        n_active_contracts, max_curtailment_kw, per_node_curtailed_energy_mwh}``.

    Raises:
        ValueError: If ``curtailed`` is empty, if Σ per-node energy diverges from
            the total beyond ``ROUND_DECIMALS``, or if any per-node curtailed
            energy is < 0 or > that node's annual EV demand.
    """
    curtailed = np.asarray(curtailed, dtype=DTYPE)
    if curtailed.size == 0 or curtailed.shape[0] == 0:
        raise ValueError(
            "flex_metrics received an empty curtailed array (no nodes in the "
            "feeder subtree). Remediation: verify feeder_elements selected the "
            "transformer + interior lines and bus_ids is non-empty."
        )
    ev_demand = np.asarray(ev_demand, dtype=DTYPE)
    node_annual_ev_demand = np.asarray(node_annual_ev_demand, dtype=DTYPE)

    # Per-node curtailed energy in kWh -> MWh (the hour axis sum is the energy).
    per_node_curtailed_kwh = curtailed.sum(axis=1)  # (n_bus,)
    # Reconciliation (D-10): every per-node energy in [0, node annual EV demand].
    neg = per_node_curtailed_kwh < 0.0
    if bool(neg.any()):
        idx = int(np.argmax(neg))
        raise ValueError(
            "flex_metrics reconciliation failed: per-node curtailed energy is "
            f"negative at node index {idx} "
            f"(value={float(per_node_curtailed_kwh[idx])}). Remediation: a cap "
            "fraction or ev_demand sign error upstream — curtailed must be >= 0."
        )
    over = per_node_curtailed_kwh > node_annual_ev_demand + 10.0**-ROUND_DECIMALS
    if bool(over.any()):
        idx = int(np.argmax(over))
        raise ValueError(
            "flex_metrics reconciliation failed: per-node curtailed energy "
            f"{float(per_node_curtailed_kwh[idx])} exceeds the node's annual EV "
            f"demand {float(node_annual_ev_demand[idx])} at node index {idx}. "
            "Remediation: cap_fraction must be <= 1 — verify flex_curtailment "
            "clamps f_E to [0, 1]."
        )

    total_curtailed_kwh = float(per_node_curtailed_kwh.sum())
    curtailed_energy_mwh = total_curtailed_kwh / 1000.0
    if total_annual_ev_demand <= 0.0:
        curtailed_energy_fraction = 0.0
    else:
        curtailed_energy_fraction = total_curtailed_kwh / float(total_annual_ev_demand)

    binding = curtailed > 0.0  # strict bind (D-05)
    per_node_activation = binding.sum(axis=1)  # (n_bus,)
    n_active_contracts = int((per_node_activation > 0).sum())

    metrics: dict[str, Any] = {
        "curtailed_energy_mwh": float(round(curtailed_energy_mwh, ROUND_DECIMALS)),
        "curtailed_energy_fraction": float(
            round(curtailed_energy_fraction, ROUND_DECIMALS)
        ),
        "contract_activation_hours": int(per_node_activation.sum()),
        "contract_activation_hours_per_node": [int(h) for h in per_node_activation],
        "n_active_contracts": n_active_contracts,
        "max_curtailment_kw": float(
            round(float(curtailed.max()) if curtailed.size else 0.0, ROUND_DECIMALS)
        ),
        "per_node_curtailed_energy_mwh": [
            float(round(float(e) / 1000.0, ROUND_DECIMALS))
            for e in per_node_curtailed_kwh
        ],
    }

    # Reconciliation: the reported per-node energies sum to the reported total.
    # Each per-node value is independently rounded to ROUND_DECIMALS, so summing
    # n_bus of them can drift from the once-rounded total by up to half a ULP per
    # node (plus half a ULP on the total's own rounding). The tolerance scales
    # with n_bus accordingly — a genuine double/under-count is orders of
    # magnitude larger and still trips this guard.
    recon_total = sum(metrics["per_node_curtailed_energy_mwh"])
    recon_tol = (per_node_curtailed_kwh.size * 0.5 + 0.5) * 10.0**-ROUND_DECIMALS
    if abs(recon_total - metrics["curtailed_energy_mwh"]) > recon_tol:
        raise ValueError(
            "flex_metrics reconciliation failed: Σ per-node curtailed energy "
            f"({recon_total} MWh) != total ({metrics['curtailed_energy_mwh']} MWh) "
            f"beyond tolerance {recon_tol} (n_bus={per_node_curtailed_kwh.size}, "
            f"ROUND_DECIMALS={ROUND_DECIMALS}). Remediation: a double-count "
            "or under-count in the per-node energy reduction."
        )
    return metrics


def flexible_ev_count(
    ev_sweep: Sequence[int],
    base: np.ndarray,
    ev_unit: np.ndarray,
    alloc_fn: Callable[[int], np.ndarray],
    indicator: np.ndarray,
    elem_kw: np.ndarray,
    limit: float = float(LINE_LOADING_LIMIT_PERCENT),
    *,
    tolerance_primary: str = TOLERANCE_PRIMARY,
    curtailed_fraction_max: float = TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
    activation_hours_max: int = TOLERANCE_ACTIVATION_HOURS_MAX,
) -> dict[str, Any]:
    """Sweep every EV count and return the flexible (feasible-AND-tolerance) count.

    Mirrors ``firm_ev_count``'s per-N loop but, per D-04/D-06/D-08: scans ALL
    ``ev_sweep`` points (no first-overload break, no interpolation/bisection),
    recomputes the congested set per N from the UNCAPPED proxy, caps via
    ``flex_curtailment``, and classifies each point passing iff it is feasible AND
    the active tolerance holds. ``flexible_ev_count`` is the largest swept passing
    N. Curtailment is asserted monotonic non-decreasing in N (SC4).

    Args:
        ev_sweep: Iterable of total feeder EV counts (the integer step-20 grid).
        base: ``(n_bus, n_hour)`` float64 base demand in kW.
        ev_unit: ``(n_bus, n_hour)`` float64 per-EV unit demand in kW.
        alloc_fn: ``total_ev -> (n_bus,)`` per-bus EV allocation (D-09:
            ``allocate_ev_per_bus``).
        indicator: ``(n_elem, n_bus)`` float64 downstream matrix.
        elem_kw: ``(n_elem,)`` float64 per-element kW rating.
        limit: The loading-percent congestion limit (strict ``>``).
        tolerance_primary: Active acceptability criterion
            (``"curtailed_energy_fraction"`` or ``"activation_hours"``).
        curtailed_fraction_max: The strict-``<`` primary gate.
        activation_hours_max: The ``<=`` secondary gate.

    Returns:
        ``{flexible_ev_count, ev_sweep, trade_curve, tolerance,
        threshold_convention}``.

    Raises:
        ValueError: If curtailment is not monotonic non-decreasing in N.
    """
    base = np.asarray(base, dtype=DTYPE)
    ev_unit = np.asarray(ev_unit, dtype=DTYPE)
    sweep = [int(n) for n in ev_sweep]

    trade_curve: list[dict[str, Any]] = []
    passing: list[int] = []
    prev_curtailed_mwh = -1.0
    for total_ev in sweep:
        per_bus_ev = np.asarray(alloc_fn(int(total_ev)), dtype=DTYPE)
        ev_demand = ev_unit * per_bus_ev[:, None]
        demand = base + ev_demand
        cap = flex_curtailment(indicator, demand, ev_demand, elem_kw, limit)
        node_annual = ev_demand.sum(axis=1)
        metrics = flex_metrics(
            cap["curtailed"],
            ev_demand,
            node_annual,
            total_annual_ev_demand=float(ev_demand.sum()),
        )

        curtailed_mwh = metrics["curtailed_energy_mwh"]
        # Monotonicity tripwire (SC4): curtailment non-decreasing in N.
        if curtailed_mwh + 10.0**-ROUND_DECIMALS < prev_curtailed_mwh:
            raise ValueError(
                "flexible_ev_count: curtailed energy decreased from "
                f"{prev_curtailed_mwh} to {curtailed_mwh} MWh as the EV count rose "
                f"to {total_ev} — curtailment must be monotonic non-decreasing in "
                "N (SC4). Remediation: an alloc_fn or cap-reduction bug broke the "
                "trade-curve correctness guarantee."
            )
        prev_curtailed_mwh = curtailed_mwh

        feasible = bool(cap["feasible"])
        if tolerance_primary == "curtailed_energy_fraction":
            tolerance_ok = metrics["curtailed_energy_fraction"] < float(
                curtailed_fraction_max
            )
        elif tolerance_primary == "activation_hours":
            tolerance_ok = metrics["contract_activation_hours"] <= int(
                activation_hours_max
            )
        else:
            raise ValueError(
                "flexible_ev_count: unknown tolerance_primary "
                f"{tolerance_primary!r}; accepted values are "
                "'curtailed_energy_fraction' and 'activation_hours'. Remediation: "
                "set config.TOLERANCE_PRIMARY to one of those."
            )
        point_passes = feasible and tolerance_ok
        if point_passes:
            passing.append(int(total_ev))

        trade_curve.append(
            {
                "ev_count": int(total_ev),
                "curtailed_energy_mwh": curtailed_mwh,
                "curtailed_energy_fraction": metrics["curtailed_energy_fraction"],
                "n_active_contracts": metrics["n_active_contracts"],
                "feasible": feasible,
                "residual_overload_kw": float(cap["residual_overload_kw"]),
            }
        )

    flexible = max(passing) if passing else 0
    return {
        "flexible_ev_count": flexible,
        "ev_sweep": sweep,
        "trade_curve": trade_curve,
        "tolerance": {
            "primary": tolerance_primary,
            "curtailed_fraction_max": float(curtailed_fraction_max),
            "activation_hours_max": int(activation_hours_max),
        },
        "threshold_convention": "strict_gt_limit",
    }

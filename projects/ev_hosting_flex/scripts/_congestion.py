"""Deterministic radial downstream-sum congestion numeric kernel for ev_hosting_flex.

Implements the three Phase-9 congestion gaps over the cached feeder subtree, all
pure-numpy, float64, deterministic to 1e-6 (CONG-01/02/03, D-09/D-10/D-11/D-12):

* **CONG-01 (the proxy):** ``proxy_loading`` aggregates per-bus demand to a
  per-element loading% via a SINGLE ``indicator @ demand`` matmul over the radial
  downstream-bus indicator — no per-hour AC solve.
* **CONG-02 (the metrics):** ``congestion_metrics`` returns exactly the five
  project-local metrics from the loading array (the CIM-typed constraint *set*
  reuse lives in the STAGE script via ``build_network_constraint_set``, D-11).
* **CONG-03 (the firm sweep):** ``firm_ev_count`` sweeps ascending integer EV
  counts and returns the largest count with zero (line|transformer) x hour
  overload, breaking on the first overload. The ``>`` vs ``>=`` threshold lives in
  ONE helper (``is_congested``, strict ``>``, D-09); a value sitting exactly at
  the limit is NOT congested.

Scope (D-A2): the proxy operates over the SELECTED feeder subtree only — the
feeder transformer plus the interior lines whose downstream set is contained in
the feeder's downstream buses — never the whole twin.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. ``numpy`` is the numeric core; ``build_network_constraint_set``
glue lives in the stage script, not here.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np

from projects.ev_hosting_flex.scripts.config import (
    DTYPE,
    LINE_LOADING_LIMIT_PERCENT,
    ROUND_DECIMALS,
)


def is_congested(
    loading_pct: np.ndarray,
    limit: float = float(LINE_LOADING_LIMIT_PERCENT),
) -> np.ndarray:
    """Return the boolean congestion mask under the strict-``>`` convention.

    The SINGLE source of truth for the ``>`` vs ``>=`` threshold (D-09, WR-03): an
    element-hour is congested iff its loading% strictly EXCEEDS ``limit`` (defaulting
    to ``LINE_LOADING_LIMIT_PERCENT``). A value sitting exactly at the limit (e.g.
    100.0) is NOT congested. No epsilon. ``congestion_metrics`` and ``firm_ev_count``
    route their threshold comparison through THIS helper so the convention lives in
    exactly one place.

    Args:
        loading_pct: Float64 loading-percent array of any shape.
        limit: The loading-percent congestion limit (strict ``>``).

    Returns:
        A boolean ``numpy`` array, same shape as ``loading_pct``.
    """
    return loading_pct > float(limit)


def feeder_elements(
    downstream_map: Mapping[str, Sequence[int]], feeder_key: str
) -> tuple[list[str], list[int]]:
    """Return the sorted (elements, feeder_buses) of the selected feeder subtree.

    Scope = the feeder transformer plus every interior line whose downstream-bus
    set is contained in the feeder's downstream buses (D-A2). Elements are
    returned with the feeder transformer first, then the interior ``line:`` keys
    in sorted order; feeder buses are returned sorted.

    Args:
        downstream_map: Mapping ``key -> [bus, ...]`` from ``downstream_bus_map``.
        feeder_key: The selected feeder element key (e.g. ``"transformer:78"``).

    Returns:
        A tuple ``(elements, feeder_buses)`` of sorted-list scopes.

    Raises:
        ValueError: If ``feeder_key`` is absent from ``downstream_map``.
    """
    if feeder_key not in downstream_map:
        raise ValueError(
            f"feeder_elements: feeder key {feeder_key!r} is not present in the "
            "downstream_bus_map. Remediation: re-run prepare_topology_cache so "
            "downstream_bus_map.json and feeder_selection.json agree."
        )
    feeder_buses = sorted(set(int(b) for b in downstream_map[feeder_key]))
    feeder_set = set(feeder_buses)
    interior_lines = sorted(
        key
        for key in downstream_map
        if key.startswith("line:")
        and set(int(b) for b in downstream_map[key]) <= feeder_set
    )
    elements = [feeder_key, *interior_lines]
    return elements, feeder_buses


def downstream_indicator(
    elements: Sequence[str],
    bus_ids: Sequence[int],
    downstream_map: Mapping[str, Sequence[int]],
) -> np.ndarray:
    """Return the float64 0/1 downstream-membership matrix ``(n_elem, n_bus)``.

    Entry ``[ei, bi]`` is 1.0 iff bus ``bus_ids[bi]`` is downstream of element
    ``elements[ei]``. Elements are iterated in the given (sorted) order; the
    column index is built from the SORTED ``bus_ids`` (D-12 determinism).

    Args:
        elements: Element keys in sorted order.
        bus_ids: Sorted bus ids defining the column order.
        downstream_map: Mapping ``key -> [bus, ...]``.

    Returns:
        A ``(len(elements), len(bus_ids))`` float64 0/1 matrix.
    """
    bus_pos = {int(b): i for i, b in enumerate(bus_ids)}
    indicator = np.zeros((len(elements), len(bus_ids)), dtype=DTYPE)
    for ei, key in enumerate(elements):
        for bus in downstream_map[key]:
            pos = bus_pos.get(int(bus))
            if pos is not None:
                indicator[ei, pos] = 1.0
    return indicator


def proxy_loading(
    indicator: np.ndarray, demand: np.ndarray, elem_kw: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(loading_pct, elem_demand)`` via a single downstream-sum matmul.

    ``elem_demand = indicator @ demand`` (one deterministic reduction, D-12) and
    ``loading_pct = elem_demand / elem_kw[:, None] * 100.0``, both float64.

    Args:
        indicator: ``(n_elem, n_bus)`` float64 0/1 downstream matrix.
        demand: ``(n_bus, n_hour)`` float64 per-bus demand in kW.
        elem_kw: ``(n_elem,)`` float64 per-element kW rating (all > 0).

    Returns:
        A tuple ``(loading_pct, elem_demand)``, each ``(n_elem, n_hour)`` float64.

    Raises:
        ValueError: If ``elem_kw`` is empty or has a non-positive entry.
    """
    elem_kw = np.asarray(elem_kw, dtype=DTYPE)
    if elem_kw.size == 0:
        raise ValueError(
            "proxy_loading received an empty elem_kw array. Remediation: pass the "
            "per-element kW ratings for the feeder subtree from "
            "line_transformer_ratings_kw.json."
        )
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "proxy_loading received a non-positive elem_kw "
            f"(min={float(elem_kw.min())}); loading% would divide by <= 0. "
            "Remediation: verify line_transformer_ratings_kw.json was built at "
            "pf>0 from the load_aware cache."
        )
    elem_demand = np.asarray(indicator, dtype=DTYPE) @ np.asarray(demand, dtype=DTYPE)
    loading_pct = elem_demand / elem_kw[:, None] * 100.0
    return loading_pct.astype(DTYPE), elem_demand.astype(DTYPE)


def congestion_metrics(
    loading_pct: np.ndarray,
    elem_demand: np.ndarray,
    elem_kw: np.ndarray,
    limit: float,
) -> dict[str, Any]:
    """Return the five project-local CONG-02 congestion metrics.

    Computed directly from the loading array (D-11; ``summarize_network_constraints``
    returns a DIFFERENT set and must NOT be used here). Floats are rounded to
    ``ROUND_DECIMALS``; counts are plain Python ``int`` so the Phase-12 regression
    numeric branch applies.

    Args:
        loading_pct: ``(n_elem, n_hour)`` float64 loading-percent array.
        elem_demand: ``(n_elem, n_hour)`` float64 element demand in kW.
        elem_kw: ``(n_elem,)`` float64 per-element kW rating.
        limit: The loading-percent congestion limit (strict ``>``).

    Returns:
        ``{max_line_loading_percent, n_congested_lines, congested_line_hours,
        congested_hours_per_year, peak_overload_kw}``.

    Raises:
        ValueError: If ``loading_pct`` has no elements.
    """
    if loading_pct.size == 0 or loading_pct.shape[0] == 0:
        raise ValueError(
            "congestion_metrics received an empty loading array (no elements in "
            "the feeder subtree). Remediation: verify feeder_elements selected the "
            "transformer + interior lines from downstream_bus_map.json."
        )
    elem_kw = np.asarray(elem_kw, dtype=DTYPE)
    congested = is_congested(loading_pct, limit)
    overload_kw = np.where(congested, elem_demand - elem_kw[:, None], 0.0)
    metrics: dict[str, Any] = {
        "max_line_loading_percent": float(round(float(loading_pct.max()), ROUND_DECIMALS)),
        "n_congested_lines": int(congested.any(axis=1).sum()),
        "congested_line_hours": int(congested.sum()),
        "congested_hours_per_year": int(congested.any(axis=0).sum()),
        "peak_overload_kw": float(round(float(overload_kw.max()), ROUND_DECIMALS)),
    }
    assert metrics["congested_hours_per_year"] <= metrics["congested_line_hours"], (
        "invariant violated: congested_hours_per_year must be <= "
        "congested_line_hours"
    )
    return metrics


def firm_ev_count(
    ev_sweep: Sequence[int],
    base: np.ndarray,
    ev_unit: np.ndarray,
    alloc_fn: Callable[[int], np.ndarray],
    indicator: np.ndarray,
    elem_kw: np.ndarray,
    limit: float,
) -> dict[str, Any]:
    """Sweep ascending EV counts and return the firm / first-overload counts.

    For each total EV count (ascending), allocate it per bus via ``alloc_fn``,
    scale ``ev_unit`` by the per-bus allocation, add the base load, run the proxy,
    and stop at the first count that produces any overload (``is_congested`` strict
    ``>``, D-09). ``firm_ev_count`` is the last count with zero overload;
    ``first_overload_ev_count`` is the breaking count (``None`` if none overloads).

    Args:
        ev_sweep: Ascending iterable of total feeder EV counts (integer step).
        base: ``(n_bus, n_hour)`` float64 base demand in kW.
        ev_unit: ``(n_bus, n_hour)`` float64 per-EV unit demand in kW.
        alloc_fn: ``total_ev -> (n_bus,)`` float64 per-bus EV allocation.
        indicator: ``(n_elem, n_bus)`` float64 downstream matrix.
        elem_kw: ``(n_elem,)`` float64 per-element kW rating.
        limit: The loading-percent congestion limit (strict ``>``).

    Returns:
        ``{firm_ev_count, first_overload_ev_count, ev_sweep, threshold_convention}``.
    """
    base = np.asarray(base, dtype=DTYPE)
    ev_unit = np.asarray(ev_unit, dtype=DTYPE)
    firm = 0
    first_overload: int | None = None
    for total_ev in ev_sweep:
        per_bus_ev = np.asarray(alloc_fn(int(total_ev)), dtype=DTYPE)
        demand = base + ev_unit * per_bus_ev[:, None]
        loading, _ = proxy_loading(indicator, demand, elem_kw)
        if is_congested(loading, limit).any():
            first_overload = int(total_ev)
            break
        firm = int(total_ev)
    return {
        "firm_ev_count": firm,
        "first_overload_ev_count": first_overload,
        "ev_sweep": [int(n) for n in ev_sweep],
        "threshold_convention": "strict_gt_limit",
    }


def _hosting_at_tol(sweep: np.ndarray, p_cong: np.ndarray, tolerance: float) -> float:
    """Return the largest penetration with ``P(cong) <= tolerance`` (linear interp).

    Ported from the manuscript ``_hosting_at_tol`` / ``_cross`` (the firm crossing
    refinement, D-06). The sweep and ``p_cong`` are paired ascending vectors. If
    every swept ``P(cong)`` is within tolerance the whole sweep is firm (return the
    last penetration); if the very first point already exceeds it firm is ``0.0``;
    otherwise the crossing is linearly interpolated between the last in-tolerance
    point and the first out-of-tolerance point.

    Args:
        sweep: Ascending penetration grid, shape ``(n_p,)`` float64.
        p_cong: Per-penetration congestion probability, shape ``(n_p,)`` float64.
        tolerance: The ``P(cong)`` tolerance (e.g. ``FIRM_PCONG_TOLERANCE``).

    Returns:
        The firm penetration as a float (may be fractional / between sweep points).
    """
    ok = p_cong <= float(tolerance)
    if bool(ok.all()):
        return float(sweep[-1])
    i = int(np.argmax(~ok))  # first out-of-tolerance index
    if i == 0:
        return 0.0
    x0, x1 = float(sweep[i - 1]), float(sweep[i])
    y0, y1 = float(p_cong[i - 1]), float(p_cong[i])
    if y1 == y0:  # degenerate (Pitfall 5): no rise to interpolate across.
        return x0
    return x0 + (float(tolerance) - y0) * (x1 - x0) / (y1 - y0)


def firm_pcong_count(
    base: np.ndarray,
    ev_stack: np.ndarray,
    alloc_fn: Callable[[float], np.ndarray],
    indicator: np.ndarray,
    elem_kw: np.ndarray,
    penetration_sweep: Sequence[float],
    tolerance: float,
    limit: float = float(LINE_LOADING_LIMIT_PERCENT),
    blend_fn: Callable[[int], np.ndarray] | None = None,
) -> dict[str, Any]:
    """Sweep penetration and return the firm ``P(cong) <= tolerance`` crossing (D-06).

    The re-calibrated firm gate: for each swept penetration ``p`` the per-bus EV
    allocation ``alloc_fn(p)`` scales each Monte-Carlo realization's EV unit demand;
    over the ``K`` realizations in ``ev_stack`` the per-realization inner engine
    REUSES the kept proxy — ``proxy_loading`` then ``is_congested(...).any()`` — and
    accumulates ``hits`` (the count of realizations with any congested element-hour).
    ``P(cong) = hits / K``. Firm = the largest ``p`` with ``P(cong) <= tolerance``,
    refined by the manuscript linear-interp crossing (``_hosting_at_tol``).

    PARTIAL-COINCIDENCE BLEND (EV-COINCIDENCE-RECAL). When ``blend_fn`` is provided
    the per-bus EV demand stack ``(K, n_bus, n_hour)`` for the penetration's integer
    EV count comes from ``blend_fn(count)`` instead of the legacy coincident
    ``ev_stack[kk] * per_bus_ev[:, None]`` (every EV identical + simultaneous). The
    blended stack is the ρ-mix of a coincident + an independent term distributed
    across buses by the SAME ``allocate_ev_per_bus`` shares so the feeder
    aggregate ``indicator @ demand`` is unchanged in total (the D-02 proxy seam is
    preserved — ``proxy_loading`` is still the only aggregation). With
    ``blend_fn=None`` the legacy coincident path is used unchanged (so existing unit
    fixtures and the ρ=1 edge match bit-for-bit).

    There is NO second epsilon: every threshold decision routes through
    ``is_congested`` (strict ``>``, D-09 / T-10.1-07). A realization whose worst
    loading sits exactly at the limit (100.0) does NOT count as congested.

    Args:
        base: ``(n_bus, n_hour)`` float64 base demand in kW (the TMY base).
        ev_stack: ``(K, n_bus, n_hour)`` float64 stochastic EV K-realization unit
            stack (from ``_stochastic.ev_realizations``); ``ev_stack[k]`` is one
            realization's per-bus EV unit shape (per EV-per-home). Used only on the
            legacy coincident path (``blend_fn=None``).
        alloc_fn: ``penetration -> (n_bus,)`` float64 per-bus EV allocation; the
            realization unit shape is scaled by ``alloc_fn(p)[:, None]``.
        indicator: ``(n_elem, n_bus)`` float64 downstream matrix.
        elem_kw: ``(n_elem,)`` float64 per-element kW rating (all > 0).
        penetration_sweep: Ascending EV-per-home penetration grid.
        tolerance: The firm ``P(cong)`` tolerance (``FIRM_PCONG_TOLERANCE``).
        limit: The loading-percent congestion limit (strict ``>``).
        blend_fn: Optional ``int_ev_count -> (K, n_bus, n_hour)`` partial-coincidence
            per-bus blended EV demand builder (EV-COINCIDENCE-RECAL); when ``None``
            the legacy coincident ``ev_stack[kk] * per_bus_ev`` path is used.

    Returns:
        ``{firm_penetration, firm_ev_count, p_cong, p_cong_at_firm,
        penetration_sweep, downstream_home_count, threshold_convention}`` where
        ``firm_penetration`` is the (possibly fractional) EV/home crossing and
        ``firm_ev_count`` is ``round(firm_penetration * downstream_home_count)``.

    Raises:
        ValueError: If ``ev_stack`` is not a 3-D ``(K, n_bus, n_hour)`` array.
    """
    base = np.asarray(base, dtype=DTYPE)
    ev_stack = np.asarray(ev_stack, dtype=DTYPE)
    if ev_stack.ndim != 3:
        raise ValueError(
            "firm_pcong_count received an ev_stack with ndim="
            f"{ev_stack.ndim} (shape {ev_stack.shape}); it must be a 3-D "
            "(K, n_bus, n_hour) Monte-Carlo realization stack. Remediation: pass "
            "the stack from _stochastic.ev_realizations(rng, K, n_ev=..., "
            "n_bus=n_bus)."
        )
    k_realizations = int(ev_stack.shape[0])
    n_bus = int(base.shape[0])
    sweep = np.asarray([float(p) for p in penetration_sweep], dtype=DTYPE)

    p_cong = np.zeros(sweep.shape[0], dtype=DTYPE)
    for pi, pen in enumerate(sweep):
        per_bus_ev = np.asarray(alloc_fn(float(pen)), dtype=DTYPE)
        ev_demand_stack: np.ndarray | None = None
        if blend_fn is not None:
            total_ev = int(round(float(per_bus_ev.sum())))
            ev_demand_stack = np.asarray(blend_fn(total_ev), dtype=DTYPE)
        hits = 0
        for kk in range(k_realizations):
            if ev_demand_stack is not None:
                demand = base + ev_demand_stack[kk]
            else:
                demand = base + ev_stack[kk] * per_bus_ev[:, None]
            loading, _ = proxy_loading(indicator, demand, elem_kw)
            # REUSE the kept strict-> helper — no second epsilon (T-10.1-07).
            if is_congested(loading, limit).any():
                hits += 1
        p_cong[pi] = hits / k_realizations if k_realizations > 0 else 0.0

    firm_penetration = _hosting_at_tol(sweep, p_cong, tolerance)
    # P(cong) AT the firm crossing: by construction <= tolerance (the in-tolerance
    # side of the bracket); report the bracketing point's probability.
    ok = p_cong <= float(tolerance)
    if bool(ok.all()):
        p_cong_at_firm = float(p_cong[-1]) if p_cong.size else 0.0
    else:
        i = int(np.argmax(~ok))
        p_cong_at_firm = float(p_cong[i - 1]) if i > 0 else float(p_cong[0])

    # The headline EV count is a CONSEQUENCE of the selected feeder's downstream
    # home count (discretion): EV/home penetration x homes. n_bus is the per-bus
    # axis width — the feeder's home-bearing bus count is the home denominator.
    downstream_home_count = n_bus
    firm_ev = int(round(firm_penetration * downstream_home_count))
    return {
        "firm_penetration": float(firm_penetration),
        "firm_ev_count": firm_ev,
        "p_cong": [float(v) for v in p_cong],
        "p_cong_at_firm": float(p_cong_at_firm),
        "penetration_sweep": [float(p) for p in sweep],
        "downstream_home_count": downstream_home_count,
        "threshold_convention": "strict_gt_limit",
    }

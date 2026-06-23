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

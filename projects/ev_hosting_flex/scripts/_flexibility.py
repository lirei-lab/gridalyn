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
    # Infeasible: a congested element whose pre-clamp f_E exceeds 1 (zeroing all
    # EV under it still cannot relieve it — base load alone overloads).
    infeasible_mask = congested & (f_raw > 1.0)
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

    # Reconciliation: Σ per-node energy == total within ROUND_DECIMALS.
    recon_total = sum(metrics["per_node_curtailed_energy_mwh"])
    if abs(recon_total - metrics["curtailed_energy_mwh"]) > 10.0**-ROUND_DECIMALS:
        raise ValueError(
            "flex_metrics reconciliation failed: Σ per-node curtailed energy "
            f"({recon_total} MWh) != total ({metrics['curtailed_energy_mwh']} MWh) "
            f"beyond ROUND_DECIMALS={ROUND_DECIMALS}. Remediation: a double-count "
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

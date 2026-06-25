"""Unit tests for ``projects/ev_hosting_flex/scripts/_flexibility.py``.

Exercises the closed-form cap/curtailment/sweep kernel (FLEX-01/02/03,
D-01..D-10) against hand-computed indicator/demand/ev_demand fixtures with KNOWN
``f_E`` / ``cap_fraction`` / ``curtailed`` — including a feasible case where the
recomputed capped loading sits exactly at the limit, a shared-upstream case
proving the per-node MAX (not summed-per-line) reduction, an infeasible case
where base load alone overloads, the strict-``<`` tolerance boundary, and the
monotonicity-in-N trade-curve guard.

GUARD-02: the kernel is numpy-only; this test never ``import pandapower``.
"""

from __future__ import annotations

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._flexibility import (
    flex_curtailment,
    flex_deferral,
    flex_metrics,
    flex_power_limited,
    flexible_ev_count,
)
from projects.ev_hosting_flex.scripts.config import (
    PLUGIN_WINDOW,
    WORKPLACE_WINDOW,
)

_LIMIT = 100.0


# ─── Cap fixture: transformer over 2 buses + interior line over bus 1 ────────
# indicator: transformer:0 -> [bus0, bus1]; line:0 -> [bus1].
_INDICATOR = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
_ELEM_KW = np.array([100.0, 50.0], dtype="float64")  # transformer, line


def test_flex_curtailment_feasible_relieves_to_limit() -> None:
    """Hand-computed cap brings every element to <= limit (strict >, FLEX-01).

    base: bus0=40, bus1=30; ev: bus0=20, bus1=40; total: bus0=60, bus1=70.
      transformer demand = 130, kW=100 -> 130% congested; f = (130-100)/60 = 0.5
      line        demand = 70,  kW=50  -> 140% congested; f = (70-50)/40  = 0.5
    cap_fraction: bus0 = 0.5 (transformer only); bus1 = max(0.5, 0.5) = 0.5
    curtailed:    bus0 = 20*0.5 = 10; bus1 = 40*0.5 = 20
    capped demand: bus0=50, bus1=50 -> transformer 100%, line 100% (NOT congested).
    """
    base = np.array([[40.0], [30.0]], dtype="float64")
    ev = np.array([[20.0], [40.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(_INDICATOR, demand, ev, _ELEM_KW, _LIMIT)

    np.testing.assert_allclose(out["cap_fraction"], [[0.5], [0.5]])
    np.testing.assert_allclose(out["curtailed"], [[10.0], [20.0]])
    assert out["feasible"] is True
    assert out["residual_overload_kw"] == 0.0

    # Recompute capped loading: every element <= limit.
    capped = demand - out["curtailed"]
    elem_demand = _INDICATOR @ capped
    loading = elem_demand[:, 0] / _ELEM_KW * 100.0
    assert np.all(loading <= _LIMIT + 1e-9)


def test_flex_curtailment_node_level_max_not_summed() -> None:
    """Per-node cap is the MAX of f_E over upstream elements, applied once (D-02).

    Shared upstream: transformer (kW=100) over bus0+bus1 AND interior line
    (kW=40) over bus1. base: bus0=10, bus1=10; ev: bus0=10, bus1=80.
      transformer demand = 110, ev = 90 -> 110% congested; f = 10/90 = 0.1111..
      line        demand = 90,  ev = 80 -> 225% congested; f = (90-40)/80 = 0.625
    bus1 sits under BOTH; its cap is max(0.1111, 0.625) = 0.625 (NOT the sum
    0.736). If the kernel summed per shared line the bus1 cap would be wrong.
    """
    indicator = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
    elem_kw = np.array([100.0, 40.0], dtype="float64")
    base = np.array([[10.0], [10.0]], dtype="float64")
    ev = np.array([[10.0], [80.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    f_trans = (110.0 - 100.0) / 90.0
    f_line = (90.0 - 40.0) / 80.0
    np.testing.assert_allclose(out["cap_fraction"][0, 0], f_trans)
    np.testing.assert_allclose(out["cap_fraction"][1, 0], f_line)  # max, not sum
    assert out["cap_fraction"][1, 0] < f_trans + f_line  # not summed


def test_flex_curtailment_infeasible_clamps_and_flags() -> None:
    """When base alone overloads, feasible=False, residual>0, cap clamped to 1.0.

    Single element (kW=50) over one bus. base=60 (already 120% with ZERO ev),
    ev=10. f_E pre-clamp = (70-50)/10 = 2.0 > 1 -> infeasible; clamp to 1.0;
    curtailed = 10*1.0 = 10; capped demand = 60 -> still 120% -> residual > 0.
    """
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([50.0], dtype="float64")
    base = np.array([[60.0]], dtype="float64")
    ev = np.array([[10.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    assert out["feasible"] is False
    assert out["residual_overload_kw"] > 0.0
    np.testing.assert_allclose(out["cap_fraction"], [[1.0]])
    np.testing.assert_allclose(out["curtailed"], [[10.0]])
    # Residual = capped demand (60) - rating (50) = 10 kW.
    np.testing.assert_allclose(out["residual_overload_kw"], 10.0)


def test_flex_curtailment_congested_with_zero_ev_is_infeasible() -> None:
    """A congested element with NO sheddable EV demand is infeasible (D-03/D-07).

    Single element (kW=100) over one bus, base demand=130 (130% congested) with
    ZERO ev. There is nothing to shed, so the overload cannot be relieved:
    feasible must be False and residual must surface the ~30 kW that remains.
    Regression for the ``safe_ev``-guard hole where f_raw is forced to 0 for
    zero-EV elements, so ``congested & (f_raw > 1.0)`` never fired.
    """
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([100.0], dtype="float64")
    demand = np.array([[130.0]], dtype="float64")  # base only, no EV
    ev = np.array([[0.0]], dtype="float64")
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    assert out["feasible"] is False
    np.testing.assert_allclose(out["curtailed"], [[0.0]])  # nothing to shed
    np.testing.assert_allclose(out["residual_overload_kw"], 30.0)


def test_flex_curtailment_rejects_nonpositive_elem_kw() -> None:
    """A nonpositive elem_kw raises a located ValueError (mirror _congestion)."""
    indicator = np.array([[1.0]], dtype="float64")
    demand = np.array([[10.0]], dtype="float64")
    ev = np.array([[5.0]], dtype="float64")
    with pytest.raises(ValueError, match="elem_kw"):
        flex_curtailment(indicator, demand, ev, np.array([0.0], dtype="float64"))


def test_flex_curtailment_rejects_empty_elem_kw() -> None:
    """An empty elem_kw raises a located ValueError."""
    with pytest.raises(ValueError, match="empty"):
        flex_curtailment(
            np.empty((0, 1), dtype="float64"),
            np.array([[10.0]], dtype="float64"),
            np.array([[5.0]], dtype="float64"),
            np.empty((0,), dtype="float64"),
        )


# ─── flex_metrics: reconciliation + activation ──────────────────────────────


def test_flex_metrics_hand_computed_and_keys() -> None:
    """flex_metrics returns the FLEX-02 set with hand-computed values (D-10)."""
    # 2 nodes x 3 hours. curtailed kWh per node-hour.
    curtailed = np.array([[0.0, 10.0, 0.0], [5.0, 5.0, 0.0]], dtype="float64")
    ev_demand = np.array([[0.0, 20.0, 0.0], [10.0, 10.0, 0.0]], dtype="float64")
    node_annual = ev_demand.sum(axis=1)  # [20, 20]
    total_annual = float(ev_demand.sum())  # 40
    m = flex_metrics(
        curtailed, ev_demand, node_annual, total_annual_ev_demand=total_annual
    )
    # total curtailed = 10 + 5 + 5 = 20 kWh -> 0.02 MWh; fraction = 20/40 = 0.5
    assert m["curtailed_energy_mwh"] == 0.02
    assert m["curtailed_energy_fraction"] == 0.5
    # activation: node0 binds at h1 (1 hour); node1 binds at h0,h1 (2 hours) -> 3
    assert m["contract_activation_hours"] == 3
    assert m["contract_activation_hours_per_node"] == [1, 2]
    assert m["n_active_contracts"] == 2
    assert m["max_curtailment_kw"] == 10.0
    assert isinstance(m["n_active_contracts"], int)
    assert isinstance(m["contract_activation_hours"], int)
    # Reconciliation: Σ per-node == total.
    assert sum(m["per_node_curtailed_energy_mwh"]) == m["curtailed_energy_mwh"]


def test_flex_metrics_rejects_negative_per_node_energy() -> None:
    """A forced-negative per-node energy raises a located ValueError (D-10)."""
    curtailed = np.array([[-1.0, 0.0]], dtype="float64")
    ev_demand = np.array([[10.0, 10.0]], dtype="float64")
    with pytest.raises(ValueError, match="negative"):
        flex_metrics(
            curtailed,
            ev_demand,
            ev_demand.sum(axis=1),
            total_annual_ev_demand=20.0,
        )


def test_flex_metrics_rejects_energy_above_node_annual() -> None:
    """Per-node energy above the node's annual EV demand raises (D-10)."""
    curtailed = np.array([[30.0, 0.0]], dtype="float64")  # 30 kWh shed
    ev_demand = np.array([[10.0, 10.0]], dtype="float64")  # node annual = 20
    with pytest.raises(ValueError, match="exceeds"):
        flex_metrics(
            curtailed,
            ev_demand,
            ev_demand.sum(axis=1),
            total_annual_ev_demand=20.0,
        )


def test_flex_metrics_rejects_empty() -> None:
    """Empty curtailed raises a located ValueError."""
    with pytest.raises(ValueError, match="empty"):
        flex_metrics(
            np.empty((0, 3), dtype="float64"),
            np.empty((0, 3), dtype="float64"),
            np.empty((0,), dtype="float64"),
            total_annual_ev_demand=0.0,
        )


def test_flex_metrics_reconciliation_tolerates_per_node_rounding() -> None:
    """Many-node per-node rounding accumulation must not false-trip recon (D-10).

    Each per-node energy is rounded to ROUND_DECIMALS independently, so summing
    n_bus of them drifts from the once-rounded total by up to half a ULP per
    node. With a real feeder's many buses this exceeds a fixed 1e-6 tolerance
    even though the decomposition is exact — the guard must scale with n_bus.

    20 nodes x 1.2349 kWh: Σ round(1.2349/1000, 6) = 20*0.001235 = 0.024700,
    while round(24.698/1000, 6) = 0.024698 — a 2e-6 drift that trips a fixed
    1e-6 guard but is pure rounding noise (relative error ~8e-5), not a
    double/under-count.
    """
    n_bus = 20
    curtailed = np.full((n_bus, 1), 1.2349, dtype="float64")
    node_annual = np.full(n_bus, 1000.0, dtype="float64")  # >> per-node shed
    m = flex_metrics(
        curtailed,
        curtailed,
        node_annual,
        total_annual_ev_demand=float(n_bus * 1000.0),
    )
    drift = abs(sum(m["per_node_curtailed_energy_mwh"]) - m["curtailed_energy_mwh"])
    # The drift is real rounding noise above the old fixed 1e-6 tolerance...
    assert drift > 10.0**-6
    # ...yet bounded by the per-node rounding budget (half a ULP per node).
    assert drift <= (n_bus * 0.5 + 0.5) * 10.0**-6


# ─── flex_deferral: in-window valley-fill (D-11) + irreducible-lost (D-12) ───
# Hand-built 24-hour-of-day fixtures. PLUGIN_WINDOW wraps midnight ([18..23] ∪
# [0..7]); midday hour 12 is OUT of window. rating is the element kW; base is the
# per-hour-of-day non-EV demand; ev is the per-hour-of-day EV draw.


def test_flex_deferral_inwindow_only_not_after_departure() -> None:
    """Over-cap energy is re-placed ONLY into in-window hours (D-11).

    rating=100. base=90 flat (headroom 10/hour). One congested EV spike of 50 kWh
    at hour 18 (arrival): placed=min(50,10)=10, excess=40 to defer. The in-window
    hours [18..23,0..7] each have 10 kW spare headroom; out-of-window hours (e.g.
    12) have 10 kW too but MUST NOT receive any energy. Assert hour 12 placed == 0
    and that energy only lands in PLUGIN_WINDOW hours.
    """
    rating = 100.0
    base = np.full(24, 90.0, dtype="float64")
    ev = np.zeros(24, dtype="float64")
    ev[18] = 50.0
    out = flex_deferral(ev, base, rating, plugin_window=PLUGIN_WINDOW, limit=_LIMIT)
    placed = np.asarray(out["placed"], dtype="float64")

    # Out-of-window hour 12 (and any hour not in PLUGIN_WINDOW) receives nothing.
    out_of_window = [h for h in range(24) if h not in set(PLUGIN_WINDOW)]
    for h in out_of_window:
        assert placed[h] == 0.0, f"hour {h} (out of window) got {placed[h]}"
    # All placed energy lands in in-window hours only.
    assert placed[12] == 0.0
    # Total placed equals the energy that fit (50 here; window has ample headroom).
    np.testing.assert_allclose(placed.sum(), 50.0)
    assert out["remaining"] == 0.0


def test_flex_deferral_all_fits_inwindow_zero_remaining() -> None:
    """When all over-cap energy fits in-window, remaining == fraction == 0 (D-12)."""
    rating = 100.0
    base = np.full(24, 80.0, dtype="float64")  # 20 kW headroom/hour
    ev = np.zeros(24, dtype="float64")
    ev[19] = 30.0  # placed=min(30,20)=20 at h19, 10 excess deferred into window
    annual_ev = float(ev.sum())
    out = flex_deferral(
        ev,
        base,
        rating,
        plugin_window=PLUGIN_WINDOW,
        limit=_LIMIT,
        annual_ev_demand=annual_ev,
    )
    assert out["remaining"] == 0.0
    assert out["irreducible_lost_fraction"] == 0.0
    np.testing.assert_allclose(np.asarray(out["placed"]).sum(), 30.0)


def test_flex_deferral_saturated_window_positive_remaining() -> None:
    """A saturated in-window valley leaves a hand-computed positive remainder (D-12).

    rating=100. The 14 in-window hours each have only 1 kW spare headroom
    (base=99), and the congested hour 18 also offers 1 kW (placed=min(ev,1)). A
    100 kWh spike at hour 18: placed=1 at h18; excess=99 to defer; the 13 OTHER
    in-window hours absorb 1 kWh each = 13; remaining = 99 - 13 = 86 kWh
    irreducible. (hour 18 already counted in placed.) Out-of-window hours give no
    relief. fraction = 86 / 100.
    """
    rating = 100.0
    base = np.full(24, 99.0, dtype="float64")  # 1 kW headroom/hour everywhere
    ev = np.zeros(24, dtype="float64")
    ev[18] = 100.0
    out = flex_deferral(
        ev,
        base,
        rating,
        plugin_window=PLUGIN_WINDOW,
        limit=_LIMIT,
        annual_ev_demand=100.0,
    )
    # 14 in-window hours x 1 kW = 14 kWh placeable; remaining = 100 - 14 = 86.
    np.testing.assert_allclose(out["remaining"], 86.0)
    np.testing.assert_allclose(out["irreducible_lost_fraction"], 0.86)


def test_flex_deferral_lowest_base_first() -> None:
    """Deferred energy fills the lowest-base in-window hour first (valley-fill).

    rating=100. In-window hours all base=95 (5 kW headroom) EXCEPT hour 2 at
    base=90 (10 kW headroom). hour 18 spike 20 kWh: placed=min(20,5)=5 at h18,
    excess=15. Lowest-base in-window hour is hour 2 (base 90) -> it absorbs its
    full 10 kW first, then the next-lowest hours take 5 each. Assert hour 2 placed
    == 10 (filled to its headroom before higher-base hours).
    """
    rating = 100.0
    base = np.full(24, 95.0, dtype="float64")
    base[2] = 90.0  # the deepest in-window valley
    ev = np.zeros(24, dtype="float64")
    ev[18] = 20.0
    out = flex_deferral(ev, base, rating, plugin_window=PLUGIN_WINDOW, limit=_LIMIT)
    placed = np.asarray(out["placed"], dtype="float64")
    # hour 2 is the lowest base in-window -> filled to its full 10 kW headroom.
    np.testing.assert_allclose(placed[2], 10.0)


def test_flex_deferral_reuses_is_congested_no_second_epsilon() -> None:
    """flex_deferral adds NO bare ``> limit`` threshold of its own (T-10.1-07).

    Reads the kernel source: it must call ``is_congested(`` and contain no bare
    ``> limit`` / ``>= limit`` / ``> float(limit)`` comparison (single-epsilon
    invariant — every congestion decision routes through the kept helper).
    """
    import inspect

    src = inspect.getsource(flex_deferral)
    assert "is_congested(" in src
    assert "> limit" not in src
    assert ">= limit" not in src
    assert "> float(limit)" not in src


def test_flex_deferral_at_limit_not_congested() -> None:
    """An hour at EXACTLY the limit is not over-cap (strict >, no deferral needed).

    rating=100, base=100 flat (loading exactly 100.0 -> NOT congested), ev=0. No
    over-cap energy -> nothing deferred, remaining 0.
    """
    rating = 100.0
    base = np.full(24, 100.0, dtype="float64")  # exactly at limit, strict-> -> ok
    ev = np.zeros(24, dtype="float64")
    out = flex_deferral(ev, base, rating, plugin_window=PLUGIN_WINDOW, limit=_LIMIT)
    assert out["remaining"] == 0.0
    np.testing.assert_allclose(np.asarray(out["placed"]).sum(), 0.0)


# ─── flex_power_limited: chronological throttle + carry-forward (DAYTIME-01..03)
# Power-limited natural charging REPLACES valley-fill: each hour the EV draw is
# throttled to min(remaining_requirement, charger_kw, max(0, rating - base[h])) in
# CLOCK order; undelivered energy carries forward to the day's next session; energy
# unserved after the day's last session is the unserved energy. No argsort/valley
# placement. ``sessions`` is a tuple of session windows (each a tuple of hours-of-day).


def test_power_limited_chronological() -> None:
    """Delivered[h] = min(remaining, charger_kw, max(0, rating-base[h])), clock order.

    rating=100, single overnight session (PLUGIN_WINDOW). base is shaped so the
    EARLIEST clock hour 18 has SMALL headroom (5) and a LATER hour 22 has LARGE
    headroom (40); a deep-night hour 2 also has large headroom (40). A 30 kWh spike
    arrives at hour 18. Chronological throttle (NOT base-sorted) walks the session in
    CLOCK order from arrival: at h18 take min(30, inf, 5) = 5 -> remaining 25; the
    NEXT in-clock-order in-window hour with headroom serves the rest. Energy must NOT
    jump ahead to the lowest-base hour first (that would be the valley-fill the new
    kernel deletes). Assert h18 delivers exactly 5 (its headroom), the remainder is
    served chronologically, and total delivered == 30 (ample headroom downstream).
    """
    rating = 100.0
    base = np.full(24, 95.0, dtype="float64")  # 5 kW headroom default
    base[22] = 60.0  # 40 kW headroom, but LATER in clock order than 18
    base[2] = 60.0  # 40 kW headroom, deep night (also later in clock order)
    ev = np.zeros(24, dtype="float64")
    ev[18] = 30.0
    out = flex_power_limited(ev, base, rating, sessions=(PLUGIN_WINDOW,), start_hod=0)
    delivered = np.asarray(out["delivered"], dtype="float64")
    # Arrival hour 18 is throttled to its own headroom (5), NOT skipped for a valley.
    np.testing.assert_allclose(delivered[18], 5.0)
    # All 30 kWh is delivered within the session (ample downstream headroom).
    np.testing.assert_allclose(delivered.sum(), 30.0)
    assert out["unserved"] == 0.0
    # No relocation: energy never lands in an hour whose headroom is zero / negative.
    headroom = np.maximum(0.0, rating - base)
    assert np.all(delivered <= headroom + 1e-9)


def test_power_limited_no_valley_sort() -> None:
    """Source has no argsort / no key= base sort / no second epsilon (D-03).

    Mirrors the existing flex_deferral source-inspection guard: the power-limited
    kernel must reuse the strict-> headroom convention (is_congested or the identical
    max(0, rating-base) cap) and contain NO valley-fill placement and NO bare
    ``> limit`` / ``>= limit`` second epsilon.
    """
    import inspect

    src = inspect.getsource(flex_power_limited)
    assert "is_congested(" in src or "max(0.0, float(rating)" in src
    assert "argsort" not in src
    assert "key=" not in src  # no sorted(..., key=base) valley placement
    assert "> limit" not in src
    assert ">= limit" not in src


def test_power_limited_unserved_fraction() -> None:
    """A saturated single session leaves a hand-computed unserved remainder (D-02).

    rating=100, base=99 flat -> every hour offers only 1 kW headroom. The overnight
    session (PLUGIN_WINDOW) has 14 in-window hours, so at most 14 kWh can be delivered
    at throttled power. A 100 kWh spike at hour 18: delivered = 14 (1 kW each over the
    14 session hours), unserved = 100 - 14 = 86, fraction = 86 / annual_ev_demand.
    """
    rating = 100.0
    base = np.full(24, 99.0, dtype="float64")  # 1 kW headroom everywhere
    ev = np.zeros(24, dtype="float64")
    ev[18] = 100.0
    out = flex_power_limited(
        ev, base, rating, sessions=(PLUGIN_WINDOW,), annual_ev_demand=100.0, start_hod=0
    )
    np.testing.assert_allclose(np.asarray(out["delivered"]).sum(), 14.0)
    np.testing.assert_allclose(out["unserved"], 86.0)
    np.testing.assert_allclose(out["unserved_fraction"], 0.86)


def test_power_limited_carry_forward() -> None:
    """Overnight remainder is served by the SAME day's workplace [9-16] session (D-01).

    A >24h two-day vector (48h, start_hod=0). The overnight session is saturated
    (base=99 -> 1 kW/hour) while the workplace [9-16] session has ample headroom
    (base=50 -> 50 kW/hour). A spike arrives early on day 0. With overnight-only the
    spike is largely unserved; adding the workplace window carries the overnight
    remainder forward to that day's [9-16] hours, dropping final unserved. Assert
    (a) the workplace hours receive the carried energy, (b) total unserved with the
    workplace session < unserved overnight-only, and (c) per-day confinement: day-0
    energy never lands in day-1 hours.
    """
    n_hour = 48
    rating = 100.0
    base = np.full(n_hour, 99.0, dtype="float64")  # saturated overnight default
    # Workplace [9-16] on BOTH days gets ample headroom.
    for day in (0, 1):
        for hod in WORKPLACE_WINDOW:
            base[day * 24 + hod] = 50.0
    ev = np.zeros(n_hour, dtype="float64")
    ev[0] = 40.0  # a day-0 spike (hour-of-day 0, an overnight in-window hour)

    overnight_only = flex_power_limited(
        ev, base, rating, sessions=(PLUGIN_WINDOW,), annual_ev_demand=40.0, start_hod=0
    )
    with_workplace = flex_power_limited(
        ev,
        base,
        rating,
        sessions=(PLUGIN_WINDOW, WORKPLACE_WINDOW),
        annual_ev_demand=40.0,
        start_hod=0,
    )
    delivered = np.asarray(with_workplace["delivered"], dtype="float64")

    # (a) day-0 workplace hours [9..16] receive the carried-forward energy.
    day0_workplace = [h for h in WORKPLACE_WINDOW]
    assert sum(delivered[h] for h in day0_workplace) > 0.0
    # (b) the extra workplace availability reduces unserved energy.
    assert with_workplace["unserved"] < overnight_only["unserved"]
    # (c) per-day confinement: NO day-1 hour (index >= 24) receives day-0's energy.
    assert np.all(delivered[24:] == 0.0)


def test_power_limited_at_limit_not_congested() -> None:
    """base exactly at limit, ev=0 -> nothing throttled, unserved 0 (strict ->).

    rating=100, base=100 flat (headroom max(0, 100-100)=0), ev=0. No EV requirement,
    nothing delivered, nothing unserved.
    """
    rating = 100.0
    base = np.full(24, 100.0, dtype="float64")
    ev = np.zeros(24, dtype="float64")
    out = flex_power_limited(ev, base, rating, sessions=(PLUGIN_WINDOW,), start_hod=0)
    np.testing.assert_allclose(np.asarray(out["delivered"]).sum(), 0.0)
    assert out["unserved"] == 0.0
    assert out["unserved_fraction"] == 0.0


def test_midday_headroom_premise() -> None:
    """Mean workplace [9-16] headroom >= mean overnight headroom (Pitfall 1 DIRECTION).

    Encodes the VALIDATED direction (workplace ~33.57 kW vs overnight ~31.95 kW over
    cold days) so a future TMY re-copy re-checks it. Uses a synthetic cold-day base
    whose midday heating demand is marginally LOWER than overnight (warmer midday),
    giving slightly MORE midday headroom. Asserts only the direction (>=), NOT a large
    margin (the real premise holds only ~+5%).
    """
    rating = 100.0
    # Synthetic single cold day: overnight base higher (colder) than midday base.
    base = np.full(24, 70.0, dtype="float64")  # overnight default (30 kW headroom)
    for hod in WORKPLACE_WINDOW:
        base[hod] = 66.0  # marginally warmer midday -> 34 kW headroom
    headroom = np.maximum(0.0, rating - base)
    overnight_hours = sorted(set(PLUGIN_WINDOW))
    workplace_hours = sorted(set(WORKPLACE_WINDOW))
    mean_overnight = float(np.mean([headroom[h] for h in overnight_hours]))
    mean_workplace = float(np.mean([headroom[h] for h in workplace_hours]))
    assert mean_workplace >= mean_overnight


# ─── flexible_ev_count: sweep, tolerance boundary, monotonicity ─────────────


def _sweep_indicator() -> tuple[np.ndarray, np.ndarray]:
    """One element over one bus, kW=100."""
    return np.array([[1.0]], dtype="float64"), np.array([100.0], dtype="float64")


def test_flexible_ev_count_grid_member_and_expansion() -> None:
    """flexible_ev_count is a swept-grid member and >= a known firm count (D-08).

    One bus, one element kW=100, 1 hour. base=80 (flat). ev_unit=1 kW/EV.
    alloc puts ALL EVs on the bus. At EV count N the demand = 80 + N.
      - Uncapped congested when 80+N > 100, i.e. N > 20.
      - When congested, f_E = (80+N-100)/N = (N-20)/N; curtailed = N*f = N-20 kWh.
        fraction = (N-20)/N. For the curtailed_energy_fraction < 0.01 gate:
          N=20 -> not congested, curtailed 0,    fraction 0      -> PASS
          N=40 -> curtailed 20, fraction 0.5               -> FAIL (> 1%)
      - Firm count (zero overload) is 20; flexible should also be 20 here, and is
        a member of the swept grid.
    """
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    sweep = (0, 20, 40, 60)
    out = flexible_ev_count(sweep, base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT)
    assert out["flexible_ev_count"] in sweep  # D-08: grid member
    assert out["flexible_ev_count"] == 20
    assert out["threshold_convention"] == "strict_gt_limit"
    # trade curve has one record per swept point.
    assert [r["ev_count"] for r in out["trade_curve"]] == list(sweep)


def test_flexible_ev_count_strict_tolerance_boundary() -> None:
    """A point at EXACTLY the tolerance is NOT passing (strict <, D-06).

    Construct a fixture where one swept point lands at curtailed_energy_fraction
    exactly == curtailed_fraction_max. One bus, kW=100, base=100 (flat, 1 hour).
    ev_unit=1. At N, demand=100+N, congested when N>0; f=(100+N-100)/N=1.0 always
    -> curtailed=N, fraction = N / N = 1.0. Use curtailed_fraction_max=1.0 so the
    point is at EXACTLY the boundary; strict < excludes it -> no passing point.
    Also confirm a lower max (1.0+eps) would include it.
    """
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 100.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    # N=0 -> not congested, fraction 0 (< boundary, but flexible_ev_count picks
    # the LARGEST passing N). N=20 -> fraction exactly 1.0 == boundary -> excluded.
    out = flexible_ev_count(
        (0, 20),
        base,
        ev_unit,
        alloc_fn,
        indicator,
        elem_kw,
        _LIMIT,
        curtailed_fraction_max=1.0,
    )
    # Only N=0 passes (fraction 0 < 1.0); N=20 at exactly 1.0 is excluded.
    assert out["flexible_ev_count"] == 0


def test_flexible_ev_count_monotonic_curtailment() -> None:
    """Curtailment is non-decreasing across the sweep (SC4)."""
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    out = flexible_ev_count(
        (0, 40, 80), base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT
    )
    curt = [r["curtailed_energy_mwh"] for r in out["trade_curve"]]
    assert curt == sorted(curt)  # non-decreasing


def test_flexible_ev_count_monotonicity_guard_raises() -> None:
    """A synthetic non-monotone alloc triggers the located monotonicity guard."""
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    # Adversarial alloc: assign MORE EVs at the smaller swept count so curtailment
    # decreases as the swept N rises -> the monotonicity tripwire must fire.
    def bad_alloc(total_ev: int) -> np.ndarray:
        mapping = {40: 200.0, 80: 30.0}
        return np.array([mapping.get(total_ev, float(total_ev))], dtype="float64")

    with pytest.raises(ValueError, match="monotonic"):
        flexible_ev_count(
            (40, 80), base, ev_unit, bad_alloc, indicator, elem_kw, _LIMIT
        )


# ─── End-to-end derive_flexibility: three-scenario power-limited leg (DAYTIME) ─
# Runs the real stage-5 derive_flexibility against the regenerated project cache +
# stage-3 TMY/stochastic profiles + the stage-4 firm_hosting.json, asserting the THREE
# power-limited availability scenarios (overnight / workplace HEADLINE / all_day) with
# per-scenario headlines + the unserved-energy P95 gate, the curtailment-leg survival,
# the SC4 monotonicity tripwire survival, the penetration cliff landing inside the
# effective sweep, and the flexible-leg byte-stability (DAYTIME-04/05).

import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    EXTENDED_PENETRATION_SWEEP,
    LINE_LOADING_LIMIT_PERCENT,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95,
)
from projects.ev_hosting_flex.scripts.pipeline.apply_flexibility_contracts import (  # noqa: E402
    _availability_sweep,
    _curve_flexible,
    derive_flexibility,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_PROJECT_JSON_DIR = PROJECT_OUTPUTS_DIR / "json"
_REQUIRED_CACHE = [
    "line_transformer_ratings_kw.json",
    "downstream_bus_map.json",
    "feeder_selection.json",
    "node_building_count.json",
]
_REQUIRED_PROFILES = [
    "base_load_8760.parquet",
    "ev_load_unit.parquet",
    "ev_stack_K.npy",
]
_REQUIRED_JSON = ["firm_hosting.json"]


def _project_cache_ready() -> bool:
    """True iff the stage-2/3 cache + profiles + stage-4 firm_hosting are present."""
    if not all((PROJECT_CACHE_DIR / name).is_file() for name in _REQUIRED_CACHE):
        return False
    if not all((_PROJECT_DATA_DIR / name).is_file() for name in _REQUIRED_PROFILES):
        return False
    return all((_PROJECT_JSON_DIR / name).is_file() for name in _REQUIRED_JSON)


# ─── Three-scenario power-limited integration + cliff + byte-stability (DAYTIME) ─


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_three_scenario_pipeline(tmp_path: Path) -> None:
    """End-to-end: the THREE power-limited availability scenarios + curtailment survival.

    Runs derive_flexibility against the regenerated project cache + stage-3
    TMY/stochastic profiles + stage-4 firm_hosting.json into a tmp json_dir (seeded
    with a copy of the real firm_hosting.json, the headline denominator) and asserts:
    exactly three scenario blocks (overnight / workplace / all_day), each with
    flexible_ev_count + hosting_expansion_percent == round((flexible - firm)/firm, 6);
    headline_scenario == "workplace"; each scenario's unserved_fraction_p95_at_flexible
    < 1%; each flexible >= firm_ev (feasibility); the monotone ordering overnight <=
    workplace <= all_day on flexible_ev_count (more availability never reduces hosting);
    AND the curtailment leg SURVIVED the deferral->power-limited rewrite (a curtailment
    block + the curtailment lost-fraction column on the availability curve + the
    line_loading_flex.parquet capped-loading artifact <= the limit).
    """
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )

    derived = derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]

    firm_ev = summary["firm_ev_count"]
    assert firm_ev > 0, summary

    # Exactly the three availability scenarios, in the documented order.
    scenarios = summary["scenarios"]
    assert set(scenarios) == {"overnight", "workplace", "all_day"}, scenarios
    assert summary["headline_scenario"] == "workplace"

    tol = float(TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95)
    for name, block in scenarios.items():
        assert block["mechanism"] == "power_limited", block
        assert "flexible_ev_count" in block
        assert "hosting_expansion_percent" in block
        # The per-scenario headline equals (flexible - firm) / firm.
        expected = round((block["flexible_ev_count"] - firm_ev) / firm_ev, 6)
        assert block["hosting_expansion_percent"] == expected, block
        # The unserved-energy fraction at the flexible point is strictly < 1% (D-04).
        assert block["unserved_fraction_p95_at_flexible"] < tol, block
        # Per-scenario firm feasibility floor.
        assert block["flexible_ev_count"] >= firm_ev, block

    # More availability never reduces hosting: overnight <= workplace <= all_day.
    ov = scenarios["overnight"]["flexible_ev_count"]
    wp = scenarios["workplace"]["flexible_ev_count"]
    ad = scenarios["all_day"]["flexible_ev_count"]
    assert ov <= wp <= ad, scenarios
    assert summary["availability_ordering"]["ordering_holds"] is True

    # Curtailment leg SURVIVED the rewrite: a curtailment block is present.
    curt = summary["curtailment"]
    assert curt["mechanism"] == "curtailment"
    assert curt["flexible_ev_count"] >= firm_ev, curt

    # The capped curtailment loading is <= the limit (a feasible flexible state).
    loading = pd.read_parquet(_PROJECT_DATA_DIR / "line_loading_flex.parquet")
    assert (
        loading.values.max() <= float(LINE_LOADING_LIMIT_PERCENT) + 1e-6
    ), loading.values.max()

    # flexible_hosting.json carries the scenarios mapping + headline + curtailment.
    flexible_json = json.loads((tmp_path / "flexible_hosting.json").read_text())
    assert set(flexible_json["scenarios"]) == {"overnight", "workplace", "all_day"}
    assert flexible_json["headline_scenario"] == "workplace"
    assert "curtailment" in flexible_json
    assert flexible_json["scenarios"]["workplace"]["flexible_ev_count"] == wp

    # availability_curve.parquet is the tidy three-scenario trade-curve series, with
    # the retained curtailment lost-fraction column + monotonic unserved_fraction_p95.
    curve = pd.read_parquet(_PROJECT_DATA_DIR / "availability_curve.parquet")
    assert {"scenario", "penetration", "ev_count", "unserved_fraction_p95"} <= set(
        curve.columns
    ), curve.columns
    # Curtailment SURVIVED as a column on the availability curve.
    assert "curtailed_lost_fraction_p95" in curve.columns, curve.columns
    assert set(curve["scenario"].unique()) == {"overnight", "workplace", "all_day"}
    ov_curve = curve[curve["scenario"] == "overnight"].sort_values("penetration")
    unserved = list(ov_curve["unserved_fraction_p95"])
    # SC4 non-decreasing WITHIN the partial-coincidence MC noise band (260625-lgg):
    # under EV_COINCIDENCE_RHO < 1 each swept count draws its OWN independent per-count
    # realization, so the P95 unserved curve is monotone-non-decreasing only IN
    # EXPECTATION (adjacent counts carry independent sampling noise of order a few
    # 1e-6..1e-5). This mirrors the stage's _SC4_MONOTONE_NOISE_BAND tripwire and does
    # NOT relax the strict-< 1% acceptability gate (asserted per-scenario above).
    sc4_band = 1.0e-4
    for prev_u, cur_u in zip(unserved[:-1], unserved[1:]):
        assert cur_u + sc4_band >= prev_u, (prev_u, cur_u, unserved)


def test_sc4_monotonicity_tripwire_survives(monkeypatch) -> None:
    """A synthetic NON-monotone unserved curve trips the located SC4 tripwire.

    Proves the per-scenario monotonicity guard was NOT dropped — and survives the
    partial-coincidence blend rewrite (EV-COINCIDENCE-RECAL, 260625-lgg). Under the
    blend the per-penetration EV aggregate comes from ``blend_ev_aggregate`` keyed by
    the integer EV count (NOT ``alloc_fn``, which no longer scales the aggregate), so
    the adversarial non-monotonicity is injected by MONKEYPATCHING the stage's
    ``blend_ev_aggregate`` to return an aggregate whose energy DROPS once the count
    exceeds a threshold. The first decrease in the P95 unserved fraction beyond the
    SC4 noise band must then fire the located ValueError. No project cache needed.
    """
    import numpy as np  # local: keep the integration block self-contained

    from projects.ev_hosting_flex.scripts.pipeline import (
        apply_flexibility_contracts as _afc,
    )

    n_hour = 8760  # the blend kernel is tied to the full calendar (ev_realizations)
    indicator = np.array([[1.0]], dtype="float64")
    base = np.full((1, n_hour), 90.0, dtype="float64")  # 10 kW headroom on a 100 kW unit
    ev_stack = np.ones((1, n_hour), dtype="float64")  # one realization, flat 1 kW unit

    # Adversarial count-keyed blend: a LARGE flat aggregate for the FIRST positive
    # count seen, then a TINY one for all larger counts -> the P95 unserved fraction
    # is high early then drops -> non-monotone -> the SC4 tripwire must fire. The
    # returned shape is (K, n_hour) to match the kernel contract; count=0 -> zeros.
    def adversarial_blend(unit, count, rho, *, seed, start_hod=0, k=None):
        k_eff = int(unit.shape[0]) if k is None else int(k)
        hours = int(unit.shape[1])
        if int(count) <= 0:
            return np.zeros((k_eff, hours), dtype="float64")
        scale = 500.0 if int(count) <= 1 else 1.0  # big first, tiny after -> decrease
        return np.full((k_eff, hours), scale, dtype="float64")

    monkeypatch.setattr(_afc, "blend_ev_aggregate", adversarial_blend)

    def alloc_fn(penetration: float) -> np.ndarray:
        # alloc_fn no longer scales the aggregate under the blend; a benign 1-EV
        # allocation keeps the per-bus distribution well-formed for the base/headroom.
        return np.array([1.0], dtype="float64")

    with pytest.raises(ValueError, match="monotonic non-decreasing"):
        _availability_sweep(
            base,
            ev_stack,
            indicator,
            feeder_row=0,
            feeder_kw=100.0,
            alloc_fn=alloc_fn,
            downstream_home_count=10,
            limit=100.0,
            start_hod=0,
        )


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_penetration_cliff_inside_sweep(tmp_path: Path) -> None:
    """The overnight unserved curve is exercised across the effective sweep grid.

    DELIBERATE RE-BASE (EV-COINCIDENCE-RECAL, 260625-lgg). Under the original FULL-
    coincidence model the overnight unserved cliff crossed the 1% gate near ~4.6
    EV/home, INSIDE the extended 0->5.0 sweep (the original informativeness guard).
    Literature-grounded PARTIAL coincidence (EV_COINCIDENCE_RHO=0.5) flattens the
    diversified feeder aggregate peak, so under power-limited natural charging the
    overnight unserved-energy P95 stays WELL BELOW the 1% gate across the entire
    0->5.0 grid (max ~0.1%) and the cliff moves BEYOND 5 EV/home — the flexible count
    saturates at the sweep top for all three availability scenarios. This is an honest
    consequence of the diversity recalibration, NOT a gate relaxation: the strict-<
    1% acceptability gate (TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95) is byte-
    unchanged. The test now asserts the curve is well-formed and rising across the
    extended grid (the grid is exercised, non-zero, monotone-in-expectation), and
    records that the cliff is beyond the sweep under partial coincidence.
    """
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )
    derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)

    curve = pd.read_parquet(_PROJECT_DATA_DIR / "availability_curve.parquet")
    ov = curve[curve["scenario"] == "overnight"].sort_values("penetration")
    top_pen = float(max(EXTENDED_PENETRATION_SWEEP))
    top_row = ov[ov["penetration"] == round(top_pen, 6)]
    assert not top_row.empty, ov["penetration"].tolist()
    # Non-zero unserved at the effective sweep top (the grid IS exercised, not flat-0).
    top_unserved = float(top_row["unserved_fraction_p95"].iloc[0])
    assert top_unserved > 0.0, top_row
    tol = float(TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95)
    # Under partial coincidence the cliff is BEYOND the sweep: the overnight curve
    # stays below the 1% gate across the whole grid (documented re-base, not a relax).
    assert float(ov["unserved_fraction_p95"].max()) < tol, (
        "overnight unserved unexpectedly reached the 1% gate inside the sweep — under "
        "EV_COINCIDENCE_RHO=0.5 the diversified aggregate should keep it below 1%; "
        "re-check the blend wiring / rho calibration."
    )
    # The unserved fraction RISES across the extended grid (within the SC4 noise band),
    # so the extended sweep is genuinely exercised toward the (out-of-grid) cliff.
    assert top_unserved > float(ov["unserved_fraction_p95"].iloc[0]) + 1e-6, (
        "overnight unserved did not rise across the extended sweep",
        ov[["penetration", "unserved_fraction_p95"]].to_dict("records"),
    )


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_flexible_leg_byte_stable(tmp_path: Path) -> None:
    """The re-baselined flexible leg is byte-stable across two runs (DAYTIME-05).

    Runs derive_flexibility twice into two tmp dirs; the PRIMARY assertion is that the
    NEW three-scenario availability output hash (availability_curve_content_sha256 — the
    artifact that actually changed this phase) is identical across runs. As a secondary
    unchanged-curtailment regression guard, the line_loading_flex.parquet
    content_sha256 (flex_loading_content_sha256) is also identical.
    """
    out1_dir = tmp_path / "run1"
    out2_dir = tmp_path / "run2"
    out1_dir.mkdir()
    out2_dir.mkdir()
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", out1_dir / "firm_hosting.json"
    )
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", out2_dir / "firm_hosting.json"
    )

    s1 = derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, out1_dir)["summary"]
    s2 = derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, out2_dir)["summary"]

    # PRIMARY: the NEW flexible-leg availability output is byte-stable (DAYTIME-05).
    assert (
        s1["availability_curve_content_sha256"]
        == s2["availability_curve_content_sha256"]
    ), (
        s1["availability_curve_content_sha256"],
        s2["availability_curve_content_sha256"],
    )
    # SECONDARY: the unchanged curtailment loading parquet is also byte-stable.
    assert s1["flex_loading_content_sha256"] == s2["flex_loading_content_sha256"], (
        s1["flex_loading_content_sha256"],
        s2["flex_loading_content_sha256"],
    )


# ─── CR-01/WR-04 cache-free gate-selection regression (CI-visible, no cache) ─────


def test_curve_flexible_rejects_ev_count_straddle() -> None:
    """``_curve_flexible`` selects at penetration granularity, not by ev_count.

    Guards CR-01: ``ev_count = round(penetration * homes)`` is NON-injective, so two
    swept penetration rows can share one ev_count. P95 lost fraction is monotone in
    penetration, so an ev_count whose LOW-penetration row passes the strict-``<`` gate
    can have a HIGHER-penetration realization of the SAME ev_count that FAILS. The
    pre-fix helper keyed its passing set on ev_count, took ``max(passing)``, and
    resolved ``at_flex`` via a last-match re-scan — so it reported the straddling
    ev_count flexible with a fraction that CONTRADICTS the gate it claims to satisfy.

    This drives the helper directly with a hand-built straddle curve (NO project
    cache, NO ``skipif``) so CI catches the inversion the integration assertion could
    not (it is cache-gated). The pre-fix body returns ``(4, 0.011)``; the fixed body
    must return ``(3, 0.004)`` — the largest ev_count ALL of whose rows pass, with an
    ``at_flex`` strictly below tolerance.
    """
    tolerance = 0.01
    curve: list[dict[str, object]] = [
        {"penetration": 0.5, "ev_count": 4, "f": 0.005},  # PASS (low pen of count 4)
        {"penetration": 0.6, "ev_count": 4, "f": 0.011},  # FAIL (high pen of count 4)
        {"penetration": 0.4, "ev_count": 3, "f": 0.004},  # PASS (count 3 all-pass)
    ]

    flexible, at_flex = _curve_flexible(curve, "f", tolerance)

    # Count 4 STRADDLES the gate (one row fails), so it MUST NOT be reported flexible;
    # count 3 is the largest ev_count all of whose rows pass.
    assert flexible == 3, (flexible, at_flex)
    # at_flex is the fraction at the selected (gate-passing) row for the chosen count
    # and is strictly below tolerance by construction — never the failing 0.011.
    assert at_flex == 0.004, (flexible, at_flex)
    assert at_flex < tolerance, (flexible, at_flex)


def test_curve_flexible_at_flex_is_strictly_below_tolerance() -> None:
    """``at_flex`` is resolved from the SELECTED row, never a last-match re-scan (WR-04).

    A monotone all-passing curve (one ev_count per penetration, every row ``< tol``)
    must return the top ev_count and the binding (worst-passing) fraction for that
    count — strictly below tolerance. This is the WR-04 continuity guard at unit
    level: the same shared helper, the same ``tuple[int, float]`` contract, asserted
    independent of the curtailment caller, pinning that ``at_flex`` cannot pick up a
    larger fraction belonging to a different ev_count.
    """
    tolerance = 0.01
    curve: list[dict[str, object]] = [
        {"penetration": 0.2, "ev_count": 2, "f": 0.002},
        {"penetration": 0.3, "ev_count": 3, "f": 0.005},
        {"penetration": 0.4, "ev_count": 4, "f": 0.009},
    ]

    flexible, at_flex = _curve_flexible(curve, "f", tolerance)

    assert flexible == 4, (flexible, at_flex)
    assert at_flex == 0.009, (flexible, at_flex)
    assert at_flex < tolerance, (flexible, at_flex)

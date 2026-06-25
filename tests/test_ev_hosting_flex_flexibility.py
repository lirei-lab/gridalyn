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
    AVAILABILITY_SCENARIOS,
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
    out = flex_power_limited(
        ev, base, rating, sessions=(PLUGIN_WINDOW,), start_hod=0
    )
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


# ─── End-to-end derive_flexibility: BOTH curves (10.1, RECAL-07/08, D-10) ─────
# Runs the real stage-5 derive_flexibility against the regenerated project cache +
# stage-3 TMY/stochastic profiles + the stage-4 firm_hosting.json, asserting BOTH
# flexibility curves (curtailment + in-window deferral) with per-mechanism
# headlines, the deferral P95 gate, and the firm <= curtail <= defer ordering.

import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    LINE_LOADING_LIMIT_PERCENT,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95,
)
from projects.ev_hosting_flex.scripts.pipeline.apply_flexibility_contracts import (  # noqa: E402
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


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_derive_flexibility_both_curves(tmp_path: Path) -> None:
    """End-to-end: BOTH curves with per-mechanism headlines + the deferral P95 gate.

    Runs derive_flexibility against the regenerated project cache + stage-3
    TMY/stochastic profiles + stage-4 firm_hosting.json into a tmp json_dir (seeded
    with a copy of the real firm_hosting.json, the headline denominator) and
    asserts: BOTH a curtailment and a deferral block, each with a distinct
    flexible_ev_count + hosting_expansion_percent; the deferral curve's irreducible-
    lost-fraction P95 < 1%; the firm <= curtail-flexible <= defer-flexible ordering;
    the capped curtailment loading <= the limit; and the two-curve trade-curve
    parquet.
    """
    # derive_flexibility reads firm_hosting.json from json_dir; seed the tmp dir
    # with the real stage-4 output so the run is hermetic w.r.t. its writes.
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )

    derived = derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]

    firm_ev = summary["firm_ev_count"]
    assert firm_ev > 0, summary

    # BOTH curve blocks, each with a distinct per-mechanism headline (D-10).
    curt = summary["curtailment"]
    defer = summary["deferral"]
    assert curt["mechanism"] == "curtailment"
    assert defer["mechanism"] == "deferral"
    for block in (curt, defer):
        assert "flexible_ev_count" in block
        assert "hosting_expansion_percent" in block
        # The per-mechanism headline equals (flexible - firm) / firm.
        expected = round((block["flexible_ev_count"] - firm_ev) / firm_ev, 6)
        assert block["hosting_expansion_percent"] == expected, block

    # The deferral curve's irreducible-lost-fraction P95 is strictly < 1% (D-12).
    assert defer["irreducible_lost_fraction_p95_at_flexible"] < float(
        TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95
    ), defer

    # The trade-curve ordering holds: firm <= curtail-flexible <= defer-flexible.
    assert firm_ev <= curt["flexible_ev_count"] <= defer["flexible_ev_count"], summary
    assert summary["trade_curve_ordering"]["ordering_holds"] is True

    # The capped curtailment loading is <= the limit (a feasible flexible state).
    loading = pd.read_parquet(_PROJECT_DATA_DIR / "line_loading_flex.parquet")
    assert (
        loading.values.max() <= float(LINE_LOADING_LIMIT_PERCENT) + 1e-6
    ), loading.values.max()

    # flexible_hosting.json carries both curve blocks.
    flexible_json = json.loads((tmp_path / "flexible_hosting.json").read_text())
    assert "curtailment" in flexible_json
    assert "deferral" in flexible_json
    assert (
        flexible_json["curtailment"]["flexible_ev_count"] == curt["flexible_ev_count"]
    )
    assert flexible_json["deferral"]["flexible_ev_count"] == defer["flexible_ev_count"]

    # contract_activations.parquet is the tidy two-curve trade-curve series, with
    # both mechanisms' P95 lost fractions monotonic non-decreasing in ev_count.
    activations = pd.read_parquet(_PROJECT_DATA_DIR / "contract_activations.parquet")
    assert "ev_count" in activations.columns
    assert "curtailed_lost_fraction_p95" in activations.columns
    assert "irreducible_lost_fraction_p95" in activations.columns
    curve = activations.sort_values("penetration")
    curt_fracs = list(curve["curtailed_lost_fraction_p95"])
    assert curt_fracs == sorted(curt_fracs), curt_fracs


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_deferral_curve_persisted_fresh_and_consistent(tmp_path: Path) -> None:
    """``deferral_curve.parquet`` is written fresh and agrees with the headline.

    Regression guard for the artifact-integrity defect where stage 5 computed the
    corrected per-penetration deferral trade-curve in memory but NEVER wrote it,
    leaving a STALE ORPHAN ``deferral_curve.parquet`` on disk (the buggy
    0-loss / feasible-to-14-EVs global-pooling curve) inconsistent with the
    corrected deferral headline (5 EVs). The fix persists the curve and registers
    it in the report; this test asserts:

      * the parquet EXISTS and is FRESH (re-written by THIS run, mtime advances);
      * it carries the five-column deferral schema with the ``deferral_feasible``
        gate == ``irreducible_lost_fraction_p95 < tolerance``;
      * its deferral-flexible point (largest ev_count whose P95 irreducible-lost
        fraction < tolerance) EQUALS ``flexible_hosting.json``'s
        ``deferral.flexible_ev_count`` (the consistency guard);
      * the curve shows the cliff (NOT 0.0 everywhere).
    """
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )
    curve_path = _PROJECT_DATA_DIR / "deferral_curve.parquet"
    before = curve_path.stat().st_mtime if curve_path.is_file() else -1.0

    derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)

    # Persisted + freshly re-written by THIS run (would have caught the orphan).
    assert curve_path.is_file(), curve_path
    assert curve_path.stat().st_mtime > before, "deferral_curve.parquet went stale"

    curve = pd.read_parquet(curve_path)
    expected_cols = {
        "penetration",
        "ev_count",
        "curtailed_lost_fraction_p95",
        "irreducible_lost_fraction_p95",
        "deferral_feasible",
    }
    assert expected_cols <= set(curve.columns), curve.columns

    tol = float(TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95)
    # The persisted gate column equals the strict-< tolerance gate exactly.
    recomputed = curve["irreducible_lost_fraction_p95"] < tol
    assert (curve["deferral_feasible"].astype(bool) == recomputed).all(), curve

    # The curve is NOT degenerate-0 everywhere: a real cliff exists.
    assert float(curve["irreducible_lost_fraction_p95"].max()) > 0.0, curve

    # Consistency guard: the persisted curve's deferral-flexible point (largest
    # passing ev_count) == the headline deferral.flexible_ev_count.
    passing = curve.loc[curve["deferral_feasible"].astype(bool), "ev_count"]
    persisted_flexible = int(passing.max()) if len(passing) else 0

    headline = json.loads((tmp_path / "flexible_hosting.json").read_text())
    assert persisted_flexible == int(headline["deferral"]["flexible_ev_count"]), (
        persisted_flexible,
        headline["deferral"]["flexible_ev_count"],
    )

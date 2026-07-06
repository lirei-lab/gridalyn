"""Unit + governed tests for the AC power-flow validation layer (stage 7).

Three tiers, mirroring the project's test conventions:

1. HAND-COMPUTED KERNEL TESTS — cache-free unit tests of the profile builders
   and the violation counters in ``_powerflow.py`` (no pandapower net needed).
2. MINI-NET CONVERGENCE — a 3-bus real pandapower net through the 24-hour
   kernel, asserting output shapes and physical sanity.
3. GOVERNED REPRODUCE-AND-PIN — reads the EMITTED ``powerflow_violations.json``
   (skipif absent, like the other cache-dependent tests) and asserts the
   before/after invariants: violations grow monotonically with network-wide EV
   adoption, and the feeder flexibility clip keeps the study transformer at or
   under its rating.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._powerflow import (
    N_DESIGN_HOURS,
    base_profile_per_home_kw,
    clip_to_headroom,
    count_violations,
    ev_profile_per_home_kw,
    run_design_day_powerflow,
)
from projects.ev_hosting_flex.scripts.config import (
    BG_KW,
    CHARGING_WINDOW,
    DIVERSITY_FACTOR,
    EV_UNIT_KW,
    NETWORK_PENETRATION_SCENARIOS,
    PROJECT_OUTPUTS_DIR,
    R_THERM,
    T_BALANCE,
)

_VIOLATIONS_PATH = PROJECT_OUTPUTS_DIR / "json" / "powerflow_violations.json"
_REPORT_PATH = (
    PROJECT_OUTPUTS_DIR / "reports" / "powerflow_validation_report.json"
)
_SKIP_REASON = (
    "governed powerflow artifacts (outputs/json/powerflow_violations.json / "
    "outputs/reports/powerflow_validation_report.json) not present; run "
    "validate_powerflow.py first (outputs are gitignored)"
)


# ─── 1. Hand-computed kernel tests (cache-free) ──────────────────────────


def test_base_profile_design_cold_reproduces_admd() -> None:
    """At the −25 °C design cold the heating-degree base lands at ~6.5 kW/home."""
    temps = np.full(N_DESIGN_HOURS, -25.0)
    profile = base_profile_per_home_kw(temps)
    expected = (float(T_BALANCE) + 25.0) / float(R_THERM) + float(BG_KW)
    assert profile.shape == (N_DESIGN_HOURS,)
    assert profile == pytest.approx(np.full(N_DESIGN_HOURS, expected))
    assert expected == pytest.approx(6.5, abs=0.02)  # the ADMD anchor


def test_base_profile_clamps_above_balance_point() -> None:
    """Above T_BALANCE the heating term is zero — only BG_KW remains."""
    temps = np.full(N_DESIGN_HOURS, float(T_BALANCE) + 10.0)
    assert base_profile_per_home_kw(temps) == pytest.approx(
        np.full(N_DESIGN_HOURS, float(BG_KW))
    )


def test_ev_profile_window_and_scaling() -> None:
    """The EV overlay sits flat inside CHARGING_WINDOW and scales linearly."""
    start, end = CHARGING_WINDOW
    one = ev_profile_per_home_kw(1.0)
    coincident = float(EV_UNIT_KW) * float(DIVERSITY_FACTOR)
    assert one[start:end] == pytest.approx(np.full(end - start, coincident))
    outside = np.concatenate([one[:start], one[end:]])
    assert outside == pytest.approx(np.zeros(N_DESIGN_HOURS - (end - start)))
    assert ev_profile_per_home_kw(0.0) == pytest.approx(np.zeros(N_DESIGN_HOURS))
    assert ev_profile_per_home_kw(1.5) == pytest.approx(1.5 * one)
    with pytest.raises(ValueError, match="penetration"):
        ev_profile_per_home_kw(-0.1)


def test_clip_to_headroom_hand_computed() -> None:
    """The clip never lets base + EV exceed the rating; zero headroom clips to 0."""
    ev = np.full(N_DESIGN_HOURS, 10.0)
    base = np.full(N_DESIGN_HOURS, 65.0)
    base[5] = 75.0  # over-rating hour -> zero headroom
    clipped = clip_to_headroom(ev, base, 71.25)
    assert clipped[0] == pytest.approx(6.25)
    assert clipped[5] == pytest.approx(0.0)
    # The clip guarantees the EV ADDITION never pushes past the rating; a base
    # already over the rating stays as-is (the clip adds zero on top of it).
    assert np.all(base + clipped <= np.maximum(base, 71.25) + 1e-12)
    with pytest.raises(ValueError, match="rating_kw"):
        clip_to_headroom(ev, base, 0.0)


def test_count_violations_hand_built_frames() -> None:
    """Element counters count distinct violating elements, not violating hours."""
    volt = pd.DataFrame(
        {
            "hour": [0, 1, 0, 1],
            "bus": [1, 1, 2, 2],  # bus 1 dips twice, bus 2 stays healthy
            "vm_pu": [0.910, 0.905, 0.960, 0.955],
        }
    )
    lines = pd.DataFrame(
        {"hour": [0, 1], "line": [0, 0], "loading_percent": [101.0, 99.0]}
    )
    trafos = pd.DataFrame(
        {"hour": [0, 1], "trafo": [0, 0], "loading_percent": [80.0, 85.0]}
    )
    out = count_violations(
        {"bus_voltage": volt, "line_loading": lines, "trafo_loading": trafos},
        lv_bus_ids=np.array([1, 2]),
    )
    assert out["n_lv_buses_below_normal"] == 1  # bus 1 once, despite 2 hours
    assert out["n_lv_buses_below_extreme"] == 0
    assert out["n_lines_over_100"] == 1
    assert out["n_trafos_over_100"] == 0
    assert out["min_lv_vm_pu"] == pytest.approx(0.905)
    assert out["max_trafo_loading_percent"] == pytest.approx(85.0)


# ─── 2. Mini-net convergence ─────────────────────────────────────────────


def test_run_design_day_powerflow_mini_net() -> None:
    """A 3-bus real pandapower net solves all 24 hours with sane shapes/values."""
    import pandapower as pp

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_lv1 = pp.create_bus(net, vn_kv=0.24)
    b_lv2 = pp.create_bus(net, vn_kv=0.24)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv1, sn_mva=0.075, vn_hv_kv=25.0,
        vn_lv_kv=0.24, vk_percent=2.0, vkr_percent=1.2, pfe_kw=0.25,
        i0_percent=0.4,
    )
    pp.create_line_from_parameters(
        net, from_bus=b_lv1, to_bus=b_lv2, length_km=0.03,
        r_ohm_per_km=0.3, x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.2,
    )
    pp.create_load(net, bus=b_lv2, p_mw=0.0)

    p_kw = np.full((1, N_DESIGN_HOURS), 6.5)
    results = run_design_day_powerflow(net, p_kw, slack_vm_pu=1.04)

    assert len(results["bus_voltage"]) == 3 * N_DESIGN_HOURS
    assert len(results["line_loading"]) == 1 * N_DESIGN_HOURS
    assert len(results["trafo_loading"]) == 1 * N_DESIGN_HOURS
    vm = results["bus_voltage"]["vm_pu"]
    assert float(vm.max()) <= 1.04 + 1e-6  # nothing above the slack setpoint
    assert float(vm.min()) > 0.95  # a 6.5 kW load barely dips this mini net
    with pytest.raises(ValueError, match="p_kw_by_load"):
        run_design_day_powerflow(net, np.zeros((2, N_DESIGN_HOURS)))


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ─────────────


@pytest.mark.skipif(not _VIOLATIONS_PATH.is_file(), reason=_SKIP_REASON)
def test_governed_violations_monotonic_in_penetration() -> None:
    """Thermal + voltage violations never DECREASE as network EV adoption grows."""
    payload = json.loads(_VIOLATIONS_PATH.read_text())
    scenarios = payload["scenarios"]
    names = [f"network_pen_{p:.1f}" for p in NETWORK_PENETRATION_SCENARIOS]
    assert all(name in scenarios for name in names), sorted(scenarios)
    for key in ("n_trafos_over_100", "n_lv_buses_below_normal"):
        series = [scenarios[name][key] for name in names]
        assert series == sorted(series), f"{key} not monotonic: {series}"
    min_v = [scenarios[name]["min_lv_vm_pu"] for name in names]
    assert min_v == sorted(min_v, reverse=True), f"min V not decreasing: {min_v}"


@pytest.mark.skipif(not _VIOLATIONS_PATH.is_file(), reason=_SKIP_REASON)
def test_governed_feeder_clip_respects_rating() -> None:
    """The deferral-clipped feeder scenario stays at/below the physical rating.

    The AC loading is apparent-power based (kW / PF plus losses), so the cap is
    the rating in kVA terms — loading ≤ 100%, strictly above the firm scenario
    (12 clipped EVs draw more than 6 unclipped ones) which itself sits above
    the EV-free base.
    """
    trafo = pd.read_parquet(
        PROJECT_OUTPUTS_DIR / "data" / "powerflow_trafo_loading.parquet"
    )
    payload = json.loads(_VIOLATIONS_PATH.read_text())
    feeder_idx = int(payload["feeder_transformer_idx"])
    peaks = (
        trafo[trafo["trafo"] == feeder_idx]
        .groupby("scenario")["loading_percent"]
        .max()
    )
    base = float(peaks["feeder_base_0ev"])
    firm = float(peaks[[k for k in peaks.index if k.startswith("feeder_firm_")][0]])
    flex = float(peaks[[k for k in peaks.index if k.startswith("feeder_flex_")][0]])
    assert base < firm < flex <= 100.0 + 1e-9


@pytest.mark.skipif(not _REPORT_PATH.is_file(), reason=_SKIP_REASON)
def test_governed_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT_PATH.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    summary = report["summary"]
    assert summary["n_powerflows"] == summary["n_scenarios"] * N_DESIGN_HOURS
    for key in ("pre_ev_min_lv_vm_pu", "post_ev_n_trafos_over_100", "slack_vm_pu"):
        assert key in summary, sorted(summary)

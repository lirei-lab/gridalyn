"""Unit + governed tests for the AC power-flow validation layer (stage 7).

Three tiers, mirroring the project's test conventions:

1. HAND-COMPUTED KERNEL TESTS — cache-free unit tests of the violation
   counters in ``_powerflow.py`` (no pandapower net needed).
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
    count_violations,
    extract_feeder_subnet,
    run_design_day_powerflow,
    run_feeder_mc,
)
from projects.ev_hosting_flex.scripts.config import (
    NETWORK_PENETRATION_SCENARIOS,
    PROJECT_OUTPUTS_DIR,
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


def test_extract_feeder_subnet_and_mc_mini_net() -> None:
    """Subnet extraction + MC runner on a hand-built 4-bus feeder subtree."""
    import pandapower as pp

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_lv = pp.create_bus(net, vn_kv=0.24)
    b_h1 = pp.create_bus(net, vn_kv=0.24)
    b_h2 = pp.create_bus(net, vn_kv=0.24)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.0)
    trafo_idx = pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv, sn_mva=0.075, vn_hv_kv=25.0,
        vn_lv_kv=0.24, vk_percent=2.0, vkr_percent=1.2, pfe_kw=0.25,
        i0_percent=0.4,
    )
    for b in (b_h1, b_h2):
        pp.create_line_from_parameters(
            net, from_bus=b_lv, to_bus=b, length_km=0.02,
            r_ohm_per_km=0.3, x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.2,
        )
        pp.create_load(net, bus=b, p_mw=0.0)

    subnet, load_buses, n_homes = extract_feeder_subnet(
        net, trafo_idx, [b_lv, b_h1, b_h2]
    )
    assert n_homes == 2
    assert sorted(load_buses) == [b_h1, b_h2]
    assert len(subnet.trafo) == 1 and len(subnet.line) == 2

    k = 3
    variants = {
        "flat_30kw": np.full((k, N_DESIGN_HOURS), 30.0),
        "flat_80kw": np.full((k, N_DESIGN_HOURS), 80.0),  # over the 71.25 kW
    }
    mc = run_feeder_mc(subnet, variants, np.full(N_DESIGN_HOURS, 1.0))
    assert len(mc) == 2 * k * N_DESIGN_HOURS
    peak = mc.groupby("variant")["trafo_loading_percent"].max()
    assert peak["flat_30kw"] < 100.0 < peak["flat_80kw"]
    with pytest.raises(ValueError, match="mv_vm_pu_hourly"):
        run_feeder_mc(subnet, variants, np.ones(3))


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
def test_governed_feeder_backstop_removes_overload_depth() -> None:
    """On the year's binding day the backstop caps the feeder near its rating.

    The peak day is the accepted tail of the P95 firm rule, so even the firm
    count may exceed 100 % there; what the mechanism guarantees is ORDER (base
    < unmanaged, curtailed < unmanaged) and that the backstop-held load stays
    inside the kW-rating AC envelope (~rating/PF + losses, < 110 %) instead of
    the unmanaged depth.
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
    firm = float(
        peaks[[k for k in peaks.index if k.startswith("feeder_firm_")][0]]
    )
    unmanaged = float(
        peaks[[k for k in peaks.index if k.startswith("feeder_unmanaged_")][0]]
    )
    curtailed = float(
        peaks[[k for k in peaks.index if k.startswith("feeder_curtailed_")][0]]
    )
    assert base < firm < unmanaged
    assert curtailed < unmanaged
    assert curtailed < 110.0  # the kW-rating AC envelope (losses + reactive)


@pytest.mark.skipif(not _VIOLATIONS_PATH.is_file(), reason=_SKIP_REASON)
def test_governed_mc_sampling_shows_tail_overloads() -> None:
    """The cold-day AC sampling makes the overload tail visible and ordered.

    Base never overloads; the firm count overloads on a small fraction of cold
    days (the tail the P95 kW rule accepts, AMPLIFIED in AC by losses/reactive
    flow — the reported AC-vs-kW gap); unmanaged is strictly worse than firm;
    the backstop removes the overload DEPTH (max peak well below unmanaged)
    even though it enforces the kW rating, which in AC sits a few % above 100.
    """
    payload = json.loads(_VIOLATIONS_PATH.read_text())
    mc = payload["feeder_mc"]
    by_prefix = {
        name.split("_")[1]: stats for name, stats in mc.items()
    }  # base / firm / unmanaged / curtailed
    assert by_prefix["base"]["p_overload_ac"] == 0.0
    assert 0.0 < by_prefix["firm"]["p_overload_ac"] < 0.5
    assert (
        by_prefix["firm"]["p_overload_ac"] <= by_prefix["unmanaged"]["p_overload_ac"]
    )
    assert (
        by_prefix["curtailed"]["peak_loading_max"]
        < by_prefix["unmanaged"]["peak_loading_max"]
    )
    # The backstop binds AT the kW rating: AC peaks just above 100%, never deep.
    assert by_prefix["curtailed"]["peak_loading_max"] < 110.0


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

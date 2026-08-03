"""Unit + governed tests for the full-net voltage-risk diagnostic stage.

Tiers: (1) hand-built full net AC kernel, (2) mini adoption sweep, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import network_min_voltage


def test_network_min_voltage_mini_net() -> None:
    """A hand-built MV->trafo->LV net: min LV voltage drops as load rises, the
    MV/slack bus is excluded, and lightsim and numba agree."""
    import pandapower as pp

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_lv = pp.create_bus(net, vn_kv=0.4)
    b_h1 = pp.create_bus(net, vn_kv=0.4)
    b_h2 = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv, sn_mva=0.1, vn_hv_kv=25.0, vn_lv_kv=0.4,
        vk_percent=4.0, vkr_percent=1.2, pfe_kw=0.3, i0_percent=0.4,
    )
    for b in (b_h1, b_h2):
        pp.create_line_from_parameters(
            net, from_bus=b_lv, to_bus=b, length_km=0.08, r_ohm_per_km=0.4,
            x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.3,
        )
        pp.create_load(net, bus=b, p_mw=0.0)
    light = network_min_voltage(net, np.array([2.0, 2.0]), slack_vm_pu=1.0)
    heavy = network_min_voltage(net, np.array([40.0, 40.0]), slack_vm_pu=1.0)
    numba = network_min_voltage(
        net, np.array([40.0, 40.0]), use_lightsim=False, slack_vm_pu=1.0
    )
    assert heavy < light <= 1.0          # heavier load -> lower min LV voltage
    assert abs(heavy - numba) < 1e-6     # lightsim and numba agree


def test_adoption_network_voltage_stats_mini() -> None:
    """A mini full net: P(undervoltage) rises and the min-voltage tail falls as
    the EV adoption grows."""
    import pandapower as pp

    from projects.ev_hosting_flex.scripts.pipeline.analyze_voltage_risk_network import (
        _adoption_network_voltage_stats,
    )

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_lv = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.04)
    pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv, sn_mva=0.05, vn_hv_kv=25.0, vn_lv_kv=0.4,
        vk_percent=4.0, vkr_percent=1.2, pfe_kw=0.25, i0_percent=0.4,
    )
    b_h = pp.create_bus(net, vn_kv=0.4)
    pp.create_line_from_parameters(
        net, from_bus=b_lv, to_bus=b_h, length_km=0.12, r_ohm_per_km=0.5,
        x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.3,
    )
    pp.create_load(net, bus=b_h, p_mw=0.0)
    # 2 cold days; per-load base ~ (1 load, 48 h) heavy evening; evbar evening EV
    base = np.tile(np.concatenate([np.full(20, 6.0), np.full(4, 9.0)]), 2)
    per_load_base_annual = base[None, :].astype(np.float64)     # (1 load, 48 h)
    evbar = np.zeros(48)
    evbar[20:24] = 3.0
    evbar[44:48] = 3.0
    cold = [0, 1]
    lo = _adoption_network_voltage_stats(
        net, per_load_base_annual, [evbar], cold, 1, 0.0, 0.917
    )
    hi = _adoption_network_voltage_stats(
        net, per_load_base_annual, [evbar], cold, 1, 3.0, 0.917
    )
    assert hi["min_v_worst"] <= lo["min_v_worst"]     # heavier -> lower tail
    assert hi["p_undervolt"] >= lo["p_undervolt"]


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ─────────────

from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_VOLT = PROJECT_OUTPUTS_DIR / "json" / "voltage_risk_network.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "voltage_risk_network_report.json"
_SKIP = (
    "voltage_risk_network.json not present; run "
    "analyze_voltage_risk_network.py first (outputs are gitignored)"
)


@pytest.mark.skipif(not _VOLT.is_file(), reason=_SKIP)
def test_governed_voltage_network() -> None:
    """Network undervoltage probability rises with adoption; the tail falls."""
    p = json.loads(_VOLT.read_text())
    assert p["p_undervolt_by_ev"] == sorted(p["p_undervolt_by_ev"])
    for key in ("min_v_p50_by_ev", "min_v_p05_by_ev", "min_v_worst_by_ev"):
        assert p[key] == sorted(p[key], reverse=True), f"{key} not falling"
    ref_i = p["ev_per_home_grid"].index(p["reference_ev_per_home"])
    assert (
        p["min_v_worst_at_ref"]
        <= p["min_v_p05_at_ref"]
        <= p["min_v_p50_by_ev"][ref_i]
    )


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_voltage_network_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    for key in ("p_undervolt_at_ref", "min_v_worst_at_ref",
                "first_risk_ev_per_home"):
        assert key in report["summary"], sorted(report["summary"])

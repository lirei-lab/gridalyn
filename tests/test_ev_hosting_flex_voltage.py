"""Unit + governed tests for the voltage-risk diagnostic stage.

Tiers: (1) hand-built feeder AC kernel, (2) mini adoption sweep, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import feeder_min_voltage


def test_feeder_min_voltage_mini_net() -> None:
    """A hand-built 2-home feeder: min LV voltage drops as the load rises, and
    the MV/slack bus is excluded from the minimum."""
    import pandapower as pp

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_lv = pp.create_bus(net, vn_kv=0.24)
    b_h1 = pp.create_bus(net, vn_kv=0.24)
    b_h2 = pp.create_bus(net, vn_kv=0.24)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv, sn_mva=0.075, vn_hv_kv=25.0, vn_lv_kv=0.24,
        vk_percent=2.0, vkr_percent=1.2, pfe_kw=0.25, i0_percent=0.4,
    )
    for b in (b_h1, b_h2):
        pp.create_line_from_parameters(
            net, from_bus=b_lv, to_bus=b, length_km=0.05, r_ohm_per_km=0.3,
            x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.2,
        )
        pp.create_load(net, bus=b, p_mw=0.0)
    light = feeder_min_voltage(net, np.array([2.0, 2.0]), slack_vm_pu=1.0)
    heavy = feeder_min_voltage(net, np.array([30.0, 30.0]), slack_vm_pu=1.0)
    assert 0.95 < heavy < light <= 1.0     # heavier load -> lower min LV voltage
    assert heavy < 1.0                     # LV buses sag below the 1.0 slack

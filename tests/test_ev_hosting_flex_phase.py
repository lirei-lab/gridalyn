"""Unit + governed tests for the phase-imbalance diagnostic stage.

Tiers: (1) hand-computed kernel, (2) mini 3-phase net convergence, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import vuf


def test_vuf_hand_computed() -> None:
    """Voltage unbalance factor = max deviation from the mean, over the mean (%)."""
    assert vuf(1.0, 1.0, 1.0) == pytest.approx(0.0)          # balanced -> 0
    # phases 0.90 / 1.00 / 1.00: mean 0.9667, max dev 0.0667 -> 6.897 %
    assert vuf(0.90, 1.00, 1.00) == pytest.approx(0.0667 / 0.96667 * 100.0, abs=5e-3)


def test_to_three_phase_mv_and_runpp_3ph_mini() -> None:
    """Build a tiny MV 3-phase net via the helper's conventions and solve it.

    This mirrors what to_three_phase_mv sets up (sequenced ext_grid, zero-seq
    line, Dyn transformer) on a hand-built 2-transformer MV stub, and confirms
    an unbalanced single-phase load pulls its phase down more than the others.
    """
    import pandapower as pp

    from projects.ev_hosting_flex.scripts._powerflow import _add_3ph_params_mini

    net = pp.create_empty_network()
    b_hv = pp.create_bus(net, vn_kv=120.0)
    b_mv = pp.create_bus(net, vn_kv=25.0)
    b_mv2 = pp.create_bus(net, vn_kv=25.0)
    pp.create_ext_grid(net, bus=b_hv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net, hv_bus=b_hv, lv_bus=b_mv, sn_mva=40.0, vn_hv_kv=120.0, vn_lv_kv=25.0,
        vk_percent=10.0, vkr_percent=0.5, pfe_kw=0.0, i0_percent=0.0, shift_degree=0,
    )
    pp.create_line_from_parameters(
        net, from_bus=b_mv, to_bus=b_mv2, length_km=5.0, r_ohm_per_km=0.3,
        x_ohm_per_km=0.4, c_nf_per_km=0.0, max_i_ka=0.4,
    )
    _add_3ph_params_mini(net, r0_mult=4.0, x0_mult=3.0)
    # a single-phase 2 MW load on phase A at the far MV bus
    pp.create_asymmetric_load(net, bus=b_mv2, p_a_mw=2.0, p_b_mw=0.0, p_c_mw=0.0,
                              q_a_mvar=0.0, q_b_mvar=0.0, q_c_mvar=0.0)
    pp.runpp_3ph(net)
    r = net.res_bus_3ph.loc[b_mv2]
    assert r.vm_a_pu < r.vm_b_pu           # loaded phase A sags below B/C
    assert r.vm_a_pu < r.vm_c_pu
    assert r.vm_a_pu < 1.0


def test_solve_phase_min_voltage_real_net() -> None:
    """The solve helper converges on the real twin MV net and the balanced case
    is at least as healthy as a round-robin single-phase case at the same load."""
    import pickle

    from projects.ev_hosting_flex.scripts.config import (
        PROJECT_CACHE_DIR, PHASE_R0_MULT, PHASE_X0_MULT,
    )
    from projects.ev_hosting_flex.scripts._powerflow import to_three_phase_mv
    from projects.ev_hosting_flex.scripts.pipeline.analyze_phase_imbalance import (
        _solve_phase_min_v,
    )

    cache = PROJECT_CACHE_DIR
    if not (cache / "pp_net_cache.pkl").is_file():
        pytest.skip("topology cache absent")
    net = pickle.load(open(cache / "pp_net_cache.pkl", "rb"))
    mv, pole_to_mv = to_three_phase_mv(net, r0_mult=PHASE_R0_MULT, x0_mult=PHASE_X0_MULT)
    trafos = sorted(pole_to_mv)
    # flat 20 kW per transformer
    load_kw = {t: 20.0 for t in trafos}
    bal = _solve_phase_min_v(mv, pole_to_mv, load_kw, balanced=True)
    unb = _solve_phase_min_v(mv, pole_to_mv, load_kw, balanced=False)
    assert 0.7 < unb["min_vm_pu"] <= bal["min_vm_pu"] <= 1.01
    assert unb["vuf"] >= bal["vuf"] - 1e-9      # unbalanced no less unbalanced

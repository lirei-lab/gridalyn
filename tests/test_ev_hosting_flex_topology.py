"""Unit tests for ``projects/ev_hosting_flex/scripts/_topology.py``.

Exercises the four project-local critical-path helpers (TWIN-02/03/04, D-02)
against a hand-computed tiny radial fixture with known kW ratings and known
downstream-bus sets, plus the real-net numeric anchors verified in RESEARCH.md
Code Examples (line0 ≈ 230.363 kW, trafo0 = 199.50 kW at pf=0.95).

The fixture mirrors a loaded pandapower ``net`` as a lightweight attribute-bag
of pandas DataFrames (``net.bus``, ``net.line``, ``net.trafo``, ``net.load``,
``net.ext_grid``, ``net.gen``, ``net.sgen``) — no ``import pandapower`` (GUARD-02).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._topology import (
    assert_radial_no_generation,
    build_downstream_map,
    line_rating_kw,
    select_feeder,
    trafo_rating_kw,
)


@dataclass
class _FakeNet:
    """Attribute-bag mirroring the pandapower ``net`` columns we read."""

    bus: pd.DataFrame
    line: pd.DataFrame
    trafo: pd.DataFrame
    load: pd.DataFrame
    ext_grid: pd.DataFrame
    gen: pd.DataFrame
    sgen: pd.DataFrame


def _radial_fixture() -> _FakeNet:
    """Hand-computed radial net: MV head → 1 distribution trafo → 2 LV buses.

    Topology (root = bus 0, the ext_grid)::

        bus0 (25 kV) --trafo0(25/0.4, 0.21 MVA)--> bus1 (0.4 kV)
        bus1 --line0(0.35 kA)--> bus2 (0.4 kV, load 0.1 MW)
        bus1 --line1(0.47 kA)--> bus3 (0.4 kV, load 0.2 MW)
    """
    bus = pd.DataFrame(
        {"vn_kv": [25.0, 0.4, 0.4, 0.4]},
        index=[0, 1, 2, 3],
    )
    line = pd.DataFrame(
        {
            "from_bus": [1, 1],
            "to_bus": [2, 3],
            "max_i_ka": [0.35, 0.47],
        },
        index=[0, 1],
    )
    trafo = pd.DataFrame(
        {
            "hv_bus": [0],
            "lv_bus": [1],
            "sn_mva": [0.21],
        },
        index=[0],
    )
    load = pd.DataFrame(
        {"bus": [2, 3], "p_mw": [0.1, 0.2]},
        index=[0, 1],
    )
    ext_grid = pd.DataFrame({"bus": [0]}, index=[0])
    empty_gen = pd.DataFrame({"bus": pd.Series([], dtype="int64")})
    return _FakeNet(
        bus=bus,
        line=line,
        trafo=trafo,
        load=load,
        ext_grid=ext_grid,
        gen=empty_gen.copy(),
        sgen=empty_gen.copy(),
    )


def _two_feeder_fixture() -> _FakeNet:
    """Two MV/LV (25/0.4) distribution trafos; trafo 1 carries the larger load.

    Used to prove deterministic max-downstream-load feeder selection picks the
    transformer index with the largest downstream building load.
    """
    bus = pd.DataFrame(
        {"vn_kv": [120.0, 25.0, 0.4, 0.4]},
        index=[0, 1, 2, 3],
    )
    # HV/MV head trafo (120/25) + two distribution trafos (25/0.4).
    trafo = pd.DataFrame(
        {
            "hv_bus": [0, 1, 1],
            "lv_bus": [1, 2, 3],
            "sn_mva": [15.0, 0.21, 0.21],
        },
        index=[0, 1, 2],
    )
    line = pd.DataFrame(
        {
            "from_bus": pd.Series([], dtype="int64"),
            "to_bus": pd.Series([], dtype="int64"),
            "max_i_ka": pd.Series([], dtype="float64"),
        }
    )
    # trafo index 1 (lv_bus 2) → 0.1 MW; trafo index 2 (lv_bus 3) → 0.3 MW (max)
    load = pd.DataFrame({"bus": [2, 3], "p_mw": [0.1, 0.3]}, index=[0, 1])
    ext_grid = pd.DataFrame({"bus": [0]}, index=[0])
    empty_gen = pd.DataFrame({"bus": pd.Series([], dtype="int64")})
    return _FakeNet(
        bus=bus,
        line=line,
        trafo=trafo,
        load=load,
        ext_grid=ext_grid,
        gen=empty_gen.copy(),
        sgen=empty_gen.copy(),
    )


# ─── TWIN-02: kW ratings ────────────────────────────────────────────────


def test_line_rating_kw() -> None:
    net = _radial_fixture()
    ratings = line_rating_kw(net, pf=0.95)
    # kW = max_i_ka * vn_from * √3 * 1000 * pf, vn_from = vn_kv(from_bus=1)=0.4
    expected0 = 0.35 * 0.4 * math.sqrt(3.0) * 1000.0 * 0.95
    expected1 = 0.47 * 0.4 * math.sqrt(3.0) * 1000.0 * 0.95
    assert ratings[0] == pytest.approx(expected0, rel=1e-9)
    assert ratings[1] == pytest.approx(expected1, rel=1e-9)


def test_line_rating_kw_real_net_anchor() -> None:
    # Real-net anchor: max_i_ka=0.35, vn_from=0.4 → 230.363 kW at pf=0.95.
    net = _radial_fixture()
    ratings = line_rating_kw(net, pf=0.95)
    assert ratings[0] == pytest.approx(230.363, rel=1e-3)


def test_trafo_rating_kw() -> None:
    net = _radial_fixture()
    ratings = trafo_rating_kw(net, pf=0.95)
    # kW = sn_mva * 1000 * pf = 0.21 * 1000 * 0.95 = 199.50 (real-net anchor).
    assert ratings[0] == pytest.approx(199.50, rel=1e-9)


# ─── TWIN-03: downstream map over transformer hops ──────────────────────


def test_downstream_map() -> None:
    net = _radial_fixture()
    dmap = build_downstream_map(net)

    # Keys follow the gridalyn/operations/constraints.py convention.
    assert "line:0" in dmap
    assert "line:1" in dmap
    assert "transformer:0" in dmap

    # line0 (1→2) far side is bus 2; line1 (1→3) far side is bus 3.
    assert dmap["line:0"] == frozenset({2})
    assert dmap["line:1"] == frozenset({3})

    # transformer 0 (0→1) descends to the whole LV subtree below it (hop).
    assert dmap["transformer:0"] == frozenset({1, 2, 3})

    # Every value is a frozenset (immutable, deterministic).
    assert all(isinstance(v, frozenset) for v in dmap.values())


# ─── TWIN-04: radiality + no-generation assertion ───────────────────────


def test_radiality_assert_pass() -> None:
    net = _radial_fixture()
    assert assert_radial_no_generation(net) is None


def test_radiality_assert_fail_loop() -> None:
    net = _radial_fixture()
    # Inject a cycle: add a line 2→3 closing the loop bus1-bus2-bus3.
    net.line = pd.concat(
        [
            net.line,
            pd.DataFrame(
                {"from_bus": [2], "to_bus": [3], "max_i_ka": [0.35]}, index=[2]
            ),
        ]
    )
    with pytest.raises(ValueError) as excinfo:
        assert_radial_no_generation(net)
    msg = str(excinfo.value)
    assert "radial" in msg.lower()
    # Located: names the project + the component/edge count.
    assert "ev_hosting_flex" in msg
    # Remediating hint.
    assert "remediation" in msg.lower() or "rebuild" in msg.lower()


def test_radiality_assert_fail_gen() -> None:
    net = _radial_fixture()
    net.sgen = pd.DataFrame({"bus": [2]}, index=[0])
    with pytest.raises(ValueError) as excinfo:
        assert_radial_no_generation(net)
    msg = str(excinfo.value)
    assert "generation" in msg.lower()
    assert "remediation" in msg.lower() or "exclude" in msg.lower()


# ─── D-02: deterministic feeder selection ───────────────────────────────


def test_select_feeder() -> None:
    net = _two_feeder_fixture()
    dmap = build_downstream_map(net)
    # trafo index 2 (lv_bus 3) carries 0.3 MW vs trafo 1's 0.1 MW → wins.
    assert select_feeder(net, dmap, None) == 2


def test_select_feeder_config_override() -> None:
    net = _two_feeder_fixture()
    dmap = build_downstream_map(net)
    # Explicit feeder_id override returns that index verbatim.
    assert select_feeder(net, dmap, {"feeder_id": 1}) == 1

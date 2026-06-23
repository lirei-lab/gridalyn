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
    annual_peak_base_factor,
    assert_radial_no_generation,
    build_downstream_map,
    line_rating_kw,
    select_feeder,
    size_feeder_transformer_kw,
    trafo_rating_kw,
)
from projects.ev_hosting_flex.scripts.config import (
    DAILY_PATTERN,
    WEEKLY_PATTERN,
    WINTER_PEAK_FACTOR,
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


# ─── 09-03: project-local feeder-transformer load-aware sizing ──────────
#
# GAP 1 (truth #8 / CONG-03): the selected feeder transformer must be sized to
# its annual winter-peak downstream base demand at the 0.8 utilization margin so
# that at 0 EVs the binding feeder element sits at or below ~80% loading.


def test_size_feeder_transformer_kw_hand_computed() -> None:
    """Hand-computed sizing arithmetic + the 0-EV <= 80% calibration target."""
    # (100 * 2.0) / 0.8 = 250.0 exactly (already integral; no round-up effect).
    assert (
        size_feeder_transformer_kw(100.0, peak_factor=2.0, utilization_margin=0.8)
        == 250.0
    )
    # For the real envelope multiplier and a 260 kW nameplate sum, the resized
    # rating divided into the annual winter-peak demand is <= the 80% margin.
    factor = annual_peak_base_factor()
    kw = size_feeder_transformer_kw(
        260.0, peak_factor=factor, utilization_margin=0.8
    )
    assert 260.0 * factor / kw * 100.0 <= 80.0 + 1e-9


def test_annual_peak_base_factor_matches_envelope() -> None:
    """The annual-peak multiplier reuses the unchanged envelope and is deterministic."""
    factor = annual_peak_base_factor()
    upper = WINTER_PEAK_FACTOR * max(DAILY_PATTERN) * max(WEEKLY_PATTERN) + 1e-9
    assert 1.0 < factor <= upper
    # Determinism: two calls return the identical float.
    assert annual_peak_base_factor() == factor


def test_size_feeder_transformer_kw_rejects_bad_input() -> None:
    """A non-positive nameplate and a margin > 1 each raise a remediating ValueError."""
    with pytest.raises(ValueError) as excinfo:
        size_feeder_transformer_kw(0.0, peak_factor=1.5, utilization_margin=0.8)
    assert "remediation" in str(excinfo.value).lower()

    with pytest.raises(ValueError) as excinfo:
        size_feeder_transformer_kw(100.0, peak_factor=1.5, utilization_margin=1.5)
    assert "remediation" in str(excinfo.value).lower()


def test_size_feeder_subtree_kw_resizes_every_element() -> None:
    """The whole feeder subtree (transformer + interior lines) is annual-peak sized.

    Hand-computed: head transformer covers buses {1,2}, an interior line covers
    {2}. With peak_factor=2.0 and margin=0.8, the transformer sizes to
    ceil((10+20)*2/0.8)=75 and the line to ceil(20*2/0.8)=50. Sizing the interior
    lines (not only the head transformer) is what makes the binding 0-EV element
    sit <= the margin (the GAP-1 root cause: an interior line binds first).
    """
    from projects.ev_hosting_flex.scripts._topology import size_feeder_subtree_kw

    element_keys = {
        "transformer:0": frozenset({1, 2}),
        "line:0": frozenset({2}),
    }
    nameplate = {1: 10.0, 2: 20.0}
    resized = size_feeder_subtree_kw(
        element_keys, nameplate, peak_factor=2.0, utilization_margin=0.8
    )
    assert resized == {"transformer:0": 75.0, "line:0": 50.0}


def test_firm_ev_count_positive_after_resize() -> None:
    """A subtree-resized feeder yields a positive, in-grid firm_ev_count.

    Synthetic fixture (cache-independent so it runs in CI without the gitignored
    runtime cache): a single feeder transformer + one interior line over 2 buses,
    each annual-peak sized to its downstream nameplate at margin 0.8 via
    ``size_feeder_subtree_kw``. With a small EV sweep the firm count lands strictly
    inside the grid with headroom below the first overload — proving the resize
    removes the 0-EV degeneracy (GAP 1 / CONG-03).
    """
    import numpy as np

    from projects.ev_hosting_flex.scripts._congestion import firm_ev_count
    from projects.ev_hosting_flex.scripts._topology import size_feeder_subtree_kw

    bus_ids = [1, 2]
    # Flat 1-hour profile: base nameplate per bus; one extra "EV unit" kW per EV.
    base_nameplate = {1: 100.0, 2: 100.0}  # kW per bus
    peak_factor = 1.5
    element_keys = {
        "transformer:0": frozenset({1, 2}),
        "line:0": frozenset({2}),
    }
    resized = size_feeder_subtree_kw(
        element_keys, base_nameplate, peak_factor=peak_factor, utilization_margin=0.8
    )
    elements = ["transformer:0", "line:0"]
    elem_kw = np.array([resized[e] for e in elements], dtype="float64")
    # indicator: transformer covers both buses, line covers bus 2 only.
    indicator = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
    # base demand at the annual peak (1 hour): nameplate * peak_factor.
    base = np.array(
        [[base_nameplate[b] * peak_factor] for b in bus_ids], dtype="float64"
    )
    ev_unit = np.array([[5.0], [5.0]], dtype="float64")  # 5 kW per EV on each bus

    def alloc_fn(total_ev: int) -> np.ndarray:
        # Split EVs evenly across the two buses (deterministic).
        per = np.zeros(len(bus_ids), dtype="float64")
        for i in range(total_ev):
            per[i % len(bus_ids)] += 1.0
        return per

    sweep = firm_ev_count(
        (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20),
        base,
        ev_unit,
        alloc_fn,
        indicator,
        elem_kw,
        100.0,
    )
    firm = int(sweep["firm_ev_count"])
    assert 0 < firm < 20, sweep
    assert (
        sweep["first_overload_ev_count"] is not None
        and sweep["first_overload_ev_count"] > firm
    ), sweep


# ─── 08.1-02: load-aware adoption regression ────────────────────────────
#
# ev_hosting_flex opts into ``lines.sizing.mode = "load_aware"`` via its OWN
# project-local config (``inputs/synthetic_network_config.json``), leaving the
# shared ``configs/grid/config.json`` byte-identical (LINESIZE-01/LINESIZE-03).
# These pin the adoption WITHOUT depending on the 787KB buildings.geojson or
# the gitignored runtime cache: they build a SMALL synthetic net through the
# public build hook with the ev_hosting_flex GRID_CONFIG.

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from gridalyn.foundation.platform.capabilities import (  # noqa: E402
    missing_capability_modules,
)

requires_sim = pytest.mark.skipif(
    bool(missing_capability_modules("sim")),
    reason="requires the 'sim' extra (pandapower)",
)


def test_ev_hosting_flex_config_opts_into_load_aware() -> None:
    """ev_hosting_flex GRID_CONFIG carries load_aware; shared config untouched."""
    from projects.ev_hosting_flex.scripts.config import GRID_CONFIG

    sizing = GRID_CONFIG["lines"].get("sizing")
    assert sizing is not None, "ev_hosting_flex GRID_CONFIG must declare lines.sizing"
    assert sizing["mode"] == "load_aware", sizing
    assert sizing.get("utilization_margin") == 0.8, sizing
    # The mirrored config keeps the downstream-required loads block.
    assert "n_buildings_cache" in GRID_CONFIG["loads"]

    # The shared config must NOT have been mutated into load_aware (LINESIZE-01).
    shared = json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))
    assert "sizing" not in shared.get("lines", {}), shared["lines"].get("sizing")


@requires_sim
def test_ev_hosting_flex_load_aware_net_radial_varied_convergent(
    tmp_path: Path,
) -> None:
    """A small ev_hosting_flex net stays radial+gen-free, varies conductors, PF converges."""
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )
    from gridalyn.twin.geoprocess import FakeGeoJSONGenerator
    from projects.ev_hosting_flex.scripts.config import GRID_CONFIG

    # Sanity: this test exercises the load-aware path the project opts into.
    assert GRID_CONFIG["lines"]["sizing"]["mode"] == "load_aware"

    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=4, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )

    build = build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=GRID_CONFIG,
        out_dir=tmp_path / "network",
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=False,
    )
    net = build.net

    # Gate: a single radial tree with no embedded generation (TWIN-04).
    assert assert_radial_no_generation(net) is None

    # Load-aware actually varied the conductors (no longer one value per level).
    assert net.line["max_i_ka"].nunique() > 1, net.line["max_i_ka"].unique()

    # The chosen conductors keep the AC power flow convergent.
    pp.runpp(net, algorithm="nr", max_iteration=100)
    assert net.converged is True

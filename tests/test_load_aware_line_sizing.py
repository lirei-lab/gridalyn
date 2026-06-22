"""Tests for opt-in load-aware AC line sizing.

Covers the selection primitive (`select_line_std_type`), the in-place sizing
post-pass (`size_lines_load_aware`), the byte-identity guarantee of the default
``uniform`` mode, the load-aware end-to-end behaviour, and facade reachability.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from gridalyn.foundation.platform.capabilities import missing_capability_modules

_SIM_MISSING = missing_capability_modules("sim")

requires_sim = pytest.mark.skipif(
    bool(_SIM_MISSING),
    reason="requires the 'sim' extra (pandapower)",
)

_SUMMARY_KEYS = {
    "idx",
    "level",
    "downstream_load_mw",
    "i_design_ka",
    "chosen_std_type",
    "max_i_ka",
    "over_capacity",
}

_LINE_TUPLE_COLS = (
    "std_type",
    "max_i_ka",
    "r_ohm_per_km",
    "x_ohm_per_km",
    "c_nf_per_km",
    "length_km",
    "name",
)


def _build_small_net(tmp_path: Path, config: dict[str, Any]) -> Any:
    """Build a small synthetic net from a config mapping (no cache, no PF)."""
    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )
    from gridalyn.twin.geoprocess import FakeGeoJSONGenerator

    tmp_path.mkdir(parents=True, exist_ok=True)
    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=3, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()),
        encoding="utf-8",
    )
    build = build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=config,
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=False,
    )
    return build.net


def _base_config() -> dict[str, Any]:
    """The shared sealed grid config (uniform / load-aware agnostic)."""
    return json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))


def _line_tuples(net: Any) -> list[tuple[Any, ...]]:
    """Return the per-line identity tuples used for byte-identity assertions."""
    tuples: list[tuple[Any, ...]] = []
    for _, row in net.line.iterrows():
        tuples.append(tuple(row[col] for col in _LINE_TUPLE_COLS))
    return tuples


# ---------------------------------------------------------------------------
# Task 1: selection primitive + sizing post-pass
# ---------------------------------------------------------------------------


@requires_sim
def test_select_line_std_type_first_above_margin() -> None:
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        select_line_std_type,
    )

    net = pp.create_empty_network()
    name, row, over = select_line_std_type(
        net, level="MV", i_design_ka=0.05, utilization_margin=0.8
    )
    threshold = 0.05 * 0.8
    assert row["max_i_ka"] >= threshold
    assert not over
    # FIRST above the threshold: nothing smaller in the catalog clears it.
    cat = pp.available_std_types(net, element="line")
    mv = cat[cat["voltage_rating"] == "MV"]
    smaller = mv[mv["max_i_ka"] < row["max_i_ka"]]
    assert (smaller["max_i_ka"] < threshold).all()


@requires_sim
def test_select_line_std_type_over_capacity_picks_largest() -> None:
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        select_line_std_type,
    )

    net = pp.create_empty_network()
    cat = pp.available_std_types(net, element="line")
    mv = cat[cat["voltage_rating"] == "MV"]
    largest = float(mv["max_i_ka"].max())
    name, row, over = select_line_std_type(
        net, level="MV", i_design_ka=largest * 10.0, utilization_margin=0.8
    )
    assert over
    assert float(row["max_i_ka"]) == largest


@requires_sim
def test_select_line_std_type_deterministic_and_monotonic() -> None:
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        select_line_std_type,
    )

    net = pp.create_empty_network()
    # Determinism: same inputs -> same name.
    a = select_line_std_type(net, level="LV", i_design_ka=0.1, utilization_margin=0.8)
    b = select_line_std_type(net, level="LV", i_design_ka=0.1, utilization_margin=0.8)
    assert a[0] == b[0]
    # Monotonic snap: larger I_design never selects a smaller rating.
    ratings = []
    for i_design in (0.05, 0.1, 0.2, 0.3):
        _, row, _ = select_line_std_type(
            net, level="MV", i_design_ka=i_design, utilization_margin=0.8
        )
        ratings.append(float(row["max_i_ka"]))
    assert ratings == sorted(ratings)


@requires_sim
def test_select_line_std_type_unknown_level_raises() -> None:
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        select_line_std_type,
    )

    net = pp.create_empty_network()
    with pytest.raises(ValueError, match="no .* line catalog entry"):
        select_line_std_type(net, level="ZZ", i_design_ka=0.05, utilization_margin=0.8)


@requires_sim
def test_size_lines_load_aware_varies_and_uses_catalog(tmp_path: Path) -> None:
    import pandapower as pp

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        size_lines_load_aware,
    )

    config = _base_config()
    net = _build_small_net(tmp_path, config)

    summary = size_lines_load_aware(net, config)

    # One row per on-tree line, with the documented schema.
    assert summary, "expected at least one sized line"
    for entry in summary:
        assert set(entry.keys()) == _SUMMARY_KEYS

    # max_i_ka now varies across the tree (no longer one value per level).
    assert net.line["max_i_ka"].nunique() > 1

    # Every written r/x/c/max_i_ka equals a real catalog row (no hand-invented).
    cat = pp.available_std_types(net, element="line")
    for _, row in net.line.iterrows():
        std = row["std_type"]
        if std not in cat.index:
            continue
        catalog_row = cat.loc[std]
        for col in ("max_i_ka", "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km"):
            assert float(row[col]) == pytest.approx(float(catalog_row[col]))


@requires_sim
def test_size_lines_load_aware_monotonic_within_level(tmp_path: Path) -> None:
    config = _base_config()
    net = _build_small_net(tmp_path, config)

    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        size_lines_load_aware,
    )

    summary = size_lines_load_aware(net, config)

    by_level: dict[str, list[dict[str, Any]]] = {}
    for entry in summary:
        by_level.setdefault(entry["level"], []).append(entry)

    for entries in by_level.values():
        ordered = sorted(entries, key=lambda e: e["i_design_ka"])
        ratings = [e["max_i_ka"] for e in ordered]
        # Snap is monotonic in I_design: more downstream load -> >= rating.
        assert ratings == sorted(ratings)


# ---------------------------------------------------------------------------
# Task 2: byte-identity (uniform == legacy), load-aware end-to-end, facade
# ---------------------------------------------------------------------------


@requires_sim
def test_uniform_is_byte_identical_to_legacy(tmp_path: Path) -> None:
    legacy_config = _base_config()  # no lines.sizing key at all

    uniform_config = _base_config()
    uniform_config["lines"]["sizing"] = {"mode": "uniform", "utilization_margin": 0.8}

    net_legacy = _build_small_net(tmp_path / "legacy", legacy_config)
    net_uniform = _build_small_net(tmp_path / "uniform", uniform_config)

    legacy_tuples = _line_tuples(net_legacy)
    uniform_tuples = _line_tuples(net_uniform)

    assert legacy_tuples == uniform_tuples
    # Sanity: uniform really is uniform (one rating per level, as today).
    assert net_legacy.line["max_i_ka"].nunique() <= len(set(net_legacy.bus["vn_kv"]))


@requires_sim
def test_load_aware_end_to_end(tmp_path: Path) -> None:
    import pandapower as pp

    from gridalyn.simulation import analyze_line_sizing

    config = _base_config()
    config["lines"]["sizing"] = {"mode": "load_aware", "utilization_margin": 0.8}

    net = _build_small_net(tmp_path, config)

    # Ratings vary now.
    assert net.line["max_i_ka"].nunique() > 1

    # Positive correlation between full (non-coincident) downstream load and
    # rating: lines are sized for the load the power flow actually injects.
    diag = analyze_line_sizing(net)
    loads = np.array([r["downstream_load_mw"] for r in diag.rows], dtype=float)
    ratings = np.array([r["max_i_ka"] for r in diag.rows], dtype=float)
    if np.std(loads) > 0 and np.std(ratings) > 0:
        corr = float(np.corrcoef(loads, ratings)[0, 1])
        assert corr > 0.0

    # Trunk (most downstream load) rating >= a leaf rating on the same level.
    by_level: dict[str, list[dict[str, Any]]] = {}
    for r in diag.rows:
        by_level.setdefault(r["level"], []).append(r)
    found_pair = False
    for rows in by_level.values():
        if len(rows) < 2:
            continue
        ordered = sorted(rows, key=lambda r: r["downstream_load_mw"])
        leaf, trunk = ordered[0], ordered[-1]
        assert trunk["max_i_ka"] >= leaf["max_i_ka"]
        found_pair = True
    assert found_pair, "expected at least one level with >=2 lines to compare"

    # A high-downstream-load trunk selects a STRICTLY larger conductor than a
    # single-building leaf line (the diversity divide is gone, so the spread in
    # injected load propagates into a spread in conductor rating). Compare the
    # globally-heaviest line against the lightest; with the full non-coincident
    # load basis these must differ in rating.
    all_rows = sorted(diag.rows, key=lambda r: r["downstream_load_mw"])
    lightest, heaviest = all_rows[0], all_rows[-1]
    assert heaviest["downstream_load_mw"] > lightest["downstream_load_mw"]
    assert heaviest["max_i_ka"] > lightest["max_i_ka"], (
        "heaviest trunk must pick a larger conductor than the lightest leaf "
        "under the full-load sizing basis"
    )

    # Power flow still converges.
    pp.runpp(net)
    assert bool(net.converged)


@requires_sim
def test_size_lines_load_aware_reachable_through_facade() -> None:
    from gridalyn.simulation import select_line_std_type, size_lines_load_aware

    assert callable(size_lines_load_aware)
    assert callable(select_line_std_type)

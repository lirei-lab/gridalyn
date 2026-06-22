"""Tests for the line-sizing ext_grid / disconnected guard and post-build guard.

``analyze_line_sizing`` must warn (not crash, not silently under-report) when the
network has zero or multiple ext_grid rows, or when the rooted BFS cannot reach
every bus. The opt-in ``check_line_sizing`` flag on
``build_synthetic_network_from_config`` must run the diagnostic read-only on a
copy, adding no new report bytes and changing nothing when left off.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from gridalyn.foundation.platform.capabilities import missing_capability_modules
from gridalyn.simulation.analytics.line_sizing import (
    LineSizingResult,
    analyze_line_sizing,
)

_SIM_MISSING = missing_capability_modules("sim")

requires_sim = pytest.mark.skipif(
    bool(_SIM_MISSING),
    reason="requires the 'sim' extra (pandapower)",
)


@dataclass
class _FakeNet:
    """Minimal duck-typed stand-in for a pandapower net (read-only fields)."""

    bus: pd.DataFrame
    load: pd.DataFrame
    line: pd.DataFrame
    trafo: pd.DataFrame
    ext_grid: pd.DataFrame
    res_line: pd.DataFrame | None = None
    converged: bool = False


def _well_formed_net(*, n_ext_grid: int = 1, connected: bool = True) -> _FakeNet:
    """Build a tiny radial fake net: buses 0-2 in a line, root at bus 0.

    Args:
        n_ext_grid: Number of ext_grid rows to attach (0, 1, or 2+).
        connected: When ``False``, add an extra bus 3 unreachable from the root.

    Returns:
        A :class:`_FakeNet` honouring the fields ``analyze_line_sizing`` reads.
    """
    bus_index = [0, 1, 2] + ([3] if not connected else [])
    bus = pd.DataFrame({"vn_kv": [0.4] * len(bus_index)}, index=bus_index)
    load = pd.DataFrame({"bus": [1, 2], "p_mw": [0.01, 0.02]})
    line = pd.DataFrame(
        {
            "from_bus": [0, 1],
            "to_bus": [1, 2],
            "max_i_ka": [0.2, 0.2],
            "length_km": [0.1, 0.1],
        }
    )
    trafo = pd.DataFrame(columns=["hv_bus", "lv_bus"])
    ext_grid = pd.DataFrame({"bus": [0, 0, 0][:n_ext_grid]})
    return _FakeNet(bus=bus, load=load, line=line, trafo=trafo, ext_grid=ext_grid)


def test_multi_ext_grid_warns() -> None:
    """Two ext_grid rows warn (naming the count) and still return a result."""
    net = _well_formed_net(n_ext_grid=2)
    with pytest.warns(UserWarning, match="2"):
        result = analyze_line_sizing(net)
    assert isinstance(result, LineSizingResult)


def test_zero_ext_grid_warns() -> None:
    """Zero ext_grid rows warn and do not raise (no IndexError on .iloc[0])."""
    net = _well_formed_net(n_ext_grid=0)
    with pytest.warns(UserWarning, match="0 ext_grid"):
        result = analyze_line_sizing(net)
    assert isinstance(result, LineSizingResult)


def test_disconnected_component_warns() -> None:
    """A bus unreachable from the root warns, naming the unreached count."""
    net = _well_formed_net(connected=False)
    with pytest.warns(UserWarning, match="1"):
        result = analyze_line_sizing(net)
    assert isinstance(result, LineSizingResult)


def test_well_formed_net_no_guard_warning() -> None:
    """A single-ext_grid, fully-connected net emits NO guard warning."""
    net = _well_formed_net()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        result = analyze_line_sizing(net)
    guard_warnings = [w for w in record if issubclass(w.category, UserWarning)]
    assert not guard_warnings
    assert isinstance(result, LineSizingResult)


def _build_args(tmp_path: Path) -> dict:
    """Common build kwargs reused by the post-build guard tests."""
    from gridalyn.twin.geoprocess import FakeGeoJSONGenerator

    footprints_path = tmp_path / "buildings.geojson"
    generator = FakeGeoJSONGenerator(grid_size=3, seed=11, rectangular=True)
    footprints_path.write_text(
        json.dumps(generator.generate_geojson()), encoding="utf-8"
    )
    config = json.loads(Path("configs/grid/config.json").read_text(encoding="utf-8"))
    return {
        "footprints_path": footprints_path,
        "config": config,
        "out_dir": tmp_path / "network",
        "clustering_crs": "auto",
        "write_cache": False,
        "run_powerflow": True,
    }


@requires_sim
def test_check_line_sizing_default_off_no_change(tmp_path: Path) -> None:
    """Default (flag off) produces the same report keys and no guard warning."""
    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )

    args = _build_args(tmp_path)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        build = build_synthetic_network_from_config(**args)
    guard = [w for w in record if "line_sizing" in str(w.message).lower()]
    assert not guard
    # No line-sizing key sneaks into the default report.
    assert "line_sizing" not in build.validation_report


@requires_sim
def test_check_line_sizing_on_runs_readonly(tmp_path: Path) -> None:
    """With check_line_sizing=True the build is valid and net.line is unchanged."""
    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )

    args = _build_args(tmp_path)
    build_off = build_synthetic_network_from_config(**dict(args))

    args_on = dict(_build_args(tmp_path))
    args_on["out_dir"] = tmp_path / "network_on"
    args_on["check_line_sizing"] = True
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        build_on = build_synthetic_network_from_config(**args_on)

    # Read-only: the net's lines are identical with the flag on.
    assert build_on.net.line["max_i_ka"].tolist() == build_off.net.line[
        "max_i_ka"
    ].tolist()
    # No new report bytes: the validation report keys are unchanged.
    assert set(build_on.validation_report.keys()) == set(
        build_off.validation_report.keys()
    )

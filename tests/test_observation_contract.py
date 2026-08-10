"""Gate the network observation contract.

Four behaviours are held here:

(a) an observation built from a solved IEEE-33 matches hand-computed
    min/max/loading values;
(b) both power-flow backends registered by the backend registry yield
    identical observations -- the seam proof;
(c) no in-scope file recomputes ``res_bus.vm_pu`` min/max directly any more;
(d) importing the package pulls no optional dependency.

Behaviour (c) is an :mod:`ast` scan, never a bare identifier grep. A grep for
``res_bus.vm_pu`` would match the prose in this docstring and in the contract's
own module docstring -- which explain *why* the direct extraction is gone --
and so would pass forever regardless of the code. That defect is Phase-9
retrospective item 3.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd
import pytest

from gridalyn.foundation.platform.capabilities import missing_capability_modules
from gridalyn.simulation.backends.contract import (
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
)
from gridalyn.simulation.backends.registry import solve_power_flow
from gridalyn.simulation.observation.contract import NetworkObservation, observe_network
from gridalyn.simulation.simulators.powerflow.benchmarks import (
    build_ieee33_benchmark_feeder,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Files migrated onto the contract by plan 10-03. Each must reach bus voltage
#: and line results through the contract, not by re-deriving them.
MIGRATED_FILES = (
    "gridalyn/operations/der_voltage.py",
    "gridalyn/operations/prosumer_realtime.py",
    "gridalyn/simulation/simulators/powerflow/scenarios.py",
    "gridalyn/simulation/simulators/powerflow/artifacts.py",
    "gridalyn/simulation/simulators/powerflow/runner.py",
)

#: Result-table attributes whose direct reduction the contract replaces.
_RESULT_TABLES = ("res_bus", "res_line")

#: Reductions that constitute "recomputing a summary statistic".
_REDUCTIONS = ("min", "max", "sum", "mean")


def _solved_ieee33(backend_id: str = PANDAPOWER_NATIVE_BACKEND_ID) -> pp.pandapowerNet:
    """Return an IEEE-33 feeder solved through a named backend.

    Args:
        backend_id: Registered power-flow backend to solve with.

    Returns:
        The solved network, mutated in place with ``res_*`` tables.
    """
    net = build_ieee33_benchmark_feeder()
    solve_power_flow(net, backend_id=backend_id)
    return net


# --------------------------------------------------------------------------
# (a) the observation matches hand-computed values
# --------------------------------------------------------------------------


def test_observation_matches_hand_computed_ieee33_values() -> None:
    """The contract reproduces the reductions the migrated sites performed."""
    net = _solved_ieee33()
    observation = observe_network(net)

    assert observation.converged is True
    assert observation.min_voltage_pu == float(net.res_bus.vm_pu.min())
    assert observation.max_voltage_pu == float(net.res_bus.vm_pu.max())
    assert observation.max_line_loading_percent == float(
        net.res_line.loading_percent.max()
    )
    assert observation.total_line_loss_mw == float(net.res_line.pl_mw.sum())
    np.testing.assert_array_equal(
        observation.bus_voltage_pu, net.res_bus.vm_pu.to_numpy(dtype=float)
    )
    assert len(observation.bus_voltage_pu) == 33
    assert observation.voltage_violation_counts(below_pu=0.95, above_pu=1.05) == (
        int((net.res_bus.vm_pu < 0.95).sum()),
        int((net.res_bus.vm_pu > 1.05).sum()),
    )


def test_voltage_frame_reproduces_the_two_column_table() -> None:
    """``voltage_frame`` equals the ``reset_index``/rename dance it replaces."""
    net = _solved_ieee33()
    expected = net.res_bus.vm_pu.reset_index()
    expected.columns = ["bus_id", "vm_pu"]

    pd.testing.assert_frame_equal(
        observe_network(net).voltage_frame(),
        expected,
        check_exact=True,
        check_dtype=True,
    )


def test_voltage_frame_carries_result_ids_not_positions() -> None:
    """``bus_id`` comes from the result index, not from the row position.

    Every network in this suite happens to have a contiguous ``0..n-1``
    result index, which makes an index/position confusion invisible. This
    case drops a row so the two differ.
    """
    net = _solved_ieee33()
    net.res_bus = net.res_bus.drop(index=net.res_bus.index[1])
    frame = observe_network(net).voltage_frame()

    assert frame["bus_id"].tolist() == [0] + list(range(2, 33))
    assert frame["bus_id"].tolist() != list(range(len(frame)))


def test_violation_counts_exclude_buses_exactly_at_the_limits() -> None:
    """A bus sitting exactly on a limit is not a violation.

    Pinned explicitly because the reductions are strict comparisons and no
    solved network in this suite lands a bus on the limit to the bit.
    """
    exactly_at_limits = NetworkObservation(
        converged=True,
        bus_ids=np.array([0, 1, 2, 3]),
        bus_voltage_pu=np.array([0.95, 1.05, 0.9499999, 1.0500001]),
        line_loading_percent=np.array([]),
        total_line_loss_mw=0.0,
    )

    assert exactly_at_limits.voltage_violation_counts(below_pu=0.95, above_pu=1.05) == (
        1,
        1,
    )


def test_reductions_skip_missing_entries_like_pandas() -> None:
    """A ``NaN`` entry is skipped by a reduction and counts as no violation."""
    net = _solved_ieee33()
    net.res_bus.loc[net.res_bus.index[:3], "vm_pu"] = np.nan
    observation = observe_network(net)

    assert observation.min_voltage_pu == float(net.res_bus.vm_pu.min())
    assert observation.max_voltage_pu == float(net.res_bus.vm_pu.max())
    assert observation.voltage_violation_counts(below_pu=0.95, above_pu=1.05) == (
        int((net.res_bus.vm_pu < 0.95).sum()),
        int((net.res_bus.vm_pu > 1.05).sum()),
    )


def test_drop_missing_preserves_the_full_versus_filtered_distinction() -> None:
    """Extremes agree across the filter; any count over the length does not.

    This is the distinction the tree already made silently -- the Monte-Carlo
    diagnostic reduced over a ``dropna()``-filtered array while the scenario
    runner reduced over the full one. Collapsing them would change a reported
    percentage, so the contract keeps both reachable and named.
    """
    net = _solved_ieee33()
    net.res_bus.loc[net.res_bus.index[:3], "vm_pu"] = np.nan
    full = observe_network(net)
    filtered = full.drop_missing()

    assert len(full.bus_voltage_pu) == 33
    assert len(filtered.bus_voltage_pu) == 30
    assert filtered.min_voltage_pu == full.min_voltage_pu
    assert filtered.max_voltage_pu == full.max_voltage_pu
    assert not np.isnan(filtered.bus_voltage_pu).any()
    np.testing.assert_array_equal(filtered.bus_ids, np.asarray(net.res_bus.index)[3:])


def test_unreported_loss_is_none_and_reported_empty_loss_is_zero() -> None:
    """``None`` and ``0.0`` are different answers, and both are preserved."""
    empty = pp.create_empty_network(sn_mva=1.0)
    pp.create_bus(empty, vn_kv=12.47)

    assert observe_network(empty).total_line_loss_mw == 0.0
    assert np.isnan(observe_network(empty).min_voltage_pu)

    class _NoResults:
        """A producer that reports no result tables at all."""

    unreported = observe_network(_NoResults())
    assert unreported.total_line_loss_mw is None
    assert unreported.converged is False
    assert len(unreported.bus_voltage_pu) == 0


# --------------------------------------------------------------------------
# (b) the seam: both backends, and a producer that is not a network at all
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    bool(missing_capability_modules("sim")),
    reason="the lightsim2grid backend needs the 'sim' extra",
)
def test_both_registered_backends_yield_identical_observations() -> None:
    """Observing through either backend gives the same observation."""
    native = observe_network(_solved_ieee33(PANDAPOWER_NATIVE_BACKEND_ID))
    lightsim = observe_network(_solved_ieee33(LIGHTSIM2GRID_BACKEND_ID))

    assert native.converged == lightsim.converged
    assert native.total_line_loss_mw == lightsim.total_line_loss_mw
    assert native.min_voltage_pu == lightsim.min_voltage_pu
    assert native.max_voltage_pu == lightsim.max_voltage_pu
    assert native.max_line_loading_percent == lightsim.max_line_loading_percent
    np.testing.assert_array_equal(native.bus_ids, lightsim.bus_ids)
    np.testing.assert_array_equal(native.bus_voltage_pu, lightsim.bus_voltage_pu)
    np.testing.assert_array_equal(
        native.line_loading_percent, lightsim.line_loading_percent
    )


def test_the_contract_does_not_require_a_pandapower_network() -> None:
    """A producer that is not a network can satisfy the contract.

    This is what makes the observation a seam: a surrogate that never solves
    an AC power flow constructs the dataclass directly, and every accessor
    the migrated sites use works on it.
    """
    surrogate = NetworkObservation(
        converged=True,
        bus_ids=np.array([0, 1, 2]),
        bus_voltage_pu=np.array([1.0, 0.94, 1.06]),
        line_loading_percent=np.array([10.0, 120.0]),
        total_line_loss_mw=0.25,
    )

    assert surrogate.min_voltage_pu == 0.94
    assert surrogate.max_voltage_pu == 1.06
    assert surrogate.max_line_loading_percent == 120.0
    assert surrogate.voltage_violation_counts(below_pu=0.95, above_pu=1.05) == (1, 1)
    assert list(surrogate.voltage_frame().columns) == ["bus_id", "vm_pu"]

    annotations = {
        name: str(value) for name, value in NetworkObservation.__annotations__.items()
    }
    assert not any("pandapower" in value.lower() for value in annotations.values())


# --------------------------------------------------------------------------
# (c) no in-scope file recomputes the summary statistics directly
# --------------------------------------------------------------------------


def _direct_result_reductions(source: str) -> list[str]:
    """Return every direct reduction of a result table found in ``source``.

    Walks the parsed module rather than matching text, so neither this file's
    docstring nor an explanatory comment in the scanned file can satisfy the
    check.

    Args:
        source: Python source of a module to scan.

    Returns:
        Dotted descriptions such as ``res_bus.vm_pu.min`` for every call of a
        reduction on an attribute chain rooted at a result table.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute) or callee.attr not in _REDUCTIONS:
            continue
        parts: list[str] = []
        cursor: ast.expr = callee.value
        while True:
            # Descend through calls and subscripts as well as attributes, so
            # that an intermediate step such as ``.dropna()`` or ``.loc[...]``
            # cannot hide the result table the reduction is rooted at.
            if isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            elif isinstance(cursor, ast.Call):
                cursor = cursor.func
            elif isinstance(cursor, ast.Subscript):
                cursor = cursor.value
            else:
                break
        if any(part in _RESULT_TABLES for part in parts):
            found.append(".".join(reversed(parts)) + f".{callee.attr}")
    return found


@pytest.mark.parametrize("relative_path", MIGRATED_FILES)
def test_migrated_files_do_not_reduce_result_tables_directly(
    relative_path: str,
) -> None:
    """Every migrated file observes through the contract, not the tables."""
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    assert _direct_result_reductions(source) == []


def test_the_ast_scan_would_catch_a_reintroduced_reduction() -> None:
    """The scan is not vacuous: it finds the pattern it exists to forbid."""
    assert _direct_result_reductions("value = net.res_bus.vm_pu.min()") == [
        "res_bus.vm_pu.min"
    ]
    assert _direct_result_reductions("total = self.pp_net.res_line.pl_mw.sum()") == [
        "pp_net.res_line.pl_mw.sum"
    ]
    # An intermediate call or subscript must not hide the result table.
    assert _direct_result_reductions("v = net.res_bus.vm_pu.dropna().min()") == [
        "res_bus.vm_pu.dropna.min"
    ]
    assert _direct_result_reductions('v = net.res_bus["vm_pu"].max()') == [
        "res_bus.max"
    ]
    # A time-series output keyed by a result-table *string* is a different
    # quantity (timesteps x buses) and is deliberately not matched.
    assert (
        _direct_result_reductions('m = ow.output["res_line.loading_percent"].max()')
        == []
    )
    # A comment naming the pattern must not satisfy the check.
    assert _direct_result_reductions("# net.res_bus.vm_pu.min() was removed") == []


def test_replay_is_not_an_observation_consumer() -> None:
    """``operations/replay.py`` reads nothing from a solved network.

    It is forecast-driven, so pulling it onto this contract would be inventing
    a consumer -- the promotion rule that justifies the boundary requires the
    consumers to be measured.
    """
    source = (REPO_ROOT / "gridalyn/operations/replay.py").read_text(encoding="utf-8")
    names = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
    }

    assert not names & {"res_bus", "res_line", "vm_pu", "loading_percent"}
    assert _direct_result_reductions(source) == []


# --------------------------------------------------------------------------
# (d) importing the package pulls no optional dependency
# --------------------------------------------------------------------------


def test_importing_the_package_pulls_no_optional_dependency() -> None:
    """A clean-process import of the package leaks no optional module."""
    probe = (
        "import json, sys;"
        "import gridalyn.simulation.observation;"
        "print(json.dumps(sorted("
        "{'lightsim2grid', 'cvxpy', 'osmnx'} & set(sys.modules))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []

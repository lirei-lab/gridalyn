"""Gate the network observation contract.

Four behaviours are held here:

(a) an observation built from a solved IEEE-33 matches hand-computed
    min/max/loading values;
(b) both power-flow backends registered by the backend registry yield
    identical observations -- the seam proof;
(c) no in-scope file recomputes ``res_bus.vm_pu`` min/max directly any more;
(d) ``as_of`` is carried, and its absence is explicit rather than fabricated.

``gridalyn.simulation.observation``, the deprecation shim Phase 11 left behind
when the contract moved to ``gridalyn.twin.observation``, was deleted
2026-08-19 (Phase 26) -- it had no in-repo consumer, and the deprecation had
no pinned removal version. ``gridalyn.twin.observation``'s own
no-optional-dependency behaviour is covered generically by
``tests/test_import_hygiene.py``'s whole-tree sweep, not by a dedicated test
here.

Behaviour (c) is an :mod:`ast` scan, never a bare identifier grep. A grep for
``res_bus.vm_pu`` would match the prose in this docstring and in the contract's
own module docstring -- which explain *why* the direct extraction is gone --
and so would pass forever regardless of the code. That defect is Phase-9
retrospective item 3.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
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
from gridalyn.simulation.simulators.powerflow.benchmarks import (
    build_ieee33_benchmark_feeder,
)
from gridalyn.twin.observation.contract import (
    AS_OF_ABSENT_REASON,
    NetworkObservation,
    observe_network,
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
        provenance="simulated",
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
        provenance="simulated",
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
# (d) the clock: carried when supplied, explicitly absent when not
# --------------------------------------------------------------------------


def test_observing_without_an_instant_leaves_as_of_absent() -> None:
    """A solved network carries no clock, so nothing is invented for it.

    The failure this forbids is a default of ``datetime.now()``: it would make
    every observation look timestamped, and a fabricated instant reads as
    evidence. ``None`` is the honest answer and the reason travels with it.
    """
    before = datetime.now(timezone.utc)
    observation = observe_network(_solved_ieee33())

    assert observation.as_of is None
    assert "fabricate" in AS_OF_ABSENT_REASON
    # Not merely "not now": no field acquired a wall-clock value at all.
    assert not [
        name
        for name, value in vars(observation).items()
        if isinstance(value, datetime) and value >= before
    ]


def test_a_supplied_instant_is_carried_through_unchanged() -> None:
    """``as_of`` is caller-supplied, keyword-only, and stored verbatim."""
    instant = datetime(2018, 1, 15, 17, 45, tzinfo=timezone.utc)
    observation = observe_network(_solved_ieee33(), as_of=instant)

    assert observation.as_of == instant
    assert observation.as_of.tzinfo is timezone.utc

    with pytest.raises(TypeError):
        observe_network(_solved_ieee33(), instant)  # type: ignore[misc]


def test_filtering_unobserved_buses_does_not_move_the_instant() -> None:
    """``drop_missing`` narrows the arrays; it does not re-time the state."""
    instant = datetime(2018, 1, 15, 17, 45, tzinfo=timezone.utc)
    net = _solved_ieee33()
    net.res_bus.loc[net.res_bus.index[:3], "vm_pu"] = np.nan

    timed = observe_network(net, as_of=instant)
    untimed = observe_network(net)

    assert timed.drop_missing().as_of == instant
    assert untimed.drop_missing().as_of is None


def _observe_calls(source: str) -> list[tuple[int, bool]]:
    """Return every ``observe_network`` call in ``source`` and whether it times.

    Walks the parsed module rather than matching text, for the Phase-9
    retrospective reason: ``as_of`` appears in prose throughout this file, the
    contract and several call-site comments, so a grep answers a different
    question than the one asked.

    A ``**kwargs`` unpacking counts as timing the call. What it forwards is not
    knowable statically, so treating it as absent would let a timed call site
    appear without the gate below noticing -- which is the single thing it
    exists to catch.

    Args:
        source: Python source of a module to scan.

    Returns:
        One ``(lineno, passes_as_of)`` pair per call, in source order.
    """
    calls: list[tuple[int, bool]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.attr
            if isinstance(callee, ast.Attribute)
            else callee.id if isinstance(callee, ast.Name) else None
        )
        if name != "observe_network":
            continue
        timed = any(
            keyword.arg == "as_of" or keyword.arg is None for keyword in node.keywords
        )
        calls.append((node.lineno, timed))
    return sorted(calls)


#: Production ``observe_network`` call sites measured across ``gridalyn/`` on
#: 2026-08-12 (7 importer modules). Held as a **floor**, not an equality: it
#: guards the gate below against passing because the scan found nothing, while
#: leaving a legitimately-added call site free to raise it.
MEASURED_PRODUCTION_OBSERVE_CALLS = 13


def test_the_simulated_path_still_supplies_no_instant() -> None:
    """The positive contract: ``observe_network`` call sites pass no ``as_of``.

    A solved network carries no clock -- one converged operating point with no
    record of which instant it represents -- so every production
    ``observe_network`` call site passes no instant, and ``None`` there is a
    fact about the producer, not a gap (:data:`AS_OF_ABSENT_REASON`). The
    measured path, which does not call ``observe_network`` at all, always
    stamps one from the datum -- pinned by ``tests/test_measured_ingest.py``.

    This replaces Phase 11's deferral marker
    ``test_no_production_call_site_supplies_an_instant``, retired deliberately
    by plan 12-04. That marker said "Going red is the correct outcome the day
    a producer with a real instant appears" -- the day arrived in Phase 12,
    via a producer that constructs observations *directly*
    (``read_measured_observations`` never calls ``observe_network``), so the
    scan stayed green and the marker's assertion became this positive
    contract rather than a red gate.

    The marker's own retirement condition is adjudicated here, not skipped.
    It named one real instant deliberately not plumbed --
    ``coincident_peak_loads_mw`` (``gridalyn/assets/datagen/api.py``) computes
    a tz-aware ``idxmax()`` ``Timestamp`` and discards it -- and said
    "Carrying it to a call site is Phase-12 scope". Phase 12 deliberately did
    NOT plumb it: the 2026-08-13 user decision (STATE.md / MILESTONE-6)
    REJECTED populating ``as_of`` from the synthetic generator, because it
    would close R20 criterion 4 mechanically while leaving both producers
    simulated. The deferral ended through the measured ingest instead, so the
    synthetic instant stays discarded and the simulated path stays untimed.
    """
    timed: dict[str, list[int]] = {}
    total = 0
    for path in sorted((REPO_ROOT / "gridalyn").rglob("*.py")):
        calls = _observe_calls(path.read_text(encoding="utf-8"))
        total += len(calls)
        lines = [lineno for lineno, passes in calls if passes]
        if lines:
            timed[str(path.relative_to(REPO_ROOT))] = lines

    assert total >= MEASURED_PRODUCTION_OBSERVE_CALLS, (
        f"found {total} production observe_network call site(s), fewer than the "
        f"{MEASURED_PRODUCTION_OBSERVE_CALLS} measured on 2026-08-12; the scan "
        "may be looking for a name that no longer exists"
    )
    assert not timed, (
        f"{sum(len(v) for v in timed.values())} production observe_network "
        f"call site(s) supply as_of: {timed}. A solved network carries no "
        "clock, so a simulated call site with an instant must show where the "
        f"instant is real -- read AS_OF_ABSENT_REASON first: {AS_OF_ABSENT_REASON}"
    )


def test_the_as_of_scan_would_catch_a_supplied_instant() -> None:
    """The scan is not vacuous, proven against real code rather than a fixture.

    This test module genuinely calls ``observe_network`` both ways, so scanning
    it exercises both branches on code that is compiled and executed -- a
    synthetic string could drift from what the scanner meets in practice.
    """
    own_source = Path(__file__).read_text(encoding="utf-8")
    calls = _observe_calls(own_source)

    timed = [passes for _lineno, passes in calls]
    # Measured 2026-08-12: 2 calls here pass ``as_of=``, 13 do not.
    assert timed.count(True) >= 2, "the scan no longer sees a timed call"
    assert timed.count(False) >= 2, "the scan no longer sees an untimed call"
    # A ``**kwargs`` forward is treated as timing the call, not as absent.
    assert _observe_calls("observe_network(net, **options)") == [(1, True)]
    # Prose naming the keyword is not a call.
    assert _observe_calls("# observe_network(net, as_of=instant) is forbidden") == []


# --------------------------------------------------------------------------
# (e) provenance: required, stamped by the producer, carried by the filter
# --------------------------------------------------------------------------
# Red-first note: the required field makes red-first structural -- these tests
# cannot even construct their subjects on the pre-provenance tree, where the
# field does not exist, so they fail there by construction.


def test_provenance_is_required() -> None:
    """Constructing without provenance is a ``TypeError``, not a default.

    A default would silently mislabel every external direct construction, so
    the field is required deliberately: no producer can omit the answer.
    """
    with pytest.raises(TypeError):
        NetworkObservation(  # type: ignore[call-arg]
            converged=True,
            bus_ids=np.empty(0, dtype=int),
            bus_voltage_pu=np.empty(0, dtype=float),
            line_loading_percent=np.empty(0, dtype=float),
            total_line_loss_mw=None,
        )


def test_observe_network_stamps_simulated() -> None:
    """``observe_network`` reads solver results, so it always stamps simulated."""
    assert observe_network(_solved_ieee33()).provenance == "simulated"


def test_drop_missing_carries_provenance() -> None:
    """``drop_missing`` narrows the arrays; it does not re-source the state.

    Built with ``provenance="measured"`` deliberately: this also proves the
    type admits the measured literal before its producer ships.
    """
    measured = NetworkObservation(
        converged=True,
        bus_ids=np.array([0, 1, 2]),
        bus_voltage_pu=np.array([1.0, np.nan, 0.97]),
        line_loading_percent=np.empty(0, dtype=float),
        total_line_loss_mw=None,
        provenance="measured",
    )

    assert measured.drop_missing().provenance == "measured"


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


# ``test_replay_is_not_an_observation_consumer`` was removed 2026-08-15 with the
# module it guarded. It asserted that ``operations/replay.py`` read nothing from
# a solved network -- evidence that this contract had not invented a consumer.
# Deleting the module answers the question it was asking.

# ``test_importing_the_package_pulls_no_optional_dependency`` (behaviour (d) in
# the original numbering) was removed 2026-08-19 with the
# ``gridalyn.simulation.observation`` deprecation shim it probed -- see the
# module docstring.

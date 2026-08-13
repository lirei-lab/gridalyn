"""Contract for what a controller can see from a solved network.

Before this module, "the state of a solved feeder" had no single definition.
Five files independently re-derived it from ``res_bus`` / ``res_line``, and a
sixth (``simulation/environments/voltage_control.py``) reached the same
quantity through a different access path entirely. Nothing forced them to
agree, and two of them already did not: ``powerflow/runner.py`` reduced over a
``dropna()``-filtered array while ``powerflow/scenarios.py`` reduced over the
full one, so "how many buses are under-voltage" meant two different things
depending on which file you read.

A :class:`NetworkObservation` is that definition. It is deliberately *not* a
pandapower object: it holds already-extracted arrays, so a different power-flow
backend -- or a surrogate that never solves an AC power flow at all -- can
construct one directly and be observed through the same contract. The
pandapower-shaped adapter is :func:`observe_network`, which is one function,
not the type signature.

Every field below is here because a measured site needs it. The
``>=2-consumer`` promotion rule in ``docs/platform/platform-layer-model.md``
is applied per *field*, not per package:

===========================  =====================================================
Field / accessor             Motivating sites
===========================  =====================================================
``bus_voltage_pu``           ``operations/der_voltage.py`` ``_base_voltage``,
                             ``_voltage_sensitivity`` and both verification nets;
                             ``powerflow/runner.py`` ``_verify_grid_stats``
``bus_ids``                  ``powerflow/scenarios.py`` and
                             ``powerflow/artifacts.py`` both rebuild the same
                             ``["bus_id", "vm_pu"]`` frame from the result index
``line_loading_percent``     ``powerflow/scenarios.py``,
                             ``operations/prosumer_realtime.py``,
                             ``powerflow/artifacts.py`` (max);
                             ``powerflow/runner.py`` (mean and overload count)
``total_line_loss_mw``       ``powerflow/scenarios.py``,
                             ``operations/prosumer_realtime.py``,
                             ``powerflow/artifacts.py``
``converged``                ``powerflow/scenarios.py``,
                             ``operations/prosumer_realtime.py``,
                             ``powerflow/artifacts.py``
``min_voltage_pu`` /         ``powerflow/scenarios.py``,
``max_voltage_pu``           ``operations/prosumer_realtime.py``,
                             ``powerflow/artifacts.py``,
                             ``powerflow/runner.py``,
                             ``operations/der_voltage.py`` (summary)
``max_line_loading_percent`` ``powerflow/scenarios.py``,
                             ``operations/prosumer_realtime.py``,
                             ``powerflow/artifacts.py``
``voltage_violation_counts`` ``powerflow/scenarios.py`` (summed to one count),
                             ``powerflow/runner.py`` (each as a percentage)
``drop_missing``             ``powerflow/runner.py`` -- the explicit form of the
                             ``dropna()`` its counts have always been taken over
``voltage_frame``            ``powerflow/scenarios.py``,
                             ``powerflow/artifacts.py``
===========================  =====================================================

Quantities with a *single* measured consumer are deliberately absent: per-line
loss vectors, mean line loading, overloaded-line counts and every transformer
result. ``powerflow/runner.py`` computes those from
:attr:`NetworkObservation.line_loading_percent` at its own call site rather
than growing this contract on one consumer.

``operations/replay.py`` is *not* a consumer: it reads nothing from a solved
network (measured: zero ``res_bus`` / ``res_line`` / ``vm_pu`` matches) and is
forecast-driven.

Reduction semantics match pandas, because that is what the migrated sites had:
every reduction skips ``NaN``, an empty reduction is ``nan`` for min/max and
``0.0`` for a sum, and ``NaN`` never counts as a voltage violation.

**Where this lives.** Phase 10 created the contract under
``gridalyn.simulation.observation`` because that is where the need surfaced.
"What a solved network shows" is a property of the network, not of the solver,
so Phase 11 moved it down to ``gridalyn.twin.observation`` -- the layer that
owns network state. ``gridalyn.simulation.observation`` remains as a
re-exporting shim that emits :class:`DeprecationWarning` and yields *this*
module's objects, not copies of them.

**The clock.** :attr:`NetworkObservation.as_of` is the instant the observed
state belongs to. It is supplied by the caller and defaults to ``None``,
because the only producer that ships today reads a solved ``pandapowerNet``,
and that object carries no clock: it holds one converged operating point with
no record of which instant it represents. Inferring a timestamp -- from the
wall clock, or from the model's ``created`` -- would manufacture evidence, the
same failure mode ``ModelIdentity.scenario_time`` avoids by staying ``None``.
See :data:`AS_OF_ABSENT_REASON`.

**The provenance.** :attr:`NetworkObservation.provenance` is where the values
came from -- :data:`ObservationProvenance`, ``"simulated"`` or ``"measured"``.
It is a required field with no default, so a consumer holding only the object
can always tell a simulation result from a measurement, and no producer can
leave the question unanswered. :func:`observe_network` reads solver results and
therefore always stamps ``"simulated"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

#: Why an observation may carry no :attr:`NetworkObservation.as_of`. Held as a
#: constant so the reason travels with the value rather than living only in a
#: docstring, matching :data:`gridalyn.twin.network.model.
#: SCENARIO_TIME_ABSENT_REASON`.
AS_OF_ABSENT_REASON = (
    "the producer reported no observation instant; a solved network holds one "
    "operating point with no record of which instant it represents, and "
    "substituting the wall clock or the model's creation time would fabricate "
    "a timestamp that reads as evidence -- pass as_of= when a real instant is "
    "known"
)

#: Result-table column holding per-bus voltage magnitude in per-unit.
BUS_VOLTAGE_COLUMN = "vm_pu"

#: Result-table column holding per-line loading as a percentage of rating.
LINE_LOADING_COLUMN = "loading_percent"

#: Result-table column holding per-line active power loss in MW.
LINE_LOSS_COLUMN = "pl_mw"

#: Where an observation's values came from. ``"simulated"`` means the state was
#: read off a solver result -- a solved pandapower network, or a surrogate that
#: stands in for one. ``"measured"`` means the state was ingested from an
#: observed system's export, with :attr:`NetworkObservation.as_of` stamped from
#: the datum itself rather than supplied by the caller.
ObservationProvenance = Literal["simulated", "measured"]


def _float_column(table: Any, column: str) -> np.ndarray | None:
    """Return ``column`` of ``table`` as a float array, or ``None`` if absent.

    Args:
        table: Candidate result table. Anything that is not a
            :class:`pandas.DataFrame` is treated as "not reported".
        column: Column name to extract.

    Returns:
        A float64 view of the column, or ``None`` when the table or the column
        is not present. ``None`` means *not reported*; an empty array means
        *reported and empty*, and the two differ for a sum.
    """
    if not isinstance(table, pd.DataFrame) or column not in table:
        return None
    return np.asarray(table[column], dtype=float)


def _present(values: np.ndarray) -> np.ndarray:
    """Return ``values`` without its ``NaN`` entries.

    Args:
        values: Float array, possibly containing ``NaN``.

    Returns:
        A new array holding only the non-``NaN`` entries, matching what
        :meth:`pandas.Series.dropna` selects.
    """
    return values[~np.isnan(values)]


def _skipna_extreme(values: np.ndarray, *, largest: bool) -> float:
    """Reduce ``values`` to its min or max the way pandas would.

    Args:
        values: Float array to reduce.
        largest: ``True`` for the maximum, ``False`` for the minimum.

    Returns:
        The extreme of the non-``NaN`` entries, or ``nan`` when there are
        none -- matching ``Series.min()`` / ``Series.max()``, which skip
        ``NaN`` and return ``nan`` for an empty selection rather than raising
        as ``numpy.nanmax`` does.
    """
    present = _present(values)
    if present.size == 0:
        return float("nan")
    return float(present.max() if largest else present.min())


@dataclass(frozen=True, eq=False)
class NetworkObservation:
    """What a controller can see from one solved network state.

    Constructed either from a solved network via :func:`observe_network` or
    directly from arrays by any producer of solved results -- a different
    power-flow backend, or a surrogate. No field is a pandapower type, which
    is what makes this a seam rather than a helper.

    Comparison is by identity (``eq=False``): the generated ``__eq__`` would
    compare array fields element-wise and then raise ``ValueError`` on the
    ambiguous truth value. Compare fields explicitly instead.

    The arrays alias the result tables they were read from, exactly as the
    ``to_numpy(dtype=float)`` calls they replace did. Treat them as read-only.

    Attributes:
        converged: Whether the producer reported a converged solution.
        bus_ids: Identifier per entry of ``bus_voltage_pu``, in the same order.
        bus_voltage_pu: Per-bus voltage magnitude in per-unit. Empty when the
            producer reported no bus voltages.
        line_loading_percent: Per-line loading as a percentage of rating.
            Empty when the producer reported no line loadings.
        total_line_loss_mw: Total active line loss in MW, or ``None`` when the
            producer reported no loss at all. ``None`` and ``0.0`` are
            different answers and callers that distinguish them rely on it.
        provenance: Where the values came from -- ``"simulated"`` or
            ``"measured"``. This is what lets a consumer holding only the
            object distinguish a simulation result from a measurement.
            Required deliberately, with no default, so that no producer can
            omit the answer.
        as_of: The instant this state belongs to, supplied by whoever knows it.
            ``None`` means *no instant was reported* -- see
            :data:`AS_OF_ABSENT_REASON`. It is never filled in from the wall
            clock, so ``None`` here is a fact about the producer rather than a
            gap in the reader's knowledge.
    """

    converged: bool
    bus_ids: np.ndarray
    bus_voltage_pu: np.ndarray
    line_loading_percent: np.ndarray
    total_line_loss_mw: float | None
    provenance: ObservationProvenance
    as_of: datetime | None = None

    @property
    def min_voltage_pu(self) -> float:
        """Return the lowest bus voltage magnitude in per-unit.

        Returns:
            float: The minimum over non-``NaN`` entries, or ``nan`` when no
                bus voltage was observed.
        """
        return _skipna_extreme(self.bus_voltage_pu, largest=False)

    @property
    def max_voltage_pu(self) -> float:
        """Return the highest bus voltage magnitude in per-unit.

        Returns:
            float: The maximum over non-``NaN`` entries, or ``nan`` when no
                bus voltage was observed.
        """
        return _skipna_extreme(self.bus_voltage_pu, largest=True)

    @property
    def max_line_loading_percent(self) -> float:
        """Return the highest line loading as a percentage of rating.

        Returns:
            float: The maximum over non-``NaN`` entries, or ``nan`` when no
                line loading was observed.
        """
        return _skipna_extreme(self.line_loading_percent, largest=True)

    def voltage_violation_counts(
        self,
        *,
        below_pu: float,
        above_pu: float,
    ) -> tuple[int, int]:
        """Count buses outside a voltage band.

        Args:
            below_pu: Lower limit; a bus strictly below it is under-voltage.
            above_pu: Upper limit; a bus strictly above it is over-voltage.

        Returns:
            ``(under_voltage_count, over_voltage_count)`` over
            :attr:`bus_voltage_pu` as held. A ``NaN`` entry compares false
            against both limits and so counts as neither, matching the pandas
            comparisons these counts replace. Call :meth:`drop_missing` first
            when the denominator must exclude unobserved buses.
        """
        voltage = self.bus_voltage_pu
        return (
            int((voltage < below_pu).sum()),
            int((voltage > above_pu).sum()),
        )

    def drop_missing(self) -> NetworkObservation:
        """Return the observation restricted to entries that were reported.

        Bus and line arrays are filtered independently, each keeping only its
        non-``NaN`` entries, exactly as the separate ``dropna()`` calls this
        replaces did. This is the explicit form of a distinction the tree
        already made silently: reductions agree either way, but any count
        divided by the array length does not.

        Returns:
            A new observation over the reported entries. ``converged``,
            ``total_line_loss_mw``, ``provenance`` and ``as_of`` are scalars
            and carry through unchanged -- filtering unobserved buses moves
            neither the instant the state belongs to nor where it came from.
        """
        keep_bus = ~np.isnan(self.bus_voltage_pu)
        return NetworkObservation(
            converged=self.converged,
            bus_ids=self.bus_ids[keep_bus],
            bus_voltage_pu=self.bus_voltage_pu[keep_bus],
            line_loading_percent=_present(self.line_loading_percent),
            total_line_loss_mw=self.total_line_loss_mw,
            provenance=self.provenance,
            as_of=self.as_of,
        )

    def voltage_frame(self) -> pd.DataFrame:
        """Return the canonical two-column bus-voltage table.

        Returns:
            A frame with columns ``["bus_id", "vm_pu"]``, one row per observed
            bus, in observation order -- the shape both the scenario runner
            and the voltage-profile figure rebuilt independently.
        """
        return pd.DataFrame(
            {
                "bus_id": self.bus_ids,
                BUS_VOLTAGE_COLUMN: self.bus_voltage_pu,
            }
        )


def observe_network(
    results: Any,
    *,
    as_of: datetime | None = None,
) -> NetworkObservation:
    """Read a :class:`NetworkObservation` off a solved network's result tables.

    This is the pandapower-shaped adapter, and the only place in the contract
    that knows those table names. It reads by attribute and column name rather
    than by type, so anything exposing ``res_bus`` / ``res_line`` frames
    satisfies it, and anything that does not can build a
    :class:`NetworkObservation` directly.

    Args:
        results: A solved network -- typically a ``pandapowerNet`` mutated in
            place by the simulation layer's power-flow backend. A missing
            table or column is read as "not reported" rather than raising,
            because the summary writers this replaces already tolerated it.
        as_of: The instant the solved state belongs to. Keyword-only and
            defaulting to ``None`` because ``results`` carries no clock of its
            own: only the caller that chose the operating point knows which
            instant it represents. Nothing is inferred when it is omitted --
            see :data:`AS_OF_ABSENT_REASON`.

    Returns:
        The observation. Absent bus/line tables yield empty arrays; an absent
        loss column yields ``total_line_loss_mw=None``, which is a different
        answer from ``0.0``; an omitted ``as_of`` yields ``as_of=None``. The
        provenance is always ``"simulated"``: this producer reads solver
        results, so that is the only honest answer it can give.
    """
    bus_voltage = _float_column(getattr(results, "res_bus", None), BUS_VOLTAGE_COLUMN)
    res_line = getattr(results, "res_line", None)
    line_loss = _float_column(res_line, LINE_LOSS_COLUMN)
    line_loading = _float_column(res_line, LINE_LOADING_COLUMN)
    if bus_voltage is None:
        bus_voltage = np.empty(0, dtype=float)
        bus_ids: np.ndarray = np.empty(0, dtype=int)
    else:
        bus_ids = np.asarray(results.res_bus.index)
    return NetworkObservation(
        converged=bool(getattr(results, "converged", False)),
        bus_ids=bus_ids,
        bus_voltage_pu=bus_voltage,
        line_loading_percent=(
            np.empty(0, dtype=float) if line_loading is None else line_loading
        ),
        total_line_loss_mw=(None if line_loss is None else float(np.nansum(line_loss))),
        provenance="simulated",
        as_of=as_of,
    )


__all__ = [
    "AS_OF_ABSENT_REASON",
    "BUS_VOLTAGE_COLUMN",
    "LINE_LOADING_COLUMN",
    "LINE_LOSS_COLUMN",
    "NetworkObservation",
    "ObservationProvenance",
    "observe_network",
]

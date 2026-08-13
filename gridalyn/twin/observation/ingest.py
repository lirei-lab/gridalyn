"""Measured-state ingest: tidy measurement rows become observations.

This module is the measured producer of :class:`NetworkObservation`. It reads
tidy ``(timestamp, entity_id, quantity, value)`` rows against the declared
schema below, joins entities to buses through user-supplied declared
configuration (:class:`EntityJoin`), and emits one
``NetworkObservation(provenance="measured")`` per instant, with
:attr:`NetworkObservation.as_of` stamped **from the datum** -- the timestamp
written in the input rows, never the wall clock and never an inference.

**Why this makes a digital shadow reachable.** Under Kritzinger's taxonomy the
classes are separated by *automated data flow*, not fidelity: a digital
*shadow* needs automated one-way flow from the observed physical system into
the model. This module is that flow's contract -- the moment a user points it
at their own AMI/SCADA export and declares the entity-to-bus join, measured
state streams into the same observation contract the simulated producer
feeds. The SDK ships the *path*, not measured data.

**Two things this module never does.** It never infers the entity join --
which entity is which bus is user-supplied declared configuration, and an
undeclared entity is a located error (inventing the join is what disqualified
the ``datasets/hq`` branch on merits). And it never infers a timestamp -- a
naive (tz-unaware) timestamp is a located error with a remediation, because
localizing it would manufacture evidence, the exact failure mode
:data:`gridalyn.twin.observation.contract.AS_OF_ABSENT_REASON` exists to
prevent.

**Why v1's quantity set is exactly ``{"voltage_pu"}``.** Every supported
quantity is a declared mapping onto a :class:`NetworkObservation` field, and
``bus_voltage_pu`` is the contract's only measured-mappable field today.
The emission is currently single-quantity: the loop in
:func:`read_measured_observations` hardcodes the ``bus_voltage_pu`` field, so
widening the set requires touching the emission site -- group by
``(as_of, quantity)`` and dispatch each group through the mapping -- not just
adding a key here. Guessing a mapping now would repeat the join-inference
failure mode this module exists to refuse.

**The mappings below are evidence, not tolerance** (the
:mod:`gridalyn.twin.network.schema` posture): every declared column and
quantity is one an emitted observation actually consumes, and nothing is
carried as defensive noise.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from gridalyn.twin.observation.contract import NetworkObservation

#: Column holding the instant each datum belongs to. Values must be tz-aware.
TIMESTAMP_COLUMN = "timestamp"

#: Column holding the measured entity's identifier, joined through
#: :class:`EntityJoin` to the twin's ``grid_buses`` identity namespace.
ENTITY_COLUMN = "entity_id"

#: Column naming what was measured; must be a key of
#: :data:`SUPPORTED_QUANTITIES`.
QUANTITY_COLUMN = "quantity"

#: Column holding the measured value; must be numeric.
VALUE_COLUMN = "value"

#: The declared tidy-measurement schema, in column order.
MEASUREMENT_COLUMNS = (
    TIMESTAMP_COLUMN,
    ENTITY_COLUMN,
    QUANTITY_COLUMN,
    VALUE_COLUMN,
)

#: The one quantity v1 supports: per-bus voltage magnitude in per-unit.
VOLTAGE_QUANTITY = "voltage_pu"

#: Declared mapping from a measured quantity name to the
#: :class:`NetworkObservation` field it feeds. Widening this is additive;
#: an unknown quantity fails loudly naming this set.
SUPPORTED_QUANTITIES: dict[str, str] = {VOLTAGE_QUANTITY: "bus_voltage_pu"}

#: Suffix-to-reader support of :func:`load_measurements`.
_SUPPORTED_SUFFIXES = (".csv", ".parquet")

#: Required columns of an :meth:`EntityJoin.from_frame` join frame.
_JOIN_COLUMNS = (ENTITY_COLUMN, "bus_id")

#: The remediation every naive-timestamp rejection carries.
_NAIVE_REMEDIATION = (
    "localize the export or include a UTC offset in every timestamp -- as_of "
    "is stamped from the datum, never inferred"
)

#: The remediation every missing-timestamp rejection carries. Deliberately
#: distinct from :data:`_NAIVE_REMEDIATION`: telling a user to localize a
#: value that is not there would be the wrong remedy.
_MISSING_REMEDIATION = (
    "every datum must carry the instant it was measured at; drop or repair "
    "the row(s) before ingest -- as_of is stamped from the datum, never "
    "inferred"
)


@dataclass(frozen=True)
class EntityJoin:
    """User-supplied declared join from measured entities to twin buses.

    The join is configuration, never inference: which measured entity sits on
    which bus is a fact only the operator of the observed system knows, and
    inventing it is exactly what disqualified the ``datasets/hq`` branch as a
    measured producer -- its 1000 anonymous ordinal columns carry no key into
    the twin's ``building_id``/``bus_id`` namespace, so any binding would have
    been manufactured rather than measured. An entity absent from this join is
    therefore a located error naming the entity, never a guess.

    Attributes:
        bus_by_entity: Declared mapping from a measured ``entity_id`` to the
            ``bus_id`` it sits on. Both are strings; ``bus_id`` is the twin's
            declared ``grid_buses`` identity namespace
            (:data:`gridalyn.twin.network.schema.GRID_BUSES`).
    """

    bus_by_entity: Mapping[str, str]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> EntityJoin:
        """Build a join from a declared ``entity_id -> bus_id`` mapping.

        Args:
            mapping: Declared entity-to-bus pairs. Must be non-empty, and
                every key and value must be a non-empty string.

        Returns:
            The validated join.

        Raises:
            ValueError: If the mapping is empty, or any key or value is
                ``None``, empty, or not a string.
        """
        if not mapping:
            raise ValueError(
                "EntityJoin.from_mapping: the mapping is empty; declare at "
                "least one entity_id -> bus_id pair -- the join is "
                "configuration, not inference"
            )
        for key, value in mapping.items():
            if not isinstance(key, str) or not key:
                raise ValueError(
                    "EntityJoin.from_mapping: every entity_id key must be a "
                    f"non-empty string, found {_describe(key)}"
                )
            if not isinstance(value, str) or not value:
                raise ValueError(
                    "EntityJoin.from_mapping: every bus_id value must be a "
                    f"non-empty string, found {_describe(value)} for "
                    f"entity_id {key!r}"
                )
        return cls(bus_by_entity=dict(mapping))

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> EntityJoin:
        """Build a join from a two-column ``entity_id``/``bus_id`` frame.

        Args:
            frame: Declared join table carrying an ``entity_id`` column and a
                ``bus_id`` column. Identifier values are read through
                ``astype(str)``, the identity comparison the declared schema
                uses for every ``grid_buses`` reference.

        Returns:
            The validated join.

        Raises:
            ValueError: If a required column is missing, any entry is null,
                or an ``entity_id`` appears more than once (the duplicates
                are named).
        """
        missing = [name for name in _JOIN_COLUMNS if name not in frame.columns]
        if missing:
            raise ValueError(
                "EntityJoin.from_frame: the join frame is missing required "
                f"column(s): {', '.join(missing)} (required columns: "
                f"{', '.join(_JOIN_COLUMNS)}; present columns: "
                f"{_present_columns(frame)})"
            )
        null_count = int(frame[list(_JOIN_COLUMNS)].isna().to_numpy().sum())
        if null_count:
            raise ValueError(
                f"EntityJoin.from_frame: the join frame carries {null_count} "
                "null entity_id/bus_id entr(y/ies); every pair must be "
                "declared explicitly -- the join is configuration, not "
                "inference"
            )
        entities = frame[ENTITY_COLUMN].astype(str)
        duplicated = sorted(entities[entities.duplicated()].unique())
        if duplicated:
            raise ValueError(
                "EntityJoin.from_frame: entity_id values appear more than "
                f"once: {', '.join(duplicated)}; each measured entity must "
                "join to exactly one bus_id"
            )
        pairs = zip(entities, frame["bus_id"].astype(str), strict=True)
        return cls.from_mapping(dict(pairs))


def read_measured_observations(
    measurements: pd.DataFrame,
    *,
    join: EntityJoin,
) -> tuple[NetworkObservation, ...]:
    """Read measured rows into one observation per instant.

    Groups the validated rows by their (tz-aware) timestamps, sorted
    ascending, and emits one :class:`NetworkObservation` per instant with
    ``provenance="measured"`` and ``as_of`` stamped from the datum. Mixed UTC
    offsets are normalized to UTC for grouping: the stamped ``as_of`` is the
    datum's instant expressed in UTC, never a different instant.

    ``converged`` is ``True`` on every emitted observation, deliberately: a
    measurement is a real operating point of the observed system, so
    convergence -- a solver concept -- does not apply, and ``True`` ("this
    state occurred") is the honest reading.

    Args:
        measurements: Tidy rows carrying :data:`MEASUREMENT_COLUMNS`. An
            empty frame (zero rows) yields ``()`` -- "no data" is not an
            error at this layer; loaders and callers decide.
        join: The declared entity-to-bus join. Keyword-only, because the join
            is the one input that must never be defaulted or inferred.

    Returns:
        One observation per distinct instant, in ascending ``as_of`` order.
        Each carries the joined bus ids in stable entity-sorted order, the
        measured voltages as float64, empty line arrays, and no loss total.

    Raises:
        ValueError: On a missing required column, a naive, missing
            (NaT/null) or unparseable timestamp, an unsupported quantity, an
            entity absent from the join, a duplicate
            ``(timestamp, entity_id, quantity)`` datum, or a non-numeric
            value. Every message locates the failure and names the remedy.
    """
    _require_columns(measurements)
    if len(measurements) == 0:
        return ()
    instants = _utc_timestamps(measurements[TIMESTAMP_COLUMN])
    _require_known_quantities(measurements[QUANTITY_COLUMN])
    entities = measurements[ENTITY_COLUMN].astype(str)
    _require_joined_entities(entities, join)
    _require_unique_data(instants, entities, measurements[QUANTITY_COLUMN])
    values = _numeric_values(measurements[VALUE_COLUMN])

    rows = pd.DataFrame(
        {
            "as_of": instants.to_numpy(),
            "entity": entities.to_numpy(),
            "value": values.to_numpy(),
        }
    )
    observations = []
    # LOUD COUPLING: the loop below hardcodes the bus_voltage_pu emission --
    # the field the single SUPPORTED_QUANTITIES entry maps to. Widening the
    # set requires grouping by (as_of, quantity) and dispatching each group
    # through the mapping; this assertion fails here, at the emission site,
    # the moment a second quantity is declared without that rework.
    assert len(SUPPORTED_QUANTITIES) == 1, (
        "the emission loop hardcodes bus_voltage_pu; widening "
        "SUPPORTED_QUANTITIES requires grouping by (as_of, quantity) and "
        "dispatching each group through the mapping"
    )
    for instant, group in rows.groupby("as_of", sort=True):
        ordered = group.sort_values("entity", kind="stable")
        bus_ids = np.array(
            [join.bus_by_entity[entity] for entity in ordered["entity"]],
            dtype=str,
        )
        observations.append(
            NetworkObservation(
                converged=True,
                bus_ids=bus_ids,
                bus_voltage_pu=ordered["value"].to_numpy(dtype=float),
                line_loading_percent=np.empty(0, dtype=float),
                total_line_loss_mw=None,
                provenance="measured",
                as_of=instant,
            )
        )
    return tuple(observations)


def load_measurements(path: Path | str) -> pd.DataFrame:
    """Load tidy measurement rows from a CSV or parquet export.

    Returns the raw frame; validation happens in
    :func:`read_measured_observations`, once, so both entry paths -- a frame
    built in memory and a file loaded here -- share the same contract.

    Args:
        path: Export to read. ``.csv`` is read with the timestamp column
            parsed; ``.parquet`` is read as written.

    Returns:
        The loaded frame, unvalidated.

    Raises:
        ValueError: If the suffix is not a supported measurement format.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(source, parse_dates=[TIMESTAMP_COLUMN])
        except ValueError:
            # The timestamp column is absent; return the raw frame so the
            # missing-column error comes from read_measured_observations,
            # located and remediating, shared with the in-memory path.
            return pd.read_csv(source)
    if suffix == ".parquet":
        return pd.read_parquet(source)
    raise ValueError(
        f"{source}: unsupported measurement file suffix {suffix!r} "
        f"(supported suffixes: {', '.join(_SUPPORTED_SUFFIXES)}); export the "
        "measurements as tidy CSV or parquet rows"
    )


def _describe(value: object) -> str:
    """Render a rejected value for an error message without a huge repr."""
    if isinstance(value, str):
        return "an empty string" if not value else repr(value)
    return type(value).__name__


def _present_columns(frame: pd.DataFrame) -> str:
    """Render a frame's columns for an error message, or say there are none."""
    if len(frame.columns) == 0:
        return "none"
    return ", ".join(str(name) for name in frame.columns)


def _require_columns(measurements: pd.DataFrame) -> None:
    """Raise unless every declared measurement column is present.

    Args:
        measurements: Frame to check against :data:`MEASUREMENT_COLUMNS`.

    Raises:
        ValueError: Naming the missing columns, the required set, and the
            present columns.
    """
    missing = [name for name in MEASUREMENT_COLUMNS if name not in measurements.columns]
    if missing:
        raise ValueError(
            "measurements frame is missing required column(s): "
            f"{', '.join(missing)} (required columns: "
            f"{', '.join(MEASUREMENT_COLUMNS)}; present columns: "
            f"{_present_columns(measurements)}); export tidy rows shaped "
            "(timestamp, entity_id, quantity, value)"
        )


def _missing_timestamp_error(position: int, value: object) -> ValueError:
    """Build the located error for a missing (NaT/null) timestamp value.

    Args:
        position: Row position of the missing entry.
        value: The raw missing entry, rendered for the message.

    Returns:
        ValueError: The located, remediating error for the caller to raise.
    """
    return ValueError(
        f"measurements column {TIMESTAMP_COLUMN!r} carries a missing "
        f"(NaT/null) timestamp at row {position} ({_describe(value)}); "
        f"{_MISSING_REMEDIATION}"
    )


def _scalar_tzinfo(value: object, position: int) -> tzinfo | None:
    """Return one raw timestamp value's ``tzinfo``, parsing scalars alone.

    Scalar parses are the sound classification instrument: measured on
    pandas 2.3.3, ``pd.to_datetime(column, format="ISO8601")`` over a *mixed*
    column silently coerces its naive elements -- to UTC, or to a neighbouring
    element's offset depending on element order -- so inspecting the parsed
    column can never find the naive row. A scalar parse has no mixed context
    and never coerces.

    Missing values are their own bucket, distinct from naive: ``None`` and
    ``NaT`` (checked before the datetime branch, because ``NaT`` *is* a
    ``datetime`` instance whose ``tzinfo`` is ``None`` and would otherwise be
    mislabeled naive), and anything pandas parses to ``NaT`` or ``None``
    (an empty string, for instance). Each is a located error carrying the
    missing-value remediation, never the "localize" remedy -- there is
    nothing to localize.

    Args:
        value: One raw timestamp entry; a datetime is inspected directly,
            anything else is parsed as an ISO 8601 scalar.
        position: Row position, used to locate a failure.

    Returns:
        tzinfo | None: The value's ``tzinfo`` (``None`` means naive).

    Raises:
        ValueError: If the value is a missing (NaT/null) timestamp, or
            cannot be parsed as a timestamp at all.
    """
    if value is None or value is pd.NaT:
        raise _missing_timestamp_error(position, value)
    if isinstance(value, datetime):
        return value.tzinfo
    try:
        parsed = pd.to_datetime(value, format="ISO8601")
    except (ValueError, TypeError):
        raise ValueError(
            f"measurements column {TIMESTAMP_COLUMN!r} carries an "
            f"unparseable timestamp at row {position}: {value!r} "
            f"({type(value).__name__}); every value must be an ISO 8601 "
            "timestamp with a UTC offset"
        ) from None
    if parsed is None or parsed is pd.NaT:
        raise _missing_timestamp_error(position, value)
    return parsed.tzinfo


def _utc_timestamps(column: pd.Series) -> pd.Series:
    """Validate the timestamp column and normalize it to UTC for grouping.

    Naive values are detected **before** any ``utc=True`` coercion, because
    ``pd.to_datetime(column, utc=True)`` silently reads a naive value as UTC
    and the mandated rejection would never fire. A stored ``datetime64``
    column is homogeneous by construction, so its dtype classifies the whole
    column; any other column is classified per element via scalar parses
    (see :func:`_scalar_tzinfo` for why the vectorized no-``utc`` parse
    cannot be trusted on mixed input).

    Args:
        column: The raw ``timestamp`` column.

    Returns:
        The instants as tz-aware UTC values. Mixed offsets are normalized to
        UTC: the stamped ``as_of`` is the datum's instant expressed in UTC.

    Raises:
        ValueError: If any value is naive (tz-unaware), missing (NaT/null)
            or unparseable, with the count and the matching remediation.
    """
    if pd.api.types.is_datetime64_any_dtype(column):
        if column.dt.tz is None:
            raise ValueError(
                f"measurements column {TIMESTAMP_COLUMN!r} carries "
                f"{int(column.size)} naive (tz-unaware) timestamp(s); "
                f"{_NAIVE_REMEDIATION}"
            )
        # NaT survives the tz-aware dtype check above, then the downstream
        # groupby would silently drop its datum (groupby drops null keys by
        # default); reject it here, at the classification site.
        missing = int(column.isna().sum())
        if missing:
            raise ValueError(
                f"measurements column {TIMESTAMP_COLUMN!r} carries "
                f"{missing} missing (NaT/null) timestamp(s); "
                f"{_MISSING_REMEDIATION}"
            )
        return pd.to_datetime(column, utc=True)
    naive_count = sum(
        1
        for position, value in enumerate(column)
        if _scalar_tzinfo(value, position) is None
    )
    if naive_count:
        raise ValueError(
            f"measurements column {TIMESTAMP_COLUMN!r} carries {naive_count} "
            f"naive (tz-unaware) timestamp(s); {_NAIVE_REMEDIATION}"
        )
    with warnings.catch_warnings():
        # pandas 2.3.3 warns (FutureWarning) that mixed offsets without
        # utc=True will change behaviour; every element is proven tz-aware
        # above and utc=True is exactly the requested normalization.
        warnings.simplefilter("ignore", FutureWarning)
        return pd.to_datetime(column, format="ISO8601", utc=True)


def _require_known_quantities(column: pd.Series) -> None:
    """Raise unless every quantity is a declared key of the supported set.

    Args:
        column: The raw ``quantity`` column.

    Raises:
        ValueError: Naming the unsupported quantities and the supported set.
    """
    unknown = sorted(str(value) for value in set(column) - set(SUPPORTED_QUANTITIES))
    if unknown:
        raise ValueError(
            f"measurements column {QUANTITY_COLUMN!r} carries unsupported "
            f"quantit(y/ies): {', '.join(unknown)} (supported quantities: "
            f"{', '.join(sorted(SUPPORTED_QUANTITIES))}); widening the "
            "supported set is a contract change, not a per-call option"
        )


def _require_joined_entities(entities: pd.Series, join: EntityJoin) -> None:
    """Raise unless every measured entity is declared in the join.

    Args:
        entities: The ``entity_id`` column, already read as strings.
        join: The declared entity-to-bus join.

    Raises:
        ValueError: Naming up to five missing entities, the total count, and
            the remediation.
    """
    missing = sorted(set(entities) - set(join.bus_by_entity))
    if missing:
        shown = ", ".join(missing[:5]) + (", ..." if len(missing) > 5 else "")
        raise ValueError(
            f"{len(missing)} measured entity_id(s) are absent from the "
            f"declared join: {shown}; declare them in the EntityJoin -- the "
            "join is configuration, not inference"
        )


def _require_unique_data(
    instants: pd.Series,
    entities: pd.Series,
    quantities: pd.Series,
) -> None:
    """Raise if any ``(timestamp, entity_id, quantity)`` datum repeats.

    Duplicates are detected on the UTC-normalized instants, so the same
    instant spelled through two different offsets is the same datum.

    Args:
        instants: UTC-normalized timestamps.
        entities: Entity identifiers as strings.
        quantities: Quantity names.

    Raises:
        ValueError: With the duplicate-row count.
    """
    keys = pd.DataFrame(
        {
            "as_of": instants.to_numpy(),
            "entity": entities.to_numpy(),
            "quantity": quantities.to_numpy(),
        }
    )
    duplicate_count = int(keys.duplicated().sum())
    if duplicate_count:
        raise ValueError(
            f"measurements carry {duplicate_count} duplicate (timestamp, "
            "entity_id, quantity) row(s); each datum must appear exactly "
            "once -- deduplicate the export"
        )


def _numeric_values(column: pd.Series) -> pd.Series:
    """Return the value column as floats, rejecting non-numeric entries.

    Args:
        column: The raw ``value`` column.

    Returns:
        The values as float64. A null input value stays ``NaN`` -- the
        observation contract's reductions already skip ``NaN``, and
        :meth:`NetworkObservation.drop_missing` makes the filtering explicit.

    Raises:
        ValueError: With the count of entries that are neither numeric nor
            null.
    """
    numeric = pd.to_numeric(column, errors="coerce")
    non_numeric_count = int((numeric.isna() & column.notna()).sum())
    if non_numeric_count:
        raise ValueError(
            f"measurements column {VALUE_COLUMN!r} carries "
            f"{non_numeric_count} non-numeric value(s); every measured value "
            "must be a number"
        )
    return numeric.astype(float)


__all__ = [
    "ENTITY_COLUMN",
    "EntityJoin",
    "MEASUREMENT_COLUMNS",
    "QUANTITY_COLUMN",
    "SUPPORTED_QUANTITIES",
    "TIMESTAMP_COLUMN",
    "VALUE_COLUMN",
    "VOLTAGE_QUANTITY",
    "load_measurements",
    "read_measured_observations",
]

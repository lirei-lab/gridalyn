"""Fixture-level proof of the measured-state ingest path.

Three behaviours are held here:

(a) ``as_of`` on every emitted observation equals a timestamp read from the
    input rows -- never inferred, never the wall clock;
(b) a naive (tz-unaware) timestamp is a located error with a remediation,
    proven on **both** an all-naive column and a mixed naive/aware column --
    the mixed shape matters because pandas 2.3.3's vectorized mixed parse
    silently localizes the naive element, so only per-element classification
    catches it;
(c) every other contract error -- undeclared entity, unsupported quantity,
    duplicate datum, non-numeric value -- is located and remediating.

The reductions test at the bottom is the seam claim: the observation
contract's accessors are producer-agnostic, so a measured observation answers
the same questions a simulated one does.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gridalyn.twin.observation.ingest import (
    MEASUREMENT_COLUMNS,
    SUPPORTED_QUANTITIES,
    EntityJoin,
    load_measurements,
    read_measured_observations,
)

#: A fixed 2018 instant, deliberately far from any wall clock this suite runs
#: under: equality against it proves as_of came from the datum.
T1 = "2018-01-15T06:00:00+00:00"
T2 = "2018-01-15T06:15:00+00:00"

JOIN = EntityJoin.from_mapping(
    {"meter_a": "bus_1", "meter_b": "bus_2", "meter_c": "bus_3"}
)


def _frame(rows: list[tuple[str, str, str, float | str]]) -> pd.DataFrame:
    """Build a tidy measurement frame from (timestamp, entity, quantity, value)."""
    return pd.DataFrame(rows, columns=list(MEASUREMENT_COLUMNS))


def _happy_frame() -> pd.DataFrame:
    """Two instants x three entities of voltage_pu, entities out of order."""
    return _frame(
        [
            (T1, "meter_b", "voltage_pu", 0.98),
            (T1, "meter_a", "voltage_pu", 0.97),
            (T1, "meter_c", "voltage_pu", 1.02),
            (T2, "meter_c", "voltage_pu", 1.01),
            (T2, "meter_a", "voltage_pu", 0.96),
            (T2, "meter_b", "voltage_pu", 0.99),
        ]
    )


# --------------------------------------------------------------------------
# the happy path, and as_of from the datum
# --------------------------------------------------------------------------


def test_happy_path_emits_one_observation_per_instant() -> None:
    """2 instants x 3 entities yield 2 observations with the joined buses."""
    observations = read_measured_observations(_happy_frame(), join=JOIN)

    assert len(observations) == 2
    first, second = observations
    assert first.as_of == datetime(2018, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert second.as_of == datetime(2018, 1, 15, 6, 15, tzinfo=timezone.utc)
    for observation in observations:
        assert observation.provenance == "measured"
        assert observation.converged is True
        assert list(observation.bus_ids) == ["bus_1", "bus_2", "bus_3"]
        assert observation.line_loading_percent.size == 0
        assert observation.total_line_loss_mw is None
    # Values land in bus_voltage_pu, in stable entity-sorted order.
    np.testing.assert_allclose(first.bus_voltage_pu, [0.97, 0.98, 1.02])
    np.testing.assert_allclose(second.bus_voltage_pu, [0.96, 0.99, 1.01])
    assert first.bus_voltage_pu.dtype == np.float64


def test_as_of_is_read_from_the_datum_not_the_wall_clock() -> None:
    """as_of equals the fixture's 2018 instant, not anything like now."""
    (observation,) = read_measured_observations(
        _frame([(T1, "meter_a", "voltage_pu", 1.0)]), join=JOIN
    )

    assert observation.as_of is not None
    assert observation.as_of == datetime(2018, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert observation.as_of.tzinfo is not None
    assert observation.as_of.date() != datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------
# the three timestamp shapes: all-naive, all-aware single-tz, mixed
# --------------------------------------------------------------------------


def test_all_naive_string_timestamps_are_rejected() -> None:
    """An all-naive column is a located error, never a silent localization."""
    frame = _frame(
        [
            ("2018-01-15T06:00:00", "meter_a", "voltage_pu", 1.0),
            ("2018-01-15T06:15:00", "meter_a", "voltage_pu", 1.0),
        ]
    )

    with pytest.raises(ValueError, match="localize"):
        read_measured_observations(frame, join=JOIN)


def test_all_naive_datetime64_timestamps_are_rejected() -> None:
    """A pre-parsed naive datetime64 column trips the dtype-level check."""
    frame = _frame([(T1, "meter_a", "voltage_pu", 1.0)])
    frame["timestamp"] = pd.to_datetime(["2018-01-15T06:00:00"])
    assert frame["timestamp"].dt.tz is None  # the shape under test

    with pytest.raises(ValueError, match="localize"):
        read_measured_observations(frame, join=JOIN)


def test_all_aware_single_offset_timestamps_are_accepted() -> None:
    """A single non-UTC offset parses; as_of is that instant in UTC."""
    frame = _frame(
        [
            ("2018-01-15T01:00:00-05:00", "meter_a", "voltage_pu", 0.97),
            ("2018-01-15T01:00:00-05:00", "meter_b", "voltage_pu", 0.98),
        ]
    )

    (observation,) = read_measured_observations(frame, join=JOIN)

    # 01:00-05:00 is 06:00 UTC: the same instant, expressed in UTC.
    assert observation.as_of == datetime(2018, 1, 15, 6, 0, tzinfo=timezone.utc)


def test_mixed_offsets_with_one_naive_row_are_rejected() -> None:
    """The naive row is caught even when aware rows surround it.

    The aware-first ordering is deliberate: it is the ordering in which
    pandas 2.3.3's vectorized no-utc parse silently localizes the naive
    element to a neighbouring offset, so a classification that trusted the
    parsed column would let this row through.
    """
    frame = _frame(
        [
            ("2018-01-15T01:00:00-05:00", "meter_a", "voltage_pu", 1.0),
            ("2018-01-15T06:00:00+00:00", "meter_b", "voltage_pu", 1.0),
            ("2018-01-15T06:15:00", "meter_c", "voltage_pu", 1.0),
        ]
    )

    with pytest.raises(ValueError, match="1 naive.*localize"):
        read_measured_observations(frame, join=JOIN)


def test_mixed_aware_offsets_normalize_to_utc_for_grouping() -> None:
    """Two spellings of one instant land in one observation, stamped UTC."""
    frame = _frame(
        [
            ("2018-01-15T01:00:00-05:00", "meter_a", "voltage_pu", 0.97),
            ("2018-01-15T06:00:00+00:00", "meter_b", "voltage_pu", 0.98),
        ]
    )

    (observation,) = read_measured_observations(frame, join=JOIN)

    assert observation.as_of == datetime(2018, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert list(observation.bus_ids) == ["bus_1", "bus_2"]


# --------------------------------------------------------------------------
# located errors: entity, quantity, duplicate, non-numeric, columns
# --------------------------------------------------------------------------


def test_an_undeclared_entity_is_a_located_error() -> None:
    """The error names the entity and the remedy: declare it in the join."""
    frame = _frame([(T1, "meter_x", "voltage_pu", 1.0)])

    with pytest.raises(ValueError, match="meter_x") as excinfo:
        read_measured_observations(frame, join=JOIN)
    assert "EntityJoin" in str(excinfo.value)


def test_an_unsupported_quantity_is_a_located_error() -> None:
    """The error names the offender and the supported set."""
    frame = _frame([(T1, "meter_a", "power_kw", 1.0)])

    with pytest.raises(ValueError, match="power_kw") as excinfo:
        read_measured_observations(frame, join=JOIN)
    assert "voltage_pu" in str(excinfo.value)


def test_a_duplicate_datum_is_rejected_with_a_count() -> None:
    """The same (timestamp, entity, quantity) twice is one error, counted."""
    row = (T1, "meter_a", "voltage_pu", 1.0)

    with pytest.raises(ValueError, match="1 duplicate"):
        read_measured_observations(_frame([row, row]), join=JOIN)


def test_a_non_numeric_value_is_rejected_with_a_count() -> None:
    """A value that is not a number is an error, not a coerced NaN."""
    frame = _frame([(T1, "meter_a", "voltage_pu", "not-a-number")])

    with pytest.raises(ValueError, match="1 non-numeric"):
        read_measured_observations(frame, join=JOIN)


def test_a_missing_required_column_is_a_located_error() -> None:
    """The error names the missing column, the required set, and what is there."""
    frame = _frame([(T1, "meter_a", "voltage_pu", 1.0)]).drop(columns=["quantity"])

    with pytest.raises(ValueError, match="quantity") as excinfo:
        read_measured_observations(frame, join=JOIN)
    message = str(excinfo.value)
    assert "required columns" in message
    assert "entity_id" in message


def test_an_empty_frame_yields_no_observations() -> None:
    """Zero rows against the declared columns is 'no data', not an error."""
    frame = pd.DataFrame(columns=list(MEASUREMENT_COLUMNS))

    assert read_measured_observations(frame, join=JOIN) == ()


# --------------------------------------------------------------------------
# EntityJoin: declared configuration, never inference
# --------------------------------------------------------------------------


def test_from_mapping_rejects_an_empty_mapping() -> None:
    """An empty join declares nothing and is refused."""
    with pytest.raises(ValueError, match="empty"):
        EntityJoin.from_mapping({})


def test_from_frame_rejects_a_duplicated_entity() -> None:
    """An entity joined to two buses is named in the error."""
    frame = pd.DataFrame(
        {"entity_id": ["meter_a", "meter_a"], "bus_id": ["bus_1", "bus_2"]}
    )

    with pytest.raises(ValueError, match="meter_a"):
        EntityJoin.from_frame(frame)


def test_from_frame_builds_the_declared_join() -> None:
    """A valid two-column frame becomes the declared mapping, as strings."""
    frame = pd.DataFrame({"entity_id": ["meter_a"], "bus_id": ["bus_1"]})

    join = EntityJoin.from_frame(frame)

    assert join.bus_by_entity == {"meter_a": "bus_1"}


# --------------------------------------------------------------------------
# loaders: CSV and parquet share the one validation path
# --------------------------------------------------------------------------


def _assert_same_observations(
    left: tuple[object, ...], right: tuple[object, ...]
) -> None:
    """Assert two observation tuples agree on as_of, buses, and values."""
    assert len(left) == len(right)
    for a, b in zip(left, right, strict=True):
        assert a.as_of == b.as_of  # type: ignore[attr-defined]
        assert list(a.bus_ids) == list(b.bus_ids)  # type: ignore[attr-defined]
        np.testing.assert_allclose(
            a.bus_voltage_pu,  # type: ignore[attr-defined]
            b.bus_voltage_pu,  # type: ignore[attr-defined]
        )


def test_csv_round_trip_matches_the_in_memory_path(tmp_path: Path) -> None:
    """A CSV export loads and reads to the same as_of and values."""
    frame = _happy_frame()
    path = tmp_path / "measurements.csv"
    frame.to_csv(path, index=False)

    direct = read_measured_observations(frame, join=JOIN)
    loaded = read_measured_observations(load_measurements(path), join=JOIN)

    _assert_same_observations(direct, loaded)


def test_parquet_round_trip_matches_the_in_memory_path(tmp_path: Path) -> None:
    """A parquet export loads and reads to the same as_of and values."""
    frame = _happy_frame()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    path = tmp_path / "measurements.parquet"
    frame.to_parquet(path, index=False)

    direct = read_measured_observations(frame, join=JOIN)
    loaded = read_measured_observations(load_measurements(path), join=JOIN)

    _assert_same_observations(direct, loaded)


def test_an_unsupported_suffix_is_a_located_error(tmp_path: Path) -> None:
    """The error names the offending suffix and the supported set."""
    path = tmp_path / "measurements.h5"
    path.write_bytes(b"")

    with pytest.raises(ValueError, match=r"\.h5") as excinfo:
        load_measurements(path)
    assert ".parquet" in str(excinfo.value)


# --------------------------------------------------------------------------
# the seam claim: the contract's reductions are producer-agnostic
# --------------------------------------------------------------------------


def test_contract_reductions_work_on_a_measured_observation() -> None:
    """min/max/violation counts answer the same on measured state."""
    frame = _frame(
        [
            (T1, "meter_a", "voltage_pu", 0.90),
            (T1, "meter_b", "voltage_pu", 1.00),
            (T1, "meter_c", "voltage_pu", 1.10),
        ]
    )

    (observation,) = read_measured_observations(frame, join=JOIN)

    assert observation.min_voltage_pu == pytest.approx(0.90)
    assert observation.max_voltage_pu == pytest.approx(1.10)
    assert observation.voltage_violation_counts(below_pu=0.95, above_pu=1.05) == (1, 1)


def test_the_supported_quantity_set_is_the_declared_v1_set() -> None:
    """The quantity map is exactly voltage_pu -> bus_voltage_pu."""
    assert SUPPORTED_QUANTITIES == {"voltage_pu": "bus_voltage_pu"}

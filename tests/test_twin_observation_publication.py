"""A deployment must be able to say whether it is a digital shadow.

``NetworkObservation.provenance`` separates ``"simulated"`` from ``"measured"``
inside the contract, and nothing outside it could say which. These tests pin
what :mod:`gridalyn.twin.observation.publication` resolves: the answer for an
instance with measured data, the answer for one without, and the fact that the
second is an answer rather than a silence.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import get_args

import pandas as pd

from gridalyn.twin.observation.contract import ObservationProvenance
from gridalyn.twin.observation.ingest import (
    JOIN_COLUMNS,
    MEASUREMENT_COLUMNS,
    SUPPORTED_QUANTITIES,
)
from gridalyn.twin.observation.publication import (
    ENTITY_JOIN_STEM,
    JOIN_ABSENT_REASON,
    MEASURED_ABSENT_REASON,
    PROVENANCE_MEASURED,
    PROVENANCE_SIMULATED,
    PROVENANCE_VALUES,
    resolve_observation_publication,
)


def _write_measurements(directory: Path, name: str = "ami_export.csv") -> Path:
    path = directory / name
    pd.DataFrame(
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "entity_id": "meter:0",
                "quantity": "voltage_pu",
                "value": 0.98,
            }
        ]
    ).to_csv(path, index=False)
    return path


def _write_join(directory: Path, suffix: str = ".csv") -> Path:
    path = directory / f"{ENTITY_JOIN_STEM}{suffix}"
    frame = pd.DataFrame([{"entity_id": "meter:0", "bus_id": "bus:0"}])
    if suffix == ".csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path)
    return path


class AbsentMeasuredStateTest(unittest.TestCase):
    """Every instance this repository ships is in this state."""

    def test_a_missing_directory_is_not_an_error(self):
        publication = resolve_observation_publication("/nonexistent-observations")
        self.assertFalse(publication.available)
        self.assertEqual((), publication.measured_sources)
        self.assertIsNone(publication.entity_join)

    def test_the_answer_is_simulated_not_unknown(self):
        """A model is not a shadow, and says which it is."""
        publication = resolve_observation_publication("/nonexistent-observations")
        self.assertEqual(PROVENANCE_SIMULATED, publication.provenance)

    def test_the_absence_carries_its_reason_and_its_remedy(self):
        publication = resolve_observation_publication("/nonexistent-observations")
        self.assertEqual(MEASURED_ABSENT_REASON, publication.absent_reason)
        self.assertIn(
            "ships the ingest path, not measured data", publication.absent_reason
        )
        self.assertIn("gridalyn.twin.observation.ingest", publication.absent_reason)

    def test_the_directory_is_named_even_when_it_holds_nothing(self):
        """ "There are none" and "I looked somewhere else" must differ."""
        publication = resolve_observation_publication("/nonexistent-observations")
        self.assertEqual(Path("/nonexistent-observations"), publication.directory)

    def test_an_empty_directory_reads_the_same_as_a_missing_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            publication = resolve_observation_publication(tmp)
        self.assertFalse(publication.available)
        self.assertEqual(MEASURED_ABSENT_REASON, publication.absent_reason)


class PresentMeasuredStateTest(unittest.TestCase):
    def test_exports_plus_a_declared_join_make_a_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            export = _write_measurements(directory)
            join = _write_join(directory)
            publication = resolve_observation_publication(directory)
        self.assertTrue(publication.available)
        self.assertEqual((export,), publication.measured_sources)
        self.assertEqual(join, publication.entity_join)
        self.assertEqual(PROVENANCE_MEASURED, publication.provenance)
        self.assertIsNone(publication.absent_reason)

    def test_exports_without_a_join_are_not_a_shadow_and_say_why(self):
        """The ingest refuses to infer the join; so does this."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_measurements(directory)
            publication = resolve_observation_publication(directory)
        self.assertFalse(publication.available)
        self.assertEqual(PROVENANCE_SIMULATED, publication.provenance)
        self.assertEqual(JOIN_ABSENT_REASON, publication.absent_reason)
        # A distinct remedy: telling an operator to add data they already
        # added would be the wrong one.
        self.assertNotEqual(MEASURED_ABSENT_REASON, publication.absent_reason)

    def test_a_join_without_exports_is_not_a_shadow_either(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_join(directory)
            publication = resolve_observation_publication(directory)
        self.assertFalse(publication.available)
        self.assertEqual(MEASURED_ABSENT_REASON, publication.absent_reason)

    def test_the_join_is_not_counted_as_a_measurement_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_measurements(directory)
            _write_join(directory)
            publication = resolve_observation_publication(directory)
        self.assertEqual(1, len(publication.measured_sources))
        self.assertNotIn(publication.entity_join, publication.measured_sources)

    def test_both_supported_suffixes_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_measurements(directory, "a.csv")
            pd.DataFrame([{"timestamp": "t"}]).to_parquet(directory / "b.parquet")
            _write_join(directory)
            publication = resolve_observation_publication(directory)
        self.assertEqual(
            ["a.csv", "b.parquet"],
            [path.name for path in publication.measured_sources],
        )

    def test_an_unsupported_file_is_ignored_rather_than_offered(self):
        """`load_measurements` reads two suffixes; nothing else is an export."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "README.md").write_text("notes", encoding="utf-8")
            _write_measurements(directory)
            _write_join(directory)
            publication = resolve_observation_publication(directory)
        self.assertEqual(
            ["ami_export.csv"],
            [path.name for path in publication.measured_sources],
        )

    def test_a_directory_with_two_join_spellings_resolves_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_measurements(directory)
            _write_join(directory, ".csv")
            _write_join(directory, ".parquet")
            first = resolve_observation_publication(directory)
            second = resolve_observation_publication(directory)
        self.assertEqual(first.entity_join, second.entity_join)
        self.assertEqual(f"{ENTITY_JOIN_STEM}.csv", first.entity_join.name)


class ObservationPayloadTest(unittest.TestCase):
    def test_the_payload_publishes_the_contract_an_export_must_satisfy(self):
        payload = resolve_observation_publication("/nowhere").to_dict()
        measured = payload["measured"]
        self.assertEqual(list(MEASUREMENT_COLUMNS), measured["columns"])
        self.assertEqual(sorted(SUPPORTED_QUANTITIES), measured["quantities"])
        self.assertEqual(list(JOIN_COLUMNS), measured["join_columns"])

    def test_the_payload_publishes_the_contracts_full_provenance_vocabulary(self):
        """A client renders the distinction from the twin's words, not its own."""
        payload = resolve_observation_publication("/nowhere").to_dict()
        self.assertEqual(list(PROVENANCE_VALUES), payload["provenance_values"])
        self.assertEqual(["simulated", "measured"], payload["provenance_values"])

    def test_the_vocabulary_is_derived_from_the_contract_not_restated(self):
        """A third provenance added to the contract must reach the catalog.

        Restating the set here would let this module and the field it
        describes drift, which is the failure the 1.1/1.2 schema gap was.
        """
        self.assertEqual(get_args(ObservationProvenance), PROVENANCE_VALUES)
        self.assertIn(PROVENANCE_SIMULATED, PROVENANCE_VALUES)
        self.assertIn(PROVENANCE_MEASURED, PROVENANCE_VALUES)

    def test_the_payload_always_answers_available(self):
        payload = resolve_observation_publication("/nowhere").to_dict()
        self.assertIn("available", payload["measured"])
        self.assertIs(False, payload["measured"]["available"])
        self.assertIsNotNone(payload["measured"]["absent_reason"])


if __name__ == "__main__":
    unittest.main()

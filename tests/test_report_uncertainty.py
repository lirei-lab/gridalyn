"""The uncertainty block must carry a defensible number or be rejected.

CLAUDE.md's Core Value promises headline numbers reported with their
uncertainty. These tests hold the contract to the part that makes the promise
worth anything: a block that names a metric the report does not carry, or whose
point estimate contradicts its own interval, is a contract error rather than a
stored field.
"""

from __future__ import annotations

import unittest

from gridalyn.foundation.platform.reports import (
    ReportMetadata,
    build_report,
    validate_report,
)
from gridalyn.foundation.platform.uncertainty import (
    METHODS,
    MIN_DRAWS,
    UncertaintyEstimate,
    build_uncertainty,
    estimate_from_samples,
    percentile,
    validate_uncertainty,
)

_METADATA = ReportMetadata(report_id="r", source_domain="simulation")


def _estimate(**overrides: object) -> UncertaintyEstimate:
    base = dict(
        metric="peak_kw",
        method="monte_carlo",
        n=50,
        point=11.0,
        low=10.0,
        high=13.0,
        level=0.9,
        seed=42,
    )
    base.update(overrides)
    return UncertaintyEstimate(**base)  # type: ignore[arg-type]


class TestPercentile(unittest.TestCase):
    def test_matches_numpy_linear_convention(self) -> None:
        """Foundation is stdlib-only, so the convention is pinned by test."""
        samples = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(percentile(samples, 0.0), 1.0)
        self.assertAlmostEqual(percentile(samples, 1.0), 4.0)
        self.assertAlmostEqual(percentile(samples, 0.5), 2.5)
        self.assertAlmostEqual(percentile(samples, 0.25), 1.75)

    def test_unordered_input_is_sorted_first(self) -> None:
        self.assertAlmostEqual(percentile([4.0, 1.0, 3.0, 2.0], 0.5), 2.5)

    def test_empty_samples_is_a_located_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            percentile([], 0.5)
        self.assertIn("at least one sample", str(ctx.exception))


class TestEstimateFromSamples(unittest.TestCase):
    def test_interval_brackets_the_median(self) -> None:
        estimate = estimate_from_samples("peak_kw", [float(i) for i in range(100)])
        self.assertLessEqual(estimate.low, estimate.point)
        self.assertLessEqual(estimate.point, estimate.high)
        self.assertEqual(estimate.n, 100)
        self.assertEqual(estimate.level, 0.90)

    def test_too_few_draws_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            estimate_from_samples("peak_kw", [1.0])
        self.assertIn(f"at least {MIN_DRAWS} draws", str(ctx.exception))

    def test_unknown_method_enumerates_the_valid_set(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            estimate_from_samples("peak_kw", [1.0, 2.0], method="vibes")
        message = str(ctx.exception)
        self.assertIn("'vibes'", message)
        for method in METHODS:
            self.assertIn(method, message)


class TestBuildUncertainty(unittest.TestCase):
    def test_an_empty_block_is_refused_rather_than_stored(self) -> None:
        """The gap does not close by adding an empty field."""
        with self.assertRaises(ValueError) as ctx:
            build_uncertainty([])
        self.assertIn("omit the uncertainty block", str(ctx.exception))

    def test_duplicate_metrics_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            build_uncertainty([_estimate(), _estimate()])


class TestValidateUncertainty(unittest.TestCase):
    def test_a_well_formed_block_passes(self) -> None:
        block = build_uncertainty([_estimate()])
        self.assertEqual(validate_uncertainty(block, {"peak_kw": 11.0}), [])

    def test_a_metric_the_summary_does_not_carry_is_rejected(self) -> None:
        block = build_uncertainty([_estimate()])
        errors = validate_uncertainty(block, {"something_else": 1.0})
        self.assertTrue(errors)
        self.assertIn("does not carry", errors[0])

    def test_a_point_outside_its_own_interval_is_rejected(self) -> None:
        block = build_uncertainty([_estimate(point=99.0)])
        errors = validate_uncertainty(block, {"peak_kw": 99.0})
        self.assertTrue(any("outside its own interval" in e for e in errors))

    def test_a_point_disagreeing_with_the_summary_is_rejected(self) -> None:
        """The interval must qualify the number the report actually carries."""
        block = build_uncertainty([_estimate()])
        errors = validate_uncertainty(block, {"peak_kw": 12.5})
        self.assertTrue(any("disagrees with summary" in e for e in errors))

    def test_an_inverted_interval_is_rejected(self) -> None:
        block = {"peak_kw": {**_estimate().to_dict(), "interval": [13.0, 10.0]}}
        errors = validate_uncertainty(block, {"peak_kw": 11.0})
        self.assertTrue(any("inverted" in e for e in errors))

    def test_an_out_of_range_level_is_rejected(self) -> None:
        block = {"peak_kw": {**_estimate().to_dict(), "level": 90}}
        errors = validate_uncertainty(block, {"peak_kw": 11.0})
        self.assertTrue(any(".level" in e for e in errors))

    def test_too_few_draws_is_rejected(self) -> None:
        block = {"peak_kw": {**_estimate().to_dict(), "n": 1}}
        errors = validate_uncertainty(block, {"peak_kw": 11.0})
        self.assertTrue(any(".n must be an integer" in e for e in errors))

    def test_an_empty_block_is_rejected(self) -> None:
        self.assertEqual(
            validate_uncertainty({}, {}),
            ["uncertainty must not be empty; omit the field instead"],
        )


class TestReportContractIntegration(unittest.TestCase):
    def test_a_report_without_uncertainty_is_unchanged(self) -> None:
        """The field is optional; 74 existing reports must stay valid."""
        payload = build_report(metadata=_METADATA, summary={"peak_kw": 11.0})
        self.assertNotIn("uncertainty", payload)
        self.assertEqual(validate_report(payload), [])

    def test_a_valid_block_is_carried_into_the_payload(self) -> None:
        payload = build_report(
            metadata=_METADATA,
            summary={"peak_kw": 11.0},
            uncertainty=build_uncertainty([_estimate()]),
        )
        self.assertEqual(payload["uncertainty"]["peak_kw"]["n"], 50)
        self.assertEqual(validate_report(payload), [])

    def test_build_report_refuses_an_incoherent_block(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_report(
                metadata=_METADATA,
                summary={"peak_kw": 11.0},
                uncertainty=build_uncertainty([_estimate(metric="absent_metric")]),
            )
        self.assertIn("invalid uncertainty block", str(ctx.exception))

    def test_validate_report_catches_a_block_written_by_hand(self) -> None:
        payload = build_report(metadata=_METADATA, summary={"peak_kw": 11.0})
        payload["uncertainty"] = {"peak_kw": {"method": "guess", "n": 0}}
        errors = validate_report(payload)
        self.assertTrue(any(".method" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

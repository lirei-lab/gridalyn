"""The EnergyPlus validation receipts must stay readable and self-consistent.

``tools/ochre_calibration/`` is the only external white-box reference this
platform has for the RC building model. Its toolchain cannot run in CI, so the
harness is not re-executed here; what is checked is that its published receipts
are present, satisfy the contracts they claim, and do not contradict the
metered arbiter where that arbiter is available.

The distinction matters: this is not a validation test. It is a test that the
validation remains legible.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "ochre_calibration"))

import receipts  # noqa: E402

from gridalyn.simulation.surrogates.contract import MEASURED  # noqa: E402

_HQ = REPO_ROOT / "datasets" / "hq"
_HQ_SKIP = (
    "datasets/hq is private Hydro-Quebec data and is gitignored; this "
    "cross-check runs only on a machine that holds it. The EnergyPlus "
    "receipts themselves are asserted unconditionally above."
)


class TestErrorBoundReceipt(unittest.TestCase):
    def test_the_bound_satisfies_the_error_bound_contract(self) -> None:
        """Constructing it runs the contract's own validation over the file."""
        bound = receipts.load_rc_error_bound()
        self.assertEqual(bound.status, MEASURED)
        self.assertGreater(bound.sample_size, 0)
        self.assertTrue(bound.method.strip(), "a bound must state its protocol")
        self.assertIn("EnergyPlus", bound.reference)

    def test_the_bound_equals_promised_minus_delivered(self) -> None:
        """The scalar is defined as promised relief minus delivered relief.

        Asserting the identity keeps the headline number tied to the two
        quantities it is derived from, so an edit to one without the other is
        caught rather than shipped.
        """
        payload = receipts._read("rc_error_bound.json")
        promised = float(payload["promised_kw_per_home"])
        delivered = float(payload["delivered_kw_per_home"])
        self.assertAlmostEqual(
            abs(promised - delivered), float(payload["value"]), places=2
        )

    def test_the_model_understates_rather_than_overstates_relief(self) -> None:
        """Direction is the whole point: conservative, not optimistic.

        If this ever flips, the RC model would be promising more relief than
        the white-box reference delivers, and every flexibility headline built
        on it would need re-reading.
        """
        payload = receipts._read("rc_error_bound.json")
        self.assertLess(
            float(payload["promised_kw_per_home"]),
            float(payload["delivered_kw_per_home"]),
        )


class TestFlexibilityHoldout(unittest.TestCase):
    def test_the_holdout_is_disjoint_and_non_trivial(self) -> None:
        payload = receipts._read("flexbound.json")
        fit = payload["fit"]["dwellings"]
        holdout = payload["holdout"]["dwellings"]
        self.assertGreater(holdout, 0)
        self.assertEqual(
            fit + holdout,
            payload["dwellings"],
            "fit and holdout must partition the pool; an overlap would make "
            "the reported bound optimistic",
        )

    def test_comfort_cost_is_stated_and_bounded(self) -> None:
        """A relief number without its comfort cost is half a result."""
        holdout = receipts.load_flexibility_holdout()
        self.assertLess(holdout.comfort_drift_c_worst, 0.0)
        self.assertGreater(
            holdout.comfort_drift_c_worst,
            -5.0,
            "the shipped decision is a bounded setback, not full curtailment; "
            "a drift beyond -5 C means this receipt is reporting a different "
            "experiment than the one the study dispatches",
        )

    def test_relief_exceeds_rebound(self) -> None:
        """A dispatch that only moves the peak later has not helped anyone."""
        holdout = receipts.load_flexibility_holdout()
        self.assertGreater(holdout.mean_relief_kw_per_home, holdout.rebound_kw_per_home)


class TestCoincidenceCurve(unittest.TestCase):
    def test_coincidence_falls_with_group_size(self) -> None:
        curve = receipts.load_coincidence_curve("validation")
        sizes = sorted(curve)
        values = [curve[n] for n in sizes]
        self.assertEqual(
            values,
            sorted(values, reverse=True),
            "coincidence must fall as more dwellings share a transformer",
        )

    def test_both_splits_agree(self) -> None:
        """Calibration and validation halves must not tell different stories."""
        cal = receipts.load_coincidence_curve("calibration")
        val = receipts.load_coincidence_curve("validation")
        for size in sorted(set(cal) & set(val)):
            self.assertAlmostEqual(
                cal[size],
                val[size],
                delta=0.05,
                msg=f"split disagreement at {size} homes",
            )

    @unittest.skipUnless((_HQ / "consumption.h5").is_file(), _HQ_SKIP)
    def test_energyplus_curve_tracks_the_metered_arbiter(self) -> None:
        """EnergyPlus is a corroborating reference, not the arbiter.

        ``datasets/hq`` settles coincidence; this asserts the EnergyPlus curve
        stays close enough to be worth citing beside it.
        """
        import numpy as np

        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from test_building_diversity_vs_hq import _all_electric_winter

        metered = _all_electric_winter()
        rng = np.random.default_rng(0)
        curve = receipts.load_coincidence_curve("validation")
        for size in (6, 12, 24):
            draws = []
            for _ in range(40):
                sample = metered[:, rng.choice(metered.shape[1], size, False)]
                draws.append(sample.sum(axis=1).max() / sample.max(axis=0).sum())
            self.assertAlmostEqual(
                curve[size],
                float(np.mean(draws)),
                delta=0.10,
                msg=f"EnergyPlus vs metered coincidence at {size} homes",
            )


if __name__ == "__main__":
    unittest.main()

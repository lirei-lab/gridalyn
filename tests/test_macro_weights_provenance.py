"""The packaged macro weights must stay identifiable and described truthfully.

Every governed CI-fixture study declares ``generator: parametric``, so these two
pickles are the inputs of every CI-verified baseline in the repository. Before
PROVENANCE.md existed nothing recorded what they were trained on, and nothing
would have noticed if they were replaced.

These tests do not re-train and do not need the private dataset. They pin the
digests, and they check that the documented facts still match what the pickles
actually contain -- a document that drifts from its subject is the failure mode
this repository has already paid for elsewhere.
"""

from __future__ import annotations

import hashlib
import pickle
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = REPO_ROOT / "gridalyn" / "assets" / "datagen" / "models" / "weights"
PROVENANCE = WEIGHTS / "PROVENANCE.md"

#: Pinned so a substitution is a failing test rather than a silent change to
#: every baseline's inputs. Regenerating these is a deliberate act: see
#: tools/train_macro_weights.py, which refuses without an explicit flag.
DIGESTS = {
    "lgbm_heating_macro.pkl": (
        "e8a2885a8643ae62ec0f0af6a57408cfcbc51cc279c6dd1ae50b948e33953f35"
    ),
    "lgbm_bg_macro.pkl": (
        "6753b0f4a2d5fab68142a997a93ff8ae2e0094e7e04090116a4eacf261de13fb"
    ),
}

#: The training-row count, recoverable from either model as the sum of tree-0's
#: leaf counts. Equals the row count of datasets/hq/consumption.h5.
TRAINING_ROWS = 35041

FEATURES = ["temperature", "hour_sin", "hour_cos", "hour"]


def _leaf_count_sum(node: dict) -> int:
    """Return the total training rows reaching the leaves under ``node``.

    Args:
        node: A LightGBM dumped tree-structure node.

    Returns:
        The summed ``leaf_count`` of every leaf beneath it.
    """
    if "leaf_count" in node:
        return int(node["leaf_count"])
    return _leaf_count_sum(node["left_child"]) + _leaf_count_sum(node["right_child"])


def _model(name: str):
    with open(WEIGHTS / name, "rb") as handle:
        return pickle.load(handle)


class TestWeightsAreIdentifiable(unittest.TestCase):
    def test_both_weight_files_ship(self) -> None:
        for name in DIGESTS:
            self.assertTrue((WEIGHTS / name).is_file(), f"{name} is not packaged")

    def test_digests_are_pinned(self) -> None:
        """A substitution must fail here, not surface as moved baselines."""
        for name, expected in DIGESTS.items():
            actual = hashlib.sha256((WEIGHTS / name).read_bytes()).hexdigest()
            self.assertEqual(
                actual,
                expected,
                f"{name} has changed. If that was deliberate, update this "
                "digest and PROVENANCE.md together, and re-base every governed "
                "baseline with a recorded rationale -- these weights are the "
                "inputs of all of them.",
            )


class TestProvenanceDocumentIsTrue(unittest.TestCase):
    """The document must keep describing the pickles it claims to describe."""

    def test_the_document_exists(self) -> None:
        self.assertTrue(PROVENANCE.is_file())

    def test_it_records_both_digests(self) -> None:
        text = PROVENANCE.read_text(encoding="utf-8")
        for name, digest in DIGESTS.items():
            self.assertIn(digest, text, f"{name} digest absent from PROVENANCE")

    def test_it_names_the_private_dataset_and_says_it_is_private(self) -> None:
        """The privacy limit is a real constraint, not a silent gitignore."""
        text = PROVENANCE.read_text(encoding="utf-8").lower()
        self.assertIn("datasets/hq", text)
        self.assertIn("private", text)

    def test_documented_features_match_the_models(self) -> None:
        for name in DIGESTS:
            with self.subTest(model=name):
                self.assertEqual(list(_model(name).feature_name_), FEATURES)
        text = PROVENANCE.read_text(encoding="utf-8")
        for feature in FEATURES:
            self.assertIn(feature, text)

    def test_documented_row_count_matches_the_models(self) -> None:
        """Tree-0's leaf counts sum to the number of training rows."""
        for name in DIGESTS:
            with self.subTest(model=name):
                dumped = _model(name).booster_.dump_model()
                tree = dumped["tree_info"][0]["tree_structure"]
                self.assertEqual(_leaf_count_sum(tree), TRAINING_ROWS)
        self.assertIn(str(TRAINING_ROWS), PROVENANCE.read_text(encoding="utf-8"))

    def test_documented_temperature_support_matches_the_models(self) -> None:
        """The support is what makes the cold-tail limit legible."""
        for name in DIGESTS:
            with self.subTest(model=name):
                info = _model(name).booster_.dump_model()["feature_infos"]
                self.assertAlmostEqual(
                    info["temperature"]["min_value"], -24.366666666666664, places=9
                )
                self.assertAlmostEqual(info["temperature"]["max_value"], 36.1, places=9)


class TestDocumentedColdLimitHolds(unittest.TestCase):
    def test_heating_is_flat_below_the_lowest_split(self) -> None:
        """PROVENANCE states the model cannot extrapolate below -20.488 C.

        Asserted so the documented limit cannot quietly stop being true, and so
        a future retrain that fixes it fails here and forces the document to be
        updated with it. Tracked as the cold-tail saturation defect.
        """
        import numpy as np
        import pandas as pd

        model = _model("lgbm_heating_macro.pkl")
        hours = np.arange(96) * 0.25

        def predict(temperature: float) -> float:
            frame = pd.DataFrame(
                {
                    "temperature": np.full(96, temperature),
                    "hour_sin": np.sin(2 * np.pi * hours / 24.0),
                    "hour_cos": np.cos(2 * np.pi * hours / 24.0),
                    "hour": hours,
                }
            )
            return float(np.maximum(model.predict(frame), 0.0).mean())

        shelf = predict(-21.0)
        for colder in (-25.0, -30.0, -40.0):
            self.assertAlmostEqual(
                predict(colder),
                shelf,
                places=9,
                msg="the documented cold-tail shelf has changed; update "
                "PROVENANCE.md and syntgrid-5am.2 together",
            )
        self.assertGreater(
            predict(-15.0),
            0.0,
            "inside its support the model must still respond to temperature",
        )
        self.assertLess(predict(-15.0), shelf)


if __name__ == "__main__":
    unittest.main()

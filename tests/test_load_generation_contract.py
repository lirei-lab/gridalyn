"""Tests for the declarative loadGeneration project input."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gridalyn.projects import init_project
from gridalyn.projects.model_inputs import (
    load_generated_bus_loads_mw,
    load_generated_load_multipliers,
    load_generated_load_profiles,
)


LOAD_GENERATION_BLOCK = """\
    loadGeneration:
      nUnits: 12
      seed: 7
      resolutionMinutes: 60
      multipliers:
        intervals: 24
        peakMultiplier: 1.26
"""


def _project_with_block(tmp: str, block: str = LOAD_GENERATION_BLOCK) -> Path:
    target = Path(tmp) / "my_case"
    init_project(target, name="my_case")
    project_file = target / "project.yaml"
    text = project_file.read_text(encoding="utf-8")
    project_file.write_text(
        text.replace("  inputs:\n    raw: inputs\n", "  inputs:\n    raw: inputs\n" + block),
        encoding="utf-8",
    )
    return target


class TestLoadGeneratedLoadProfiles(unittest.TestCase):
    def test_generates_declared_profiles_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp)

            first = load_generated_load_profiles(target)
            second = load_generated_load_profiles(target)

            self.assertEqual(first.shape, (24, 12))
            self.assertTrue(first.equals(second))

    def test_missing_required_field_is_located(self) -> None:
        block = "    loadGeneration:\n      nUnits: 12\n"
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp, block)

            with self.assertRaises(ValueError) as ctx:
                load_generated_load_profiles(target)

            message = str(ctx.exception)
            self.assertIn("spec.inputs.loadGeneration.seed", message)
            self.assertIn("present fields:", message)

    def test_unsupported_key_is_reported(self) -> None:
        block = "    loadGeneration:\n      nUnits: 12\n      seed: 7\n      houses: 3\n"
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp, block)

            with self.assertRaises(ValueError) as ctx:
                load_generated_load_profiles(target)

            message = str(ctx.exception)
            self.assertIn("unsupported keys: houses", message)
            self.assertIn("supported:", message)


class TestLoadGeneratedLoadMultipliers(unittest.TestCase):
    def test_multipliers_hit_declared_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp)

            multipliers = load_generated_load_multipliers(target)

            self.assertEqual(len(multipliers), 24)
            self.assertAlmostEqual(float(multipliers.max()), 1.26, places=9)

    def test_missing_multipliers_block_is_located(self) -> None:
        block = "    loadGeneration:\n      nUnits: 12\n      seed: 7\n"
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp, block)

            with self.assertRaises(ValueError) as ctx:
                load_generated_load_multipliers(target)

            message = str(ctx.exception)
            self.assertIn("spec.inputs.loadGeneration.multipliers", message)
            self.assertIn("intervals", message)


class TestLoadGeneratedBusLoads(unittest.TestCase):
    def test_snapshot_total_is_anchored(self) -> None:
        anchors = {1: 0.035, 2: 0.045, 3: 0.030, 4: 0.040}
        with tempfile.TemporaryDirectory() as tmp:
            target = _project_with_block(tmp)

            snapshot = load_generated_bus_loads_mw(target, anchor_loads_mw=anchors)

            self.assertEqual(sorted(snapshot), sorted(anchors))
            self.assertAlmostEqual(
                sum(snapshot.values()), sum(anchors.values()), places=9
            )


if __name__ == "__main__":
    unittest.main()

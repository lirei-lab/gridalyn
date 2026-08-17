"""Tests for the SDK LV-feeder spec constructor (RadialFeederSpec variant)."""

from __future__ import annotations

import unittest

from gridalyn.assets.modeling.feeders import (
    RadialFeederSpec,
    lv_feeder_spec,
    validate_radial_feeder_spec,
)


class TestLvFeederSpec(unittest.TestCase):
    def test_returns_valid_spec(self) -> None:
        spec = lv_feeder_spec(
            name="lv-01",
            bus_count=3,
            sn_mva=0.4,
            base_voltage_kv=0.4,
            loads_mw={1: 0.01, 2: 0.02},
        )
        self.assertIsInstance(spec, RadialFeederSpec)
        validate_radial_feeder_spec(spec)  # no raise
        self.assertEqual(spec.name, "lv-01")
        self.assertEqual(spec.bus_count, 3)
        self.assertEqual(spec.sn_mva, 0.4)
        self.assertEqual(spec.loads_mw, {1: 0.01, 2: 0.02})
        self.assertEqual(spec.metadata["class"], "lv")

    def test_is_deterministic(self) -> None:
        kwargs = {
            "name": "lv-01",
            "bus_count": 3,
            "sn_mva": 0.4,
            "base_voltage_kv": 0.4,
            "loads_mw": {1: 0.01, 2: 0.02},
        }
        spec_a = lv_feeder_spec(**kwargs)
        spec_b = lv_feeder_spec(**kwargs)
        self.assertEqual(spec_a, spec_b)

    def test_invalid_spec_raises_located(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            lv_feeder_spec(
                name="bad",
                bus_count=1,
                sn_mva=0.4,
                base_voltage_kv=0.4,
                loads_mw={},
            )
        self.assertIn("bus_count", str(ctx.exception))

    def test_load_on_slack_bus_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            lv_feeder_spec(
                name="bad",
                bus_count=3,
                sn_mva=0.4,
                base_voltage_kv=0.4,
                loads_mw={0: 0.01},
            )
        self.assertIn("slack bus 0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

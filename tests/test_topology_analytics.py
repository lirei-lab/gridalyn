"""Tests for the SDK radial-feeder topology analytics (GAP-1 / GAP-2 closure)."""

from __future__ import annotations

import unittest

import pandapower as pp

from gridalyn.simulation.analytics.topology import (
    assert_radial_no_generation,
    downstream_bus_map,
    thermal_ratings_kw,
)


def _radial_with_transformer() -> pp.pandapowerNet:
    """Build a small radial net: ext_grid - line - trafo - line - load bus."""
    net = pp.create_empty_network(sn_mva=1.0)
    pp.create_bus(net, vn_kv=12.47, name="mv1")  # 0
    pp.create_bus(net, vn_kv=12.47, name="mv2")  # 1
    pp.create_bus(net, vn_kv=0.4, name="lv1")  # 2
    pp.create_bus(net, vn_kv=0.4, name="lv2")  # 3
    pp.create_ext_grid(net, bus=0, vm_pu=1.0)
    pp.create_line_from_parameters(
        net,
        from_bus=0,
        to_bus=1,
        length_km=0.1,
        r_ohm_per_km=0.2,
        x_ohm_per_km=0.1,
        c_nf_per_km=5.0,
        max_i_ka=0.3,
    )
    pp.create_transformer_from_parameters(
        net,
        hv_bus=1,
        lv_bus=2,
        sn_mva=0.4,
        vn_hv_kv=12.47,
        vn_lv_kv=0.4,
        vk_percent=4.0,
        vkr_percent=1.0,
        pfe_kw=0.1,
        i0_percent=0.1,
    )
    pp.create_line_from_parameters(
        net,
        from_bus=2,
        to_bus=3,
        length_km=0.05,
        r_ohm_per_km=0.5,
        x_ohm_per_km=0.2,
        c_nf_per_km=5.0,
        max_i_ka=0.2,
    )
    pp.create_load(net, bus=3, p_mw=0.02, q_mvar=0.006)
    return net


class TestThermalRatingsKw(unittest.TestCase):
    def test_per_line_and_per_transformer_rating_formula(self) -> None:
        net = _radial_with_transformer()
        ratings = thermal_ratings_kw(net, pf=0.95)

        # line 0 (mv): max_i_ka=0.3 * vn(12.47) * sqrt(3) * 1000 * 0.95
        expected_line = 0.3 * 12.47 * 1.7320508075688772 * 1000.0 * 0.95
        self.assertAlmostEqual(ratings["line:0"], expected_line, places=3)
        # trafo 0: sn_mva=0.4 * 1000 * 0.95
        self.assertAlmostEqual(ratings["transformer:0"], 0.4 * 1000.0 * 0.95, places=3)
        # line 1 (lv): max_i_ka=0.2 * vn(0.4) * sqrt(3) * 1000 * 0.95
        expected_lv_line = 0.2 * 0.4 * 1.7320508075688772 * 1000.0 * 0.95
        self.assertAlmostEqual(ratings["line:1"], expected_lv_line, places=3)

    def test_pf_out_of_range_raises(self) -> None:
        net = _radial_with_transformer()
        with self.assertRaises(ValueError):
            thermal_ratings_kw(net, pf=0.0)
        with self.assertRaises(ValueError):
            thermal_ratings_kw(net, pf=1.5)

    def test_missing_net_table_raises_located(self) -> None:
        class BareNet:
            pass

        with self.assertRaises(ValueError) as ctx:
            thermal_ratings_kw(BareNet(), pf=0.95)
        self.assertIn("net.bus", str(ctx.exception))


class TestDownstreamBusMap(unittest.TestCase):
    def test_transformer_hop_includes_lv_subtree(self) -> None:
        net = _radial_with_transformer()
        mapping = downstream_bus_map(net)

        # Feeder-head transformer (0 -> 2) downstream includes LV buses 2 and 3.
        self.assertEqual(mapping["transformer:0"], frozenset({2, 3}))
        # MV line 0 (0 -> 1) downstream includes 1, 2, 3.
        self.assertEqual(mapping["line:0"], frozenset({1, 2, 3}))
        # LV line 1 (2 -> 3) downstream includes only 3.
        self.assertEqual(mapping["line:1"], frozenset({3}))

    def test_explicit_root_used(self) -> None:
        net = _radial_with_transformer()
        mapping = downstream_bus_map(net, root_bus=2)
        # Rooted at bus 2: line:1 (2 -> 3) downstream is {3}.
        self.assertEqual(mapping["line:1"], frozenset({3}))
        # transformer:0 oriented from root 2 -> 1 (far-from-root = hv side 1);
        # descendants of 1 include bus 0 via line:0, so downstream is {0, 1}.
        self.assertEqual(mapping["transformer:0"], frozenset({0, 1}))


class TestAssertRadialNoGeneration(unittest.TestCase):
    def test_radial_net_passes(self) -> None:
        net = _radial_with_transformer()
        assert_radial_no_generation(net)  # no raise

    def test_non_radial_raises(self) -> None:
        net = _radial_with_transformer()
        # Add a second line creating a cycle between buses 1 and 3 via a new bus.
        pp.create_bus(net, vn_kv=0.4, name="lv3")  # 4
        pp.create_line_from_parameters(
            net,
            from_bus=1,
            to_bus=4,
            length_km=0.05,
            r_ohm_per_km=0.5,
            x_ohm_per_km=0.2,
            c_nf_per_km=5.0,
            max_i_ka=0.2,
        )
        pp.create_line_from_parameters(
            net,
            from_bus=4,
            to_bus=3,
            length_km=0.05,
            r_ohm_per_km=0.5,
            x_ohm_per_km=0.2,
            c_nf_per_km=5.0,
            max_i_ka=0.2,
        )
        with self.assertRaises(ValueError) as ctx:
            assert_radial_no_generation(net)
        self.assertIn("not radial", str(ctx.exception))

    def test_embedded_generation_raises(self) -> None:
        net = _radial_with_transformer()
        pp.create_sgen(net, bus=3, p_mw=0.005, q_mvar=0.0)
        with self.assertRaises(ValueError) as ctx:
            assert_radial_no_generation(net)
        self.assertIn("embedded generation", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

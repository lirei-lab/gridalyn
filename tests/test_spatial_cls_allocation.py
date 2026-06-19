import unittest

import numpy as np

from gridalyn.operations import (
    allocate_addition_by_headroom,
    allocate_reduction,
    apply_spatial_cls,
)


class SpatialClsAllocationTest(unittest.TestCase):
    def test_allocate_reduction_respects_eligibility_and_capacity(self):
        load_kw = np.array([[2.0, 10.0, 4.0], [1.0, 20.0, 1.0]])
        target_kw = np.array([3.0, 10.0])
        eligible = np.array([True, False, True])

        curtailed, delivered = allocate_reduction(load_kw, target_kw, eligible)

        np.testing.assert_allclose(delivered, [3.0, 2.0])
        np.testing.assert_allclose(curtailed[0], [1.0, 0.0, 2.0])
        np.testing.assert_allclose(curtailed[1], [1.0, 0.0, 1.0])
        self.assertTrue(np.all(curtailed <= load_kw))

    def test_apply_spatial_cls_uses_soft_buildings_then_hard_ev_backstop(self):
        building_kw = np.array([[2.0, 10.0, 4.0], [1.0, 20.0, 1.0]])
        ev_kw = np.array([[1.0, 3.0, 5.0], [0.0, 2.0, 1.0]])
        soft_target_kw = np.array([3.0, 10.0])
        hard_target_kw = np.array([2.0, 10.0])
        soft_eligible = np.array([True, False, True])
        hard_preferred = np.array([False, True, False])
        ev_eligible = np.array([False, True, True])

        result = apply_spatial_cls(
            building_kw=building_kw,
            ev_kw=ev_kw,
            soft_cls_kw=soft_target_kw,
            hard_cls_kw=hard_target_kw,
            soft_eligible=soft_eligible,
            hard_preferred=hard_preferred,
            ev_eligible=ev_eligible,
        )

        np.testing.assert_allclose(result.soft_delivered_kw, [3.0, 2.0])
        np.testing.assert_allclose(result.hard_delivered_kw, [2.0, 3.0])
        np.testing.assert_allclose(result.hard_curtailed_kw[0], [0.0, 2.0, 0.0])
        np.testing.assert_allclose(result.hard_curtailed_kw[1], [0.0, 2.0, 1.0])
        self.assertTrue(np.all(result.managed_building_kw >= 0.0))
        self.assertTrue(np.all(result.managed_ev_kw >= 0.0))

    def test_allocate_addition_by_headroom_caps_rebound_at_charger_headroom(self):
        load_kw = np.array([[1.0, 3.0, 4.0], [3.0, 3.5, 4.0]])
        target_kw = np.array([4.0, 4.0])
        eligible = np.array([True, True, False])
        charger_kw = np.array([4.0, 4.0, 4.0])

        added, delivered = allocate_addition_by_headroom(
            load_kw, target_kw, eligible, charger_kw
        )

        np.testing.assert_allclose(delivered, [4.0, 1.5])
        np.testing.assert_allclose(added[0], [3.0, 1.0, 0.0])
        np.testing.assert_allclose(added[1], [1.0, 0.5, 0.0])
        self.assertTrue(np.all(load_kw + added <= charger_kw + 1e-12))


if __name__ == "__main__":
    unittest.main()

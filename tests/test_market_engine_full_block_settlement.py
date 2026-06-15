"""Economic invariants for the full-block (capacity-availability) settlement.

The paper settles a cleared 30-min capacity block as an availability product
(paper Eq. 17): the reservation is paid for the block's full duration, not only
the 5-min timesteps with an active real-time deficit. These tests lock in that
``pay_full_block`` changes only the money — never the physical dispatch — and
that it never pays less than the utilization-only convention.
"""

import numpy as np
import unittest

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.operations.market.dso_dispatch import DSODispatcher
from gridalyn.operations.market.engine import MarketSimulationEngine


class LoadEqualsThetaModel:
    """Thermal proxy where hottest-spot temperature equals the load (kW)."""

    theta_max = 100.0

    def max_load_for_temp(self, _ambient_c):
        return 100.0

    def simulate_profile(self, load_profile_kw, _ambient_profile_c, dt_min=1.0):
        return np.asarray(load_profile_kw, dtype=float)


def _run(pay_full_block: bool):
    network = MVNetwork(
        p_limit_kw=100.0,
        p_emergency_kw=120.0,
        p_rated_kw=100.0,
        transformer_mva=0.1,
        thermal_model=LoadEqualsThetaModel(),
    )
    dispatcher = DSODispatcher(
        network=network,
        dt_man_h=5.0 / 60.0,
        epsilon=0.05,
        stochastic_failure_rate=0.0,
    )
    engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    # A 30-minute block (6 x 5-min steps) congested only in steps 2-3, so steps
    # 0-1 and 4-5 are "reserved but released" — the case full-block payment fixes.
    base = np.array([70.0, 70.0, 110.0, 110.0, 70.0, 70.0])
    return engine.run(
        p_base_kw_mean=base,
        p_base_kw_std=np.zeros_like(base),
        p_ev_kw_mean=np.zeros_like(base),
        p_ev_kw_std=np.zeros_like(base),
        t_out_trace_c=np.zeros_like(base),
        dt_man_h=5.0 / 60.0,
        n_total_blocks=4,
        participation_rate=1.0,
        epsilon=0.05,
        is_profiled=True,
        market_resolution_h=0.5,
        pay_full_block=pay_full_block,
    )


class FullBlockSettlementTest(unittest.TestCase):
    def setUp(self):
        self.partial = _run(pay_full_block=False)
        self.full = _run(pay_full_block=True)

    def test_physical_dispatch_is_identical(self):
        for column in ("soft_cls_kw", "hard_cls_kw", "rebound_kw", "managed_load_kw"):
            np.testing.assert_allclose(
                self.full[column].to_numpy(),
                self.partial[column].to_numpy(),
                rtol=0.0,
                atol=1e-9,
                err_msg=f"{column} must not change under pay_full_block",
            )

    def test_full_block_pays_at_least_as_much(self):
        self.assertGreaterEqual(
            self.full["market_settlement_cost"].sum(),
            self.partial["market_settlement_cost"].sum(),
        )

    def test_reservation_paid_in_released_timesteps(self):
        # A cleared block reserves capacity in steps 0-1 and 4-5 even though no
        # deficit is active there; the utilization-only convention pays nothing.
        released = [0, 1, 4, 5]
        partial_released = self.partial["market_settlement_cost"].to_numpy()[released]
        full_released = self.full["market_settlement_cost"].to_numpy()[released]
        self.assertTrue(np.allclose(partial_released, 0.0))
        self.assertGreater(full_released.sum(), 0.0)

    def test_penalties_unchanged(self):
        np.testing.assert_allclose(
            self.full["market_penalties"].to_numpy(),
            self.partial["market_penalties"].to_numpy(),
            atol=1e-9,
        )


if __name__ == "__main__":
    unittest.main()

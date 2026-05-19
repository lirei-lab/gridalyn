import numpy as np
import unittest

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.market.engine import MarketSimulationEngine


class FixedLimitThermalModel:
    theta_max = 100.0

    def max_load_for_temp(self, _ambient_c):
        return 100.0

    def simulate_profile(self, load_profile_kw, _ambient_profile_c, dt_min=1.0):
        return np.zeros_like(load_profile_kw, dtype=float)


class MarketEngineRiskDispatchTest(unittest.TestCase):
    def test_hard_cls_covers_chance_constrained_shortfall_when_mean_is_below_limit(self):
        network = MVNetwork(
            p_limit_kw=100.0,
            p_emergency_kw=120.0,
            p_rated_kw=100.0,
            transformer_mva=0.1,
            thermal_model=FixedLimitThermalModel(),
        )
        dispatcher = DSODispatcher(
            network=network,
            epsilon=0.05,
            stochastic_failure_rate=0.0,
        )
        engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)

        result = engine.run(
            p_base_kw_mean=np.array([80.0]),
            p_base_kw_std=np.array([10.0]),
            p_ev_kw_mean=np.array([10.0]),
            p_ev_kw_std=np.array([0.0]),
            t_out_trace_c=np.array([0.0]),
            n_total_blocks=1,
            participation_rate=0.0,
            epsilon=0.05,
        )

        expected_shortfall = result.loc[0, "target_deficit_kw"]
        self.assertGreater(expected_shortfall, 0)
        self.assertEqual(result.loc[0, "soft_cls_kw"], 0.0)
        self.assertEqual(result.loc[0, "hard_cls_kw"], expected_shortfall)
        self.assertLessEqual(
            result.loc[0, "managed_worst_kw"],
            result.loc[0, "thermal_limit_kw"],
        )


if __name__ == "__main__":
    unittest.main()

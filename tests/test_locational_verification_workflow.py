import unittest
from unittest.mock import patch

import pandapower as pp

from gridalyn.interfaces.cli import flexibility
from gridalyn.workflows.flexibility import locational_verification
from gridalyn.projects.workflows.scripts.run_digital_twin_ev_powerflow import (
    _normalize_pandapower_timeseries_net,
)


class LocationalVerificationWorkflowTest(unittest.TestCase):
    def test_flexibility_cli_routes_verify_clearing_to_workflow(self):
        with patch.object(locational_verification, "main", return_value=0) as main:
            result = flexibility.main(["verify-clearing", "--scenario-id", "S4"])

        self.assertEqual(result, 0)
        main.assert_called_once_with(["--scenario-id", "S4"])

    def test_powerflow_loader_normalizes_legacy_load_columns(self):
        net = pp.create_empty_network()
        bus = pp.create_bus(net, vn_kv=0.4)
        pp.create_ext_grid(net, bus)
        pp.create_load(net, bus, p_mw=0.01, q_mvar=0.001)
        net.load = net.load.drop(
            columns=[
                "const_z_p_percent",
                "const_i_p_percent",
                "const_z_q_percent",
                "const_i_q_percent",
            ]
        )
        net.pop("vsc_stacked")
        net.pop("vsc_bipolar")

        _normalize_pandapower_timeseries_net(net)

        self.assertTrue(hasattr(net, "vsc_stacked"))
        self.assertTrue(hasattr(net, "vsc_bipolar"))
        for column in [
            "const_z_p_percent",
            "const_i_p_percent",
            "const_z_q_percent",
            "const_i_q_percent",
        ]:
            self.assertIn(column, net.load.columns)
            self.assertEqual(float(net.load[column].iloc[0]), 0.0)


if __name__ == "__main__":
    unittest.main()

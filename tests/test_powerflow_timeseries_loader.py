"""Pandapower timeseries-net normalisation for the digital-twin powerflow run.

Split out of ``test_locational_verification_workflow.py`` on 2026-08-06. That
module also asserted that ``gridalyn market verify-clearing`` routed to the
locational-verification workflow; the command and the workflow were retired
with the ``flexibility_cls`` study that produced their input, so only this
check -- which was always unrelated to them -- remains.
"""

from __future__ import annotations

import unittest

import pandapower as pp

from gridalyn.projects.workflows.scripts.run_digital_twin_ev_powerflow import (
    _normalize_pandapower_timeseries_net,
)


class PowerflowTimeseriesLoaderTest(unittest.TestCase):
    def test_powerflow_loader_normalizes_legacy_load_columns(self) -> None:
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

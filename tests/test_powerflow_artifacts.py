from __future__ import annotations

import json
from pathlib import Path

import pandapower as pp

from gridalyn.foundation import ReportMetadata
from gridalyn.simulation.simulators.powerflow import (
    build_pandapower_summary,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def _solved_network() -> pp.pandapowerNet:
    net = pp.create_empty_network(sn_mva=1.0)
    pp.create_bus(net, vn_kv=12.47, name="source")
    pp.create_bus(net, vn_kv=12.47, name="load")
    pp.create_ext_grid(net, bus=0, vm_pu=1.0)
    pp.create_line_from_parameters(
        net,
        from_bus=0,
        to_bus=1,
        length_km=0.1,
        r_ohm_per_km=0.2,
        x_ohm_per_km=0.1,
        c_nf_per_km=5.0,
        max_i_ka=0.2,
    )
    pp.create_load(net, bus=1, p_mw=0.05, q_mvar=0.01)
    pp.runpp(net)
    return net


def test_powerflow_artifact_helpers_write_tables_figure_and_report(tmp_path: Path) -> None:
    net = _solved_network()

    tables = write_pandapower_element_tables(net, tmp_path / "data")
    figure = write_voltage_profile_figure(
        net,
        tmp_path / "figures" / "voltage.png",
        title="Test feeder",
    )
    summary = build_pandapower_summary(net, network="unit_test_feeder")
    report = write_powerflow_report(
        tmp_path / "reports" / "powerflow.json",
        metadata=ReportMetadata(
            report_id="unit_test_powerflow",
            source_domain="unit_test",
            project={"name": "unit_test"},
        ),
        net=net,
        inputs=[{"name": "unit_test_feeder", "type": "test_network"}],
        artifacts=[*tables.values(), figure],
        summary={"network": "unit_test_feeder"},
    )

    assert set(tables) == {"buses", "lines", "loads"}
    assert all(path.exists() for path in tables.values())
    assert figure.exists()
    assert summary["bus_count"] == 2
    assert summary["line_count"] == 1
    assert summary["load_count"] == 1
    assert summary["converged"] is True
    assert report["validation"]["valid"] is True
    persisted = json.loads((tmp_path / "reports" / "powerflow.json").read_text())
    assert persisted["summary"]["network"] == "unit_test_feeder"

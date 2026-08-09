"""Pandapower builders for Gridalyn benchmark feeder contracts."""

from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn

from gridalyn.assets.modeling.benchmarks import (
    IEEE_33_BUS_BENCHMARK,
    IeeeBenchmarkFeederSpec,
)
from gridalyn.simulation.backends.registry import solve_power_flow


def build_ieee33_benchmark_feeder(
    spec: IeeeBenchmarkFeederSpec = IEEE_33_BUS_BENCHMARK,
    *,
    run_powerflow: bool = False,
) -> pp.pandapowerNet:
    """Build the IEEE 33-bus benchmark through Gridalyn's model contract."""
    if spec.benchmark_id != IEEE_33_BUS_BENCHMARK.benchmark_id:
        raise ValueError(f"unsupported IEEE benchmark feeder: {spec.benchmark_id}")
    net = pn.case33bw()
    if len(net.bus) != spec.expected_bus_count:
        raise ValueError(
            f"{spec.display_name} expected {spec.expected_bus_count} buses, got {len(net.bus)}"
        )
    if len(net.line) != spec.expected_line_count:
        raise ValueError(
            f"{spec.display_name} expected {spec.expected_line_count} lines, "
            f"got {len(net.line)}"
        )
    if len(net.load) != spec.expected_load_count:
        raise ValueError(
            f"{spec.display_name} expected {spec.expected_load_count} loads, "
            f"got {len(net.load)}"
        )
    if run_powerflow:
        solve_power_flow(net)
    return net


__all__ = ["build_ieee33_benchmark_feeder"]

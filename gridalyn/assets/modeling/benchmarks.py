"""Benchmark feeder asset-model contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IeeeBenchmarkFeederSpec:
    """Stable Gridalyn contract for a known IEEE distribution benchmark."""

    benchmark_id: str
    display_name: str
    source_name: str
    expected_bus_count: int
    expected_line_count: int
    expected_load_count: int


IEEE_33_BUS_BENCHMARK = IeeeBenchmarkFeederSpec(
    benchmark_id="ieee_33_bus",
    display_name="IEEE 33-Bus Distribution Feeder",
    source_name="pandapower.networks.case33bw",
    expected_bus_count=33,
    expected_line_count=37,
    expected_load_count=32,
)


__all__ = ["IEEE_33_BUS_BENCHMARK", "IeeeBenchmarkFeederSpec"]

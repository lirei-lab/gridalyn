"""Smoke test for the pilot external backend extension (Phase 18, 18-01)."""

from __future__ import annotations

import pilot_backend

from gridalyn.simulation.backends.contract import PowerFlowBackendDescriptor


def test_descriptor_is_conformant() -> None:
    descriptor = pilot_backend.descriptor
    assert isinstance(descriptor, PowerFlowBackendDescriptor)
    assert descriptor.backend_id == "pilot_native_backend"
    assert descriptor.capability is None
    assert descriptor.contract_version == "1"


def test_factory_returns_a_solvable_backend() -> None:
    backend = pilot_backend.factory()
    assert backend.descriptor.backend_id == "pilot_native_backend"
    assert callable(backend.solve)


def test_backend_solves_a_minimal_network() -> None:
    # Review cycle 1 (solve never exercised): prove the "working backend, not a
    # stub" claim — the delegation to pandapower native actually converges.
    import pandapower as pp

    net = pp.create_empty_network()
    hv = pp.create_bus(net, vn_kv=20.0)
    lv = pp.create_bus(net, vn_kv=0.4)
    pp.create_transformer(
        net,
        hv,
        lv,
        std_type="0.25 MVA 20/0.4 kV",
    )
    pp.create_ext_grid(net, hv)
    pp.create_load(net, lv, p_mw=0.1, q_mvar=0.02)
    pilot_backend.factory().solve(net)
    assert net.converged

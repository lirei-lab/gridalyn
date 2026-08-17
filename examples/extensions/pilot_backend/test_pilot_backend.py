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

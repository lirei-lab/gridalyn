"""Smoke test for the hello_world extension (scaffolded by gridalyn extension new)."""

from __future__ import annotations

import hello_world

from gridalyn.foundation.platform.extensions import SUPPORTED_CONTRACT_VERSIONS


def test_descriptor_is_conformant() -> None:
    descriptor = hello_world.descriptor
    assert descriptor.extension_id == "hello_world"
    assert descriptor.role == "data_source"
    assert descriptor.contract_version in SUPPORTED_CONTRACT_VERSIONS


def test_factory_is_callable() -> None:
    assert callable(hello_world.factory)

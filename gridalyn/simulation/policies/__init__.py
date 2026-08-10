"""Pluggable voltage-control policy contracts and registry."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "SENSITIVITY_DISPATCH_POLICY_ID": (
        "gridalyn.simulation.policies.contract",
        "SENSITIVITY_DISPATCH_POLICY_ID",
    ),
    "TABULAR_RL_POLICY_ID": (
        "gridalyn.simulation.policies.contract",
        "TABULAR_RL_POLICY_ID",
    ),
    "Policy": (
        "gridalyn.simulation.policies.contract",
        "Policy",
    ),
    "PolicyDescriptor": (
        "gridalyn.simulation.policies.contract",
        "PolicyDescriptor",
    ),
    "voltage_at_bus": (
        "gridalyn.simulation.policies.contract",
        "voltage_at_bus",
    ),
    "PolicyRegistration": (
        "gridalyn.simulation.policies.registry",
        "PolicyRegistration",
    ),
    "PolicyRegistry": (
        "gridalyn.simulation.policies.registry",
        "PolicyRegistry",
    ),
    "SensitivityDispatchPolicy": (
        "gridalyn.simulation.policies.registry",
        "SensitivityDispatchPolicy",
    ),
    "UnknownPolicyError": (
        "gridalyn.simulation.policies.registry",
        "UnknownPolicyError",
    ),
    "default_policy_registry": (
        "gridalyn.simulation.policies.registry",
        "default_policy_registry",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a policy symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.policies``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known policy symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.policies' has no attribute {name!r}"
    )

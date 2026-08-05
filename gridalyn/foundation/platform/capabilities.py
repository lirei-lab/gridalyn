"""Optional capability detection with actionable install guidance."""

from __future__ import annotations

import importlib.util


OPTIONAL_CAPABILITY_MODULES: dict[str, list[str]] = {
    "geo": ["geopandas", "osmnx", "shapely"],
    "sim": ["pandapower", "lightsim2grid"],
    # lightgbm is NOT here: it is a base dependency, because the packaged
    # macro weights are LightGBM models and a missing runtime silently
    # swaps the generator to a different macro model. Listing a base
    # dependency as an optional capability makes a check that can never
    # fail on a supported install.
    "ops": ["cvxpy"],
    "semantic": ["rdflib", "falkordb"],
    "dashboard": ["folium", "leafmap"],
}


class MissingCapabilityError(RuntimeError):
    """Raised when a command needs an optional extra that is not installed."""


def missing_capability_modules(capability: str) -> list[str]:
    """Return the modules of an optional capability that cannot be imported."""
    modules = OPTIONAL_CAPABILITY_MODULES.get(capability)
    if modules is None:
        known = ", ".join(sorted(OPTIONAL_CAPABILITY_MODULES))
        raise KeyError(f"unknown capability {capability!r} (known: {known})")
    return [name for name in modules if importlib.util.find_spec(name) is None]


def capability_install_hint(capability: str, missing: list[str], context: str = "") -> str:
    """Build the user-facing message for a missing optional capability."""
    subject = context or f"the '{capability}' capability"
    return (
        f"{subject} needs the '{capability}' extra "
        f"(missing modules: {', '.join(missing)}). "
        f'Install with: pip install "gridalyn[{capability}]" '
        "and inspect your installation with: gridalyn doctor"
    )


def require_capabilities(*capabilities: str, context: str = "") -> None:
    """Raise ``MissingCapabilityError`` when optional modules are unavailable."""
    for capability in capabilities:
        missing = missing_capability_modules(capability)
        if missing:
            raise MissingCapabilityError(
                capability_install_hint(capability, missing, context=context)
            )


__all__ = [
    "MissingCapabilityError",
    "OPTIONAL_CAPABILITY_MODULES",
    "capability_install_hint",
    "missing_capability_modules",
    "require_capabilities",
]

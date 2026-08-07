"""Optional capability detection with actionable install guidance.

A capability names the *truly-optional* modules an operation needs -- modules
absent from ``pyproject.toml`` ``[project] dependencies``. A base dependency
never belongs here: it is present on every supported install, so listing it
creates a check that can never fail. ``tests/test_capability_contract.py``
pins this rule against the pyproject dependency list.
"""

from __future__ import annotations

import importlib.util

OPTIONAL_CAPABILITY_MODULES: dict[str, list[str]] = {
    # A base dependency NEVER appears in this map: it is installed on every
    # supported environment, so requiring it makes a check that can never
    # fail -- an always-green gate that guards nothing. lightgbm was the
    # first removal for this reason (the packaged macro weights are LightGBM
    # models and a missing runtime silently swaps the generator to a
    # different macro model, so it became a base dependency). On 2026-08-06
    # six more base dependencies were removed for the same reason:
    # pandapower (sim), geopandas and shapely (geo), rdflib (semantic), and
    # folium and leafmap -- the last two emptied the 'dashboard' capability,
    # which was removed entirely, because an empty capability is itself an
    # always-green check. On 2026-08-07 the 'semantic' capability was removed
    # too: its only module (falkordb) had no functional consumer, and the
    # semantic build/validate commands are parquet-only, so the gate was a
    # spurious hard dependency on a graph database the pipeline never opens.
    "geo": ["osmnx"],
    "sim": ["lightsim2grid"],
    "ops": ["cvxpy"],
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


def capability_install_hint(
    capability: str, missing: list[str], context: str = ""
) -> str:
    """Build the user-facing message for a missing optional capability."""
    subject = context or f"the {capability!r} capability"
    return (
        f"{subject} needs the {capability!r} extra "
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

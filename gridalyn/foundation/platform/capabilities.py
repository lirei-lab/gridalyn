"""Optional capability detection with actionable install guidance.

A capability names the *truly-optional* modules an operation needs -- modules
absent from ``pyproject.toml`` ``[project] dependencies``. A base dependency
never belongs here: it is present on every supported install, so listing it
creates a check that can never fail. ``tests/test_capability_contract.py``
pins this rule against the pyproject dependency list.

Since Phase 15 the capability surface is *extensible*: an external package may
declare its own optional capabilities through the ``gridalyn.capabilities``
entry-point group, and :func:`require_capabilities` merges them additively with
the core :data:`OPTIONAL_CAPABILITY_MODULES`. External declarations may only
add NEW capability keys -- never redefine the core set, never an empty
capability (an always-green check).
"""

from __future__ import annotations

import importlib
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


#: Entry-point group through which external packages declare extra capabilities.
CAPABILITIES_ENTRY_POINT_GROUP = "gridalyn.capabilities"

#: Module attribute an external capability declaration must expose.
CAPABILITY_MODULES_ATTR = "CAPABILITY_MODULES"


def external_capability_modules(
    group: str = CAPABILITIES_ENTRY_POINT_GROUP,
    *,
    base_modules: frozenset[str] | None = None,
) -> dict[str, list[str]]:
    """Return optional-capability modules declared by installed extras.

    Reads the ``gridalyn.capabilities`` entry-point group (the
    ``[tool.gridalyn.capabilities]`` / entry-point declaration of an external
    package). Each entry-point module exposes ``CAPABILITY_MODULES`` — a dict
    shaped like :data:`OPTIONAL_CAPABILITY_MODULES`. External declarations are
    additive: they may only declare NEW capability keys, never redefine the
    core set, never an empty capability, and never a pyproject **base**
    dependency (an always-green check).

    Args:
        group: The entry-point group to read.
        base_modules: Optional set of module names that are base dependencies
            (present on every supported install); an external declaration
            naming one is rejected as an always-green check. The core map is
            policed the same way by the capability contract test; pass the
            pyproject-derived set here to apply the same rule externally.

    Returns:
        The externally-declared capability map, sorted by key.

    Raises:
        ValueError: If an entry-point module exposes no capability dict, an
            empty capability, a base-dependency module, or a key that
            collides with the core set.
    """
    from gridalyn.foundation.platform.extensions import list_entry_point_metadata

    base = base_modules or frozenset()
    external: dict[str, list[str]] = {}
    for record in list_entry_point_metadata(group):
        module = importlib.import_module(record.module)
        declared = getattr(module, CAPABILITY_MODULES_ATTR, None)
        if not isinstance(declared, dict) or not declared:
            raise ValueError(
                f"capability entry point {record.name!r} (module "
                f"{record.module!r}) must expose a non-empty "
                f"{CAPABILITY_MODULES_ATTR!r} dict shaped like "
                "OPTIONAL_CAPABILITY_MODULES; an empty capability is an "
                "always-green check"
            )
        for capability, modules in declared.items():
            if capability in OPTIONAL_CAPABILITY_MODULES:
                core_keys = ", ".join(sorted(OPTIONAL_CAPABILITY_MODULES))
                raise ValueError(
                    f"external capability {capability!r} from "
                    f"{record.name!r} collides with a core capability; an "
                    f"extra may only declare new capabilities, never redefine "
                    f"gridalyn's own (core keys: {core_keys})"
                )
            if not modules:
                raise ValueError(
                    f"external capability {capability!r} from {record.name!r} "
                    "is empty; an empty capability is an always-green check"
                )
            base_hits = sorted(name for name in modules if name.lower() in base)
            if base_hits:
                raise ValueError(
                    f"external capability {capability!r} from "
                    f"{record.name!r} names base-dependency module(s) "
                    f"{', '.join(base_hits)}; a base dependency is present on "
                    "every supported install, so requiring it is an "
                    "always-green check (name a truly-optional module instead)"
                )
            external[capability] = list(modules)
    return dict(sorted(external.items()))


def require_extension_capabilities(extension_id: str, group: str) -> None:
    """Raise when a resolved extension declares capabilities its env lacks.

    The shared readiness gate for the ``entry_point`` source: after an
    extension module is loaded, callers (the CLI ``validate`` path and the
    programmatic ``resolve_declared_extensions`` path) call this so a
    registered-but-not-ready extension is surfaced as
    :class:`MissingCapabilityError` — never silently accepted. The engine
    itself cannot do this (it is stdlib-only); this helper lives at the
    capability layer, which both callers reach.

    Args:
        extension_id: The resolved extension ID.
        group: The entry-point group it came from.

    Raises:
        MissingCapabilityError: If the extension declares a
            ``REQUIRED_CAPABILITIES`` capability whose optional modules are
            not importable.
    """
    from gridalyn.foundation.platform.extensions import (
        REQUIRED_CAPABILITIES_ATTR,
        list_entry_point_metadata,
    )

    for record in list_entry_point_metadata(group):
        if record.name != extension_id:
            continue
        module = importlib.import_module(record.module)
        required = getattr(module, REQUIRED_CAPABILITIES_ATTR, ())
        if required:
            require_capabilities(*required, context=f"extension {extension_id!r}")
        return


def _modules_for(capability: str) -> list[str]:
    """Resolve a capability's modules, core first then external declarations."""
    if capability in OPTIONAL_CAPABILITY_MODULES:
        return OPTIONAL_CAPABILITY_MODULES[capability]
    external = external_capability_modules()
    modules = external.get(capability)
    if modules is None:
        known = ", ".join(sorted(set(OPTIONAL_CAPABILITY_MODULES) | set(external)))
        raise KeyError(f"unknown capability {capability!r} (known: {known})")
    return modules


def missing_capability_modules(capability: str) -> list[str]:
    """Return the modules of an optional capability that cannot be imported."""
    modules = _modules_for(capability)
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
    "CAPABILITIES_ENTRY_POINT_GROUP",
    "CAPABILITY_MODULES_ATTR",
    "MissingCapabilityError",
    "OPTIONAL_CAPABILITY_MODULES",
    "capability_install_hint",
    "external_capability_modules",
    "missing_capability_modules",
    "require_capabilities",
    "require_extension_capabilities",
]

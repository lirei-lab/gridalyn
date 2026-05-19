"""Compatibility aliases for historical Gridalyn import paths."""

from __future__ import annotations

from importlib import import_module
import sys


COMPAT_MODULE_ALIASES = {
    "gridalyn.adapters": "gridalyn.twin.adapters",
    "gridalyn.analytics": "gridalyn.simulation.analytics",
    "gridalyn.interfaces.cli": "gridalyn.interfaces.cli",
    "gridalyn.core": "gridalyn.twin.core",
    "gridalyn.data": "gridalyn.foundation.data",
    "gridalyn.datagen": "gridalyn.assets.datagen",
    "gridalyn.db": "gridalyn.twin.db",
    "gridalyn.geoprocess": "gridalyn.twin.geoprocess",
    "gridalyn.io": "gridalyn.twin.io",
    "gridalyn.market": "gridalyn.operations.market",
    "gridalyn.modeling": "gridalyn.assets.modeling",
    "gridalyn.network": "gridalyn.twin.network",
    "gridalyn.platform": "gridalyn.foundation.platform",
    "gridalyn.reporting": "gridalyn.interfaces.reporting",
    "gridalyn.semantic": "gridalyn.twin.semantic",
    "gridalyn.simulators": "gridalyn.simulation.simulators",
    "gridalyn.viz": "gridalyn.interfaces.viz",
    "gridalyn.workflows": "gridalyn.projects.workflows",
}

COMPAT_SUBMODULE_ALIASES = {
    "gridalyn.adapters.network": "gridalyn.twin.adapters.network",
    "gridalyn.adapters.registry": "gridalyn.twin.adapters.registry",
    "gridalyn.core.graph": "gridalyn.twin.core.graph",
    "gridalyn.core.ontology": "gridalyn.twin.core.ontology",
    "gridalyn.core.topology": "gridalyn.twin.core.topology",
    "gridalyn.modeling.artifacts": "gridalyn.assets.modeling.artifacts",
}


def register_compat_module_aliases(root_module_name: str = "gridalyn") -> None:
    """Expose historical module paths while the physical tree is reorganized."""

    root_module = sys.modules[root_module_name]
    for public_name, target_name in COMPAT_MODULE_ALIASES.items():
        if public_name not in sys.modules:
            sys.modules[public_name] = import_module(target_name)
        attr_name = public_name.removeprefix(f"{root_module_name}.")
        if "." not in attr_name:
            setattr(root_module, attr_name, sys.modules[public_name])

    for public_name, target_name in COMPAT_SUBMODULE_ALIASES.items():
        if public_name not in sys.modules:
            sys.modules[public_name] = import_module(target_name)


__all__ = [
    "COMPAT_MODULE_ALIASES",
    "COMPAT_SUBMODULE_ALIASES",
    "register_compat_module_aliases",
]

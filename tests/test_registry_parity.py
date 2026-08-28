"""Gate: the three component registries expose the same contract.

Why this exists
---------------
``backends``, ``surrogates`` and ``policies`` are the platform's three
explicit-ID registries, and they are meant to be the same mechanism applied to
three roles. They were not. Measured 2026-08-28:

    method                  backends  surrogates  policies
    create                     yes       yes        yes
    register                   yes       yes        yes
    get_descriptor             yes       yes        yes
    list_descriptors           yes       yes        yes
    registration_source        YES        no         no
    registration_version       YES        no         no

That asymmetry was load-bearing rather than cosmetic.
``gridalyn.projects.developer.bind_project_components`` wires two of the four
declared roles; its docstring names the missing ``registration_source``
discriminator -- which tells a project-registered component from a core one --
as the concrete prerequisite for the other two, because ``consume()`` cannot
answer honestly for a role it cannot attribute. Two methods absent from two
files kept half the developer API declared-but-unwired.

A divergence of this kind accumulates silently: each registry reads fine on its
own, and only a side-by-side comparison shows the gap. This module is that
comparison, run on every push.
"""

from __future__ import annotations

import inspect
import unittest

from gridalyn.simulation.backends.registry import (
    PowerFlowBackendRegistry,
    default_powerflow_backend_registry,
)
from gridalyn.simulation.policies.registry import (
    PolicyRegistry,
    default_policy_registry,
)
from gridalyn.simulation.surrogates.registry import (
    SurrogateRegistry,
    default_surrogate_registry,
)

#: The three registries, with the id-attribute their descriptors carry.
_REGISTRIES = (
    (
        "backends",
        PowerFlowBackendRegistry,
        default_powerflow_backend_registry,
        "backend_id",
    ),
    ("surrogates", SurrogateRegistry, default_surrogate_registry, "surrogate_id"),
    ("policies", PolicyRegistry, default_policy_registry, "policy_id"),
)

#: Methods every registry must expose. Named rather than derived from one of
#: them, so shrinking a registry cannot shrink the expectation with it.
_REQUIRED_METHODS = frozenset(
    {
        "create",
        "get_descriptor",
        "list_descriptors",
        "register",
        "registration_source",
        "registration_version",
    }
)


def _unused_factory(*args: object, **kwargs: object) -> object:
    """Stand-in factory. Registration records a factory; it never calls one."""
    raise AssertionError("registration must not invoke the factory")


def _borrow_descriptor(registry: object) -> object:
    """Return a real descriptor from a default registry, without mutating it.

    The defaults are process-wide singletons, so a test must never register
    into one. Borrowing a genuine descriptor keeps the mutation tests
    exercising the real contract -- including its contract-version check --
    without touching shared state.

    The descriptor alone is enough: registration records a factory, it does not
    call it, and the policy factories require constructor arguments a parity
    test has no business inventing.
    """
    return registry.list_descriptors()[0]


def _public_methods(cls: type) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


class RegistryParityTests(unittest.TestCase):
    def test_every_registry_exposes_the_required_contract(self) -> None:
        for name, cls, _, _ in _REGISTRIES:
            with self.subTest(registry=name):
                missing = sorted(_REQUIRED_METHODS - _public_methods(cls))
                self.assertEqual(
                    [],
                    missing,
                    f"{name} registry is missing {missing}; the three registries "
                    "are one mechanism applied to three roles and must not "
                    "diverge",
                )

    def test_no_registry_carries_a_method_the_others_lack(self) -> None:
        """Parity in both directions.

        A method added to one registry and not the others is how the
        ``registration_source`` gap opened in the first place.
        """
        apis = {name: _public_methods(cls) for name, cls, _, _ in _REGISTRIES}
        shared = set.intersection(*apis.values())
        for name, api in apis.items():
            with self.subTest(registry=name):
                extra = sorted(api - shared)
                self.assertEqual(
                    [],
                    extra,
                    f"{name} exposes {extra}, which the other registries do "
                    "not. Add it to them, or move it off the registry class.",
                )

    def test_shipped_registrations_report_core(self) -> None:
        """The discriminator must actually discriminate, not default blindly."""
        for name, _, factory, id_attr in _REGISTRIES:
            with self.subTest(registry=name):
                registry = factory()
                descriptors = registry.list_descriptors()
                self.assertTrue(descriptors, f"{name} ships no default registration")
                for descriptor in descriptors:
                    component_id = getattr(descriptor, id_attr)
                    self.assertEqual(
                        "core",
                        registry.registration_source(component_id),
                        f"{name}:{component_id} is shipped but does not report "
                        "'core'",
                    )
                    self.assertIsNone(
                        registry.registration_version(component_id),
                        f"{name}:{component_id} is shipped but records a "
                        "version; only extensions declare one",
                    )

    def test_an_unknown_source_is_rejected_by_every_registry(self) -> None:
        """A typo'd source must not brand a core component as an extension.

        The governed manifest reads this value, so accepting an unrecognised
        one would put an unverifiable claim into provenance.
        """
        for name, cls, factory, _id_attr in _REGISTRIES:
            with self.subTest(registry=name):
                descriptor = _borrow_descriptor(factory())
                registry = cls()
                with self.assertRaises(ValueError) as caught:
                    registry.register(
                        _unused_factory,
                        descriptor=descriptor,
                        source="hsot",  # deliberate typo of "host"
                    )
                message = str(caught.exception)
                self.assertIn("hsot", message)
                self.assertIn("core", message)

    def test_a_host_registration_is_reported_as_host(self) -> None:
        for name, cls, factory, id_attr in _REGISTRIES:
            with self.subTest(registry=name):
                descriptor = _borrow_descriptor(factory())
                registry = cls()
                registry.register(
                    _unused_factory,
                    descriptor=descriptor,
                    source="host",
                    version="2.1.0",
                )
                component_id = getattr(descriptor, id_attr)
                self.assertEqual("host", registry.registration_source(component_id))
                self.assertEqual("2.1.0", registry.registration_version(component_id))

    def test_the_default_registries_are_process_wide_singletons(self) -> None:
        """Pinned because it dictates how everything else here is written.

        ``default_*_registry()`` returns the same object every call, so a test
        that registers into it mutates the shipped registry for every test that
        runs afterwards. The mutation tests above therefore build a fresh
        registry and only BORROW a descriptor from the default. Discovered the
        hard way: an earlier draft registered into the singleton and made a
        later assertion about the shipped backends fail, in a way that looked
        like a defect in the registry rather than in the test.
        """
        for name, _, factory, _ in _REGISTRIES:
            with self.subTest(registry=name):
                self.assertIs(factory(), factory())


if __name__ == "__main__":
    unittest.main()

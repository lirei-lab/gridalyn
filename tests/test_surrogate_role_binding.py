"""The surrogate role's declaration -> resolution -> provenance contract.

The platform shipped four per-role registries but wired only one of them into
the project path: measured 2026-08-18, ``PowerFlowBackendRegistry`` had six
production consumers while ``SurrogateRegistry``, ``PolicyRegistry`` and
``ObservationProducerRegistry`` had none outside their own packages. The cause
was not discipline but surface: ``spec.simulation.powerflowBackend`` gave a
study somewhere to declare a backend, and nothing gave it somewhere to declare
a surrogate, so ``clearing_method == "surrogate"`` stayed a string literal
(``operations/clearing/selection.py``) rather than a resolved component.

This module pins the surrogate half of that contract, mirroring the backend's
own gates:

* declaring nothing resolves the registry default, so an undeclared study's
  behaviour is unchanged (the property that makes this change baseline-safe);
* declaring an ID resolves exactly that surrogate;
* declaring an unregistered ID is a located error naming what IS registered,
  never a silent fallback to the default -- a silent downgrade would change
  predicted values while leaving every governed artifact identical;
* provenance records which surrogate answered AND its stated error bound,
  because naming a surrogate without its accuracy invites the reader to assume
  there is none.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from gridalyn.projects.loader import load_project
from gridalyn.projects.model_inputs import load_surrogate_id
from gridalyn.projects.runner import _surrogate_provenance
from gridalyn.simulation.surrogates.registry import (
    DEFAULT_SURROGATE_ID,
    default_surrogate_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNDECLARED = _REPO_ROOT / "projects" / "minimal_grid_project" / "project.yaml"
_DECLARED = _REPO_ROOT / "projects" / "ev_hosting_flex" / "project.yaml"


class SurrogateRoleBindingTests(unittest.TestCase):
    """Declaration, resolution and provenance for the surrogate role."""

    def test_undeclared_study_resolves_the_registry_default(self) -> None:
        """A study that declares nothing keeps today's behaviour exactly."""
        self.assertEqual(DEFAULT_SURROGATE_ID, load_surrogate_id(_UNDECLARED))

    def test_declared_study_resolves_what_it_declared(self) -> None:
        """The flagship declares its surrogate; resolution honours it."""
        self.assertEqual("network_impact_tabular_v1", load_surrogate_id(_DECLARED))

    def test_unregistered_id_is_a_located_error(self) -> None:
        """Naming a surrogate the repo does not register fails loudly."""
        project = load_project(_UNDECLARED)
        project.raw["spec"]["simulation"]["surrogate"] = "no_such_surrogate_v9"
        with self.assertRaises(ValueError) as caught:
            load_surrogate_id(project)
        message = str(caught.exception)
        self.assertIn("no_such_surrogate_v9", message)
        self.assertIn("registered:", message)
        self.assertIn(DEFAULT_SURROGATE_ID, message)

    def test_empty_declaration_is_a_located_error(self) -> None:
        """An empty string is a malformed declaration, not 'declares none'."""
        project = load_project(_UNDECLARED)
        project.raw["spec"]["simulation"]["surrogate"] = "   "
        with self.assertRaises(ValueError) as caught:
            load_surrogate_id(project)
        self.assertIn("non-empty string", str(caught.exception))

    def test_provenance_records_the_id_and_its_error_bound(self) -> None:
        """A run records which surrogate answered and how accurate it is."""
        provenance = _surrogate_provenance(load_project(_DECLARED))
        self.assertEqual("network_impact_tabular_v1", provenance["surrogate_id"])
        self.assertEqual("spec.simulation.surrogate", provenance["declared_source"])
        bound = provenance["error_bound"]
        self.assertIsNotNone(bound, "a registered surrogate states an error bound")
        self.assertIn("value", bound)
        self.assertIn("method", bound)

    def test_provenance_distinguishes_declared_from_inherited(self) -> None:
        """Naming the default explicitly is distinguishable from naming nothing."""
        inherited = _surrogate_provenance(load_project(_UNDECLARED))
        self.assertEqual(
            "registry default (study declares none)", inherited["declared_source"]
        )
        self.assertEqual(DEFAULT_SURROGATE_ID, inherited["surrogate_id"])

    def test_provenance_lists_every_registered_surrogate(self) -> None:
        """Registered IDs come from the registry, not a hardcoded list."""
        provenance = _surrogate_provenance(load_project(_UNDECLARED))
        expected = sorted(
            descriptor.surrogate_id
            for descriptor in default_surrogate_registry().list_descriptors()
        )
        self.assertEqual(expected, provenance["registered"])

    def test_bind_project_components_exposes_the_resolved_surrogate(self) -> None:
        """The bind resolves the role, so a stage consumes rather than imports."""
        from gridalyn.projects.developer import bind_project_components
        from gridalyn.projects.scripting import project_script

        script = project_script(root=_UNDECLARED.parent)
        components = bind_project_components(script)
        self.assertIsNotNone(components.surrogate)
        self.assertEqual(DEFAULT_SURROGATE_ID, components.to_dict()["surrogate_id"])

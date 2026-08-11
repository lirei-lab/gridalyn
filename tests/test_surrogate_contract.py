"""Gate for the surrogate contract and its stated error bounds (plan 10-02).

``docs/platform/platform-layer-model.md`` (layer 4) allows market logic to use
fast estimates only when the estimate has a *known* error. Before this phase no
surrogate stated one: ``physics_model.py`` matched ``mae|rmse|error|tolerance``
zero times. This file pins the five properties that make the rule enforceable
rather than aspirational:

(a) every registered surrogate satisfies the contract and carries a *measured*
    bound whose value re-derives from its own ``verify``;
(b) registering a descriptor without an error bound raises a located error;
(c) an unknown ID raises a located error enumerating the available IDs;
(d) importing the package leaks no truly-optional dependency;
(e) resolution is by explicit ID only -- no ``entry_points`` discovery, and an
    unregistered surrogate is not resolvable.

Why (d) runs in a subprocess
----------------------------
An in-process assertion on ``sys.modules`` is worthless: pytest has already
imported half the tree in the same interpreter, so the assertion would pass or
fail for reasons unrelated to this package. Subprocess isolation is mandatory
for a correct verdict -- the same reasoning ``tests/test_import_hygiene.py``
documents.

Why (e) is an AST walk and not a grep
-------------------------------------
A grep for ``entry_points`` matches the module docstring that explains why
discovery is absent, so it can never go red. The walk looks for a *call*,
which the prose cannot fake.

The stated bounds themselves are re-derived by
``StatedErrorBoundsAreReproducibleTest``, which skips when the physics labels
are absent: they live under ``instances/`` and are gitignored
(``.gitignore:186``), so CI never sees them. That skip is disclosed on the
bound's own ``method`` string rather than hidden here.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.simulation.analytics.network_impact.physics_model import (
    NETWORK_IMPACT_PHYSICS_SURROGATE_ID,
    PHYSICS_SURROGATE_ERROR_BOUND,
    NetworkImpactPhysicsLookupSurrogate,
    measure_physics_surrogate_error_bound,
)
from gridalyn.simulation.analytics.network_impact.surrogate import (
    NETWORK_IMPACT_TABULAR_SURROGATE_ID,
    TABULAR_SURROGATE_ERROR_BOUND,
    NetworkImpactTabularSurrogate,
    build_training_dataset,
)
from gridalyn.simulation.surrogates import contract as contract_module
from gridalyn.simulation.surrogates import registry as registry_module
from gridalyn.simulation.surrogates.contract import (
    MEASURED,
    UNMEASURED,
    ErrorBound,
    Surrogate,
    SurrogateDescriptor,
    measure_relief_error_bound,
    unmeasured_error_bound,
)
from gridalyn.simulation.surrogates.registry import (
    DEFAULT_SURROGATE_ID,
    SurrogateRegistry,
    UnboundedSurrogateError,
    UnknownSurrogateError,
    default_surrogate_registry,
    registered_error_bounds,
    resolve_surrogate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the finite-difference labels the stated bounds were measured on live.
#: Gitignored, so absent from a clean checkout and from CI.
PHYSICS_LABELS = (
    REPO_ROOT
    / "instances/default/digital_twin/flexibility"
    / "network_impact_physics_labels.parquet"
)
PROVIDER_REGISTRY = (
    REPO_ROOT
    / "instances/default/digital_twin/flexibility"
    / "provider_registry.parquet"
)
NETWORK_SENSITIVITY = (
    REPO_ROOT
    / "instances/default/digital_twin/flexibility"
    / "network_sensitivity.parquet"
)

#: Tolerance for re-deriving a bound stated to six decimal places.
_ROUNDING_TOLERANCE = 5e-7

_LEAK_PROBE = """\
import json
import sys

import gridalyn.simulation.surrogates

optional = ["cvxpy", "lightsim2grid", "osmnx"]
print(json.dumps(sorted(set(optional) & set(sys.modules))))
"""


def _toy_labels() -> pd.DataFrame:
    """Return a two-row physics-label frame with a known relief.

    Returns:
        Labels whose ``relief_pct_per_kw`` is 0.5 for both rows, so a
        prediction of 1.0 has an exactly-known mean absolute error of 0.5.
    """
    return pd.DataFrame(
        [
            {
                "provider_id": "provider:A",
                "scenario_id": "S4",
                "constraint_id": "transformer:1",
                "actual_perturbation_kw": 2.0,
                "relief_pct_per_kw": 0.5,
            },
            {
                "provider_id": "provider:A",
                "scenario_id": "S4",
                "constraint_id": "transformer:1",
                "actual_perturbation_kw": 4.0,
                "relief_pct_per_kw": 0.5,
            },
        ]
    )


def _toy_predictions(delta_loading: float = -1.0) -> pd.DataFrame:
    """Return a one-row prediction frame matching :func:`_toy_labels`.

    Args:
        delta_loading: Signed loading change per kW; its negation is the
            predicted relief.

    Returns:
        A prediction frame joinable to the toy labels.
    """
    return pd.DataFrame(
        [
            {
                "provider_id": "provider:A",
                "scenario_id": "S4",
                "constraint_id": "transformer:1",
                "predicted_delta_loading_pct_per_kw": delta_loading,
            }
        ]
    )


class _UnboundedSurrogate:
    """A surrogate whose descriptor deliberately states no error bound."""

    DESCRIPTOR = SurrogateDescriptor(
        surrogate_id="unbounded_probe",
        name="Probe with no stated accuracy",
        physical_model="pandapower AC power flow",
    )

    @property
    def descriptor(self) -> SurrogateDescriptor:
        """Return the bound-less descriptor.

        Returns:
            The class-level descriptor.
        """
        return self.DESCRIPTOR


class RegisteredSurrogatesSatisfyContractTest(unittest.TestCase):
    """(a) Every registered surrogate is contract-shaped and bounded."""

    def test_registry_is_not_empty_and_is_sorted_by_id(self) -> None:
        registry = default_surrogate_registry()
        ids = [descriptor.surrogate_id for descriptor in registry.list_descriptors()]

        self.assertEqual(
            [
                NETWORK_IMPACT_PHYSICS_SURROGATE_ID,
                NETWORK_IMPACT_TABULAR_SURROGATE_ID,
            ],
            ids,
        )
        self.assertEqual(sorted(ids), ids)
        self.assertEqual(NETWORK_IMPACT_TABULAR_SURROGATE_ID, DEFAULT_SURROGATE_ID)

    def test_every_registered_surrogate_satisfies_the_protocol(self) -> None:
        registry = default_surrogate_registry()
        for descriptor in registry.list_descriptors():
            with self.subTest(surrogate_id=descriptor.surrogate_id):
                surrogate = registry.create(descriptor.surrogate_id)
                self.assertIsInstance(surrogate, Surrogate)
                for method in ("fit", "predict", "verify"):
                    self.assertTrue(
                        callable(getattr(surrogate, method, None)),
                        f"{descriptor.surrogate_id} has no callable {method}",
                    )
                self.assertEqual(descriptor, surrogate.descriptor)

    def test_every_registered_surrogate_states_a_measured_error_bound(self) -> None:
        for descriptor in default_surrogate_registry().list_descriptors():
            with self.subTest(surrogate_id=descriptor.surrogate_id):
                bound = descriptor.error_bound
                self.assertIsNotNone(bound)
                assert bound is not None  # narrows for mypy
                self.assertEqual(MEASURED, bound.status)
                self.assertIsNotNone(bound.value)
                self.assertGreater(bound.sample_size, 0)
                self.assertTrue(bound.method.strip())
                self.assertTrue(bound.reference.strip())
                self.assertTrue(bound.units.strip())

    def test_descriptor_is_read_only_so_a_stated_bound_cannot_be_rebound(self) -> None:
        descriptor = default_surrogate_registry().get_descriptor(DEFAULT_SURROGATE_ID)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            descriptor.error_bound = None  # type: ignore[misc]

    def test_registered_error_bounds_are_json_native(self) -> None:
        payload = registered_error_bounds()
        self.assertEqual(
            {
                NETWORK_IMPACT_PHYSICS_SURROGATE_ID,
                NETWORK_IMPACT_TABULAR_SURROGATE_ID,
            },
            set(payload),
        )
        # Round-trips without a custom encoder, so it can be embedded in a
        # governed verification report as-is.
        self.assertEqual(payload, json.loads(json.dumps(payload)))


class ErrorBoundHonestyTest(unittest.TestCase):
    """(b, part 1) A bound cannot state more, or less, than was measured."""

    def test_measured_bound_without_a_value_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ErrorBound(
                metric="mae",
                units="pct_per_kw",
                value=None,
                sample_size=10,
                method="held out",
                reference="pandapower",
            )
        self.assertIn("state a finite measured number", str(caught.exception))

    def test_measured_bound_over_no_samples_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ErrorBound(
                metric="mae",
                units="pct_per_kw",
                value=0.1,
                sample_size=0,
                method="held out",
                reference="pandapower",
            )
        self.assertIn("not a measurement", str(caught.exception))

    def test_measured_bound_without_a_method_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ErrorBound(
                metric="mae",
                units="pct_per_kw",
                value=0.1,
                sample_size=10,
                method="   ",
                reference="pandapower",
            )
        self.assertIn("record the evaluation protocol", str(caught.exception))

    def test_unmeasured_bound_carrying_a_number_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ErrorBound(
                metric="mae",
                units="pct_per_kw",
                value=0.1,
                sample_size=0,
                method="",
                reference="pandapower",
                status=UNMEASURED,
                reason="labels absent",
            )
        self.assertIn("must state no number at all", str(caught.exception))

    def test_unmeasured_bound_without_a_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            unmeasured_error_bound(
                metric="mae",
                units="pct_per_kw",
                reference="pandapower",
                reason="",
            )
        self.assertIn("name what is missing and where", str(caught.exception))

    def test_unknown_status_enumerates_the_known_ones(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ErrorBound(
                metric="mae",
                units="pct_per_kw",
                value=0.1,
                sample_size=1,
                method="x",
                reference="pandapower",
                status="approximately",  # type: ignore[arg-type]
            )
        message = str(caught.exception)
        self.assertIn(MEASURED, message)
        self.assertIn(UNMEASURED, message)

    def test_measurement_uses_the_schema_sign_convention(self) -> None:
        bound = measure_relief_error_bound(
            _toy_predictions(delta_loading=-1.0),
            _toy_labels(),
            reference="pandapower",
            method="toy",
        )
        # Predicted relief is -(-1.0) = 1.0 against a label of 0.5.
        self.assertEqual(MEASURED, bound.status)
        self.assertAlmostEqual(0.5, float(bound.value or 0.0))
        self.assertEqual(2, bound.sample_size)

    def test_zero_perturbation_labels_are_excluded_from_the_sample(self) -> None:
        labels = _toy_labels()
        labels.loc[1, "actual_perturbation_kw"] = 0.0
        bound = measure_relief_error_bound(
            _toy_predictions(),
            labels,
            reference="pandapower",
            method="toy",
        )
        self.assertEqual(1, bound.sample_size)

    def test_empty_overlap_is_unmeasured_not_an_accuracy_of_zero(self) -> None:
        labels = _toy_labels()
        labels["actual_perturbation_kw"] = 0.0
        bound = measure_relief_error_bound(
            _toy_predictions(),
            labels,
            reference="pandapower",
            method="toy",
        )
        self.assertEqual(UNMEASURED, bound.status)
        self.assertIsNone(bound.value)
        self.assertIn("perturbation_sampler", bound.reason or "")


class UnboundedRegistrationIsRefusedTest(unittest.TestCase):
    """(b) A surrogate with no stated accuracy cannot enter the registry."""

    def test_registering_without_an_error_bound_raises_a_located_error(self) -> None:
        registry = SurrogateRegistry()
        with self.assertRaises(UnboundedSurrogateError) as caught:
            registry.register(_UnboundedSurrogate)
        message = str(caught.exception)
        self.assertIn("unbounded_probe", message)
        self.assertIn("declares no error bound", message)
        self.assertIn("unmeasured_error_bound", message)
        self.assertEqual([], registry.list_descriptors())

    def test_an_unmeasured_bound_is_accepted_because_it_is_honest(self) -> None:
        registry = SurrogateRegistry()
        descriptor = SurrogateDescriptor(
            surrogate_id="unmeasured_probe",
            name="Probe with a disclosed gap",
            physical_model="pandapower AC power flow",
            error_bound=unmeasured_error_bound(
                metric="mae_relief_pct_per_kw",
                units="transformer_loading_pct_point_per_kw",
                reference="pandapower",
                reason="labels absent on a clean checkout",
            ),
        )
        registry.register(_UnboundedSurrogate, descriptor=descriptor)
        registered = registry.get_descriptor("unmeasured_probe").error_bound
        assert registered is not None  # narrows for mypy
        self.assertEqual(UNMEASURED, registered.status)

    def test_duplicate_registration_needs_replace(self) -> None:
        registry = default_surrogate_registry()
        with self.assertRaises(ValueError) as caught:
            registry.register(NetworkImpactTabularSurrogate)
        self.assertIn("replace=True", str(caught.exception))
        registry.register(NetworkImpactTabularSurrogate, replace=True)


class UnknownIdIsLocatedTest(unittest.TestCase):
    """(c) An unknown ID enumerates what is available."""

    def test_unknown_id_enumerates_available_ids(self) -> None:
        with self.assertRaises(UnknownSurrogateError) as caught:
            resolve_surrogate("gnn_v2")
        message = str(caught.exception)
        self.assertIn("gnn_v2", message)
        self.assertIn(NETWORK_IMPACT_TABULAR_SURROGATE_ID, message)
        self.assertIn(NETWORK_IMPACT_PHYSICS_SURROGATE_ID, message)
        self.assertIn("explicit ID only", message)

    def test_unknown_id_on_an_empty_registry_says_so(self) -> None:
        with self.assertRaises(UnknownSurrogateError) as caught:
            SurrogateRegistry().create("anything")
        self.assertIn("none registered", str(caught.exception))

    def test_get_descriptor_is_located_too(self) -> None:
        with self.assertRaises(UnknownSurrogateError):
            default_surrogate_registry().get_descriptor("gnn_v2")

    def test_default_registry_is_fresh_per_call(self) -> None:
        first = default_surrogate_registry()
        first.register(
            _UnboundedSurrogate,
            descriptor=SurrogateDescriptor(
                surrogate_id="leak_probe",
                name="probe",
                physical_model="pandapower",
                error_bound=TABULAR_SURROGATE_ERROR_BOUND,
            ),
        )
        second_ids = [
            d.surrogate_id for d in default_surrogate_registry().list_descriptors()
        ]
        self.assertNotIn("leak_probe", second_ids)


class ImportHygieneTest(unittest.TestCase):
    """(d) Importing the package pulls no truly-optional dependency."""

    def test_importing_the_package_leaks_no_optional_dependency(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", _LEAK_PROBE],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=120,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            f"probe failed: {completed.stderr.strip()[-2000:]}",
        )
        self.assertEqual([], json.loads(completed.stdout))


class ExplicitIdResolutionOnlyTest(unittest.TestCase):
    """(e) There is no discovery mechanism anywhere in the package."""

    def _package_sources(self) -> dict[str, str]:
        package = REPO_ROOT / "gridalyn/simulation/surrogates"
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(package.glob("*.py"))
        }

    def test_no_entry_points_call_anywhere_in_the_package(self) -> None:
        # An AST walk, not a grep: the module docstrings explain *why*
        # discovery is absent, and a grep would match that prose forever.
        offenders: list[str] = []
        for name, source in self._package_sources().items():
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "entry_points":
                    offenders.append(f"{name}:{node.lineno} entry_points() call")
                elif isinstance(func, ast.Name) and func.id == "entry_points":
                    offenders.append(f"{name}:{node.lineno} entry_points() call")
        self.assertEqual([], offenders)

    def test_no_discovery_module_is_imported(self) -> None:
        forbidden = {"importlib.metadata", "pkg_resources", "entrypoints"}
        offenders: list[str] = []
        for name, source in self._package_sources().items():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    offenders.extend(
                        f"{name}:{node.lineno} import {alias.name}"
                        for alias in node.names
                        if alias.name in forbidden
                    )
                elif isinstance(node, ast.ImportFrom) and node.module in forbidden:
                    offenders.append(f"{name}:{node.lineno} from {node.module}")
        self.assertEqual([], offenders)

    def test_an_unregistered_surrogate_is_not_resolvable(self) -> None:
        # The class is importable and contract-shaped, yet resolving it by ID
        # fails: nothing scans the module namespace.
        self.assertIsInstance(NetworkImpactPhysicsLookupSurrogate(), Surrogate)
        with self.assertRaises(UnknownSurrogateError):
            SurrogateRegistry().create(NETWORK_IMPACT_PHYSICS_SURROGATE_ID)


class OutputIdentityTest(unittest.TestCase):
    """The contract adapts the existing triple; it does not replace it."""

    def setUp(self) -> None:
        self.providers = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "constraint_zone_id": "transformer:64",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                }
            ]
        )
        self.sensitivity = pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:1:soft_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:64",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 1.0,
                    "available_relief_kw": 6.5,
                }
            ]
        )

    def test_tabular_predict_matches_the_pre_contract_function(self) -> None:
        from gridalyn.simulation.analytics.network_impact.surrogate import (
            build_provider_impact_predictions,
        )

        training = build_training_dataset(
            self.providers, self.sensitivity, scenario_id="S4"
        )
        surrogate = resolve_surrogate(NETWORK_IMPACT_TABULAR_SURROGATE_ID)
        pd.testing.assert_frame_equal(
            build_provider_impact_predictions(training),
            surrogate.predict(training, surrogate.fit(training)),
            check_exact=True,
        )

    def test_physics_surrogate_names_its_missing_labels(self) -> None:
        surrogate = resolve_surrogate(NETWORK_IMPACT_PHYSICS_SURROGATE_ID)
        training = build_training_dataset(
            self.providers, self.sensitivity, scenario_id="S4"
        )
        with self.assertRaises(ValueError) as caught:
            surrogate.fit(training)
        self.assertIn("perturbation_sampler", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            surrogate.predict(training)
        self.assertIn("fit(training, labels)", str(caught.exception))

    def test_single_group_hold_out_is_unmeasured_not_optimistic(self) -> None:
        labels = _toy_labels()
        labels["timestep"] = 0
        bound = measure_physics_surrogate_error_bound(pd.DataFrame(), labels)
        self.assertEqual(UNMEASURED, bound.status)
        self.assertIn("at least", bound.reason or "")


@unittest.skipUnless(
    PHYSICS_LABELS.exists()
    and PROVIDER_REGISTRY.exists()
    and NETWORK_SENSITIVITY.exists(),
    f"physics labels absent (gitignored): {PHYSICS_LABELS}",
)
class StatedErrorBoundsAreReproducibleTest(unittest.TestCase):
    """The stated numbers re-derive from the dataset their method names.

    Skipped in CI by construction -- the labels are gitignored -- which is
    exactly why the skip reason names the path rather than passing silently.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.labels = pd.read_parquet(PHYSICS_LABELS)
        cls.training = build_training_dataset(
            pd.read_parquet(PROVIDER_REGISTRY),
            pd.read_parquet(NETWORK_SENSITIVITY),
            scenario_id="S4",
        )

    def test_tabular_bound_re_derives(self) -> None:
        surrogate = resolve_surrogate(NETWORK_IMPACT_TABULAR_SURROGATE_ID)
        predictions = surrogate.predict(self.training, surrogate.fit(self.training))
        measured = surrogate.verify(predictions, self.labels)
        stated = TABULAR_SURROGATE_ERROR_BOUND
        self.assertEqual(stated.sample_size, measured.sample_size)
        self.assertAlmostEqual(
            float(stated.value or 0.0),
            float(measured.value or 0.0),
            delta=_ROUNDING_TOLERANCE,
        )

    def test_physics_bound_re_derives_out_of_sample(self) -> None:
        measured = measure_physics_surrogate_error_bound(self.training, self.labels)
        stated = PHYSICS_SURROGATE_ERROR_BOUND
        self.assertEqual(stated.sample_size, measured.sample_size)
        self.assertAlmostEqual(
            float(stated.value or 0.0),
            float(measured.value or 0.0),
            delta=_ROUNDING_TOLERANCE,
        )

    def test_the_topology_surrogate_is_the_looser_of_the_two(self) -> None:
        # The whole point of stating bounds: the default surrogate is two
        # orders of magnitude looser than the physics-fitted one, and that is
        # now a checkable fact rather than a footnote.
        self.assertGreater(
            float(TABULAR_SURROGATE_ERROR_BOUND.value or 0.0),
            100 * float(PHYSICS_SURROGATE_ERROR_BOUND.value or 0.0),
        )


class VerificationReportCarriesBoundsTest(unittest.TestCase):
    """The verification report can state the accuracy it screened with."""

    def _case_metrics(self) -> dict[str, dict[str, Any]]:
        base = {
            "trafo_max_loading_percent": 110.0,
            "line_max_loading_percent": 80.0,
            "v_min_pu": 0.95,
            "ext_grid_peak_mw": 1.0,
            "n_trafo_overloads": 2,
            "n_line_overloads": 0,
        }
        managed = dict(base, trafo_max_loading_percent=99.0, n_trafo_overloads=0)
        return {"unmanaged": base, "surrogate": managed}

    def test_report_is_unchanged_when_no_bounds_are_supplied(self) -> None:
        from gridalyn.simulation.analytics.network_impact.verification_report import (
            build_network_impact_verification_report,
        )

        report = build_network_impact_verification_report(
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            case_metrics=self._case_metrics(),
            dispatch_summaries={},
        )
        self.assertNotIn("surrogate_error_bounds", report)

    def test_supplied_bounds_are_embedded_json_native_and_sorted(self) -> None:
        from gridalyn.simulation.analytics.network_impact.verification_report import (
            build_network_impact_verification_report,
        )

        bounds = {
            descriptor.surrogate_id: descriptor.error_bound
            for descriptor in default_surrogate_registry().list_descriptors()
            if descriptor.error_bound is not None
        }
        report = build_network_impact_verification_report(
            scenario_id="S4",
            constraint_ids=["transformer:64"],
            case_metrics=self._case_metrics(),
            dispatch_summaries={},
            surrogate_error_bounds=bounds,
        )
        embedded = report["surrogate_error_bounds"]
        self.assertEqual(sorted(embedded), list(embedded))
        self.assertEqual(
            MEASURED,
            embedded[NETWORK_IMPACT_TABULAR_SURROGATE_ID]["status"],
        )
        self.assertEqual(report, json.loads(json.dumps(report)))


class ContractModuleSurfaceTest(unittest.TestCase):
    """The contract and registry expose what the plan's consumers import."""

    def test_public_names_are_exported(self) -> None:
        for name in ("ErrorBound", "Surrogate", "SurrogateDescriptor"):
            self.assertIn(name, contract_module.__all__)
        for name in ("SurrogateRegistry", "default_surrogate_registry"):
            self.assertIn(name, registry_module.__all__)


if __name__ == "__main__":
    unittest.main()

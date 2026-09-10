"""Gate: the semantic profile is a set of axioms a graph is held to.

syntgrid-4ky.2. Measured on the shipped twin before this gate (2026-09-10):

* an unregistered semantic capability name was ignored in silence --
  ``profile_with_capabilities({"agent_interaction"})`` returned the core
  profile -- and the twin build never passed its capabilities to the semantic
  step at all;
* ``ENABLES`` and ``HAS_FLEXIBILITY_RESOURCE`` each carried two predicate IRIs,
  and 10 357 topology edges used the class ``cim:ConnectivityNode`` as their
  predicate;
* no predicate, domain or range was declared, so none could be checked;
* ``gridalyn semantic validate`` checked the default full graph against the
  core-only profile: 40 errors on a valid graph.

Each test pins one of those. Each was mutation-tested when written: the guarded
code was broken on purpose, the test went red, the code was restored.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.projects.workflows.digital_twin.build import build_digital_twin_steps
from gridalyn.projects.workflows.scripts.validate_digital_twin_semantics import (
    validate_semantic_artifacts,
)
from gridalyn.twin.semantic.builder import SemanticGraphBuilder
from gridalyn.twin.semantic.capabilities.flexibility import FLEXIBILITY_CAPABILITY
from gridalyn.twin.semantic.mappings import build_semantic_graph
from gridalyn.twin.semantic.profile import (
    north_america_profile,
    profile_with_capabilities,
    semantic_uri,
)
from gridalyn.twin.semantic.records import _edge, _node
from gridalyn.twin.semantic.registry import (
    SemanticCapabilityRegistry,
    UnknownSemanticCapabilityError,
    default_semantic_capability_registry,
    register_semantic_capability_extension,
)
from gridalyn.twin.semantic.validation import validate_semantic_graph
from gridalyn.twin.semantic.vocabulary import (
    CapabilityInputs,
    RelationshipSpec,
    SemanticCapability,
)
from tests.test_twin_model_first import _fixtures


def _build(
    capabilities: set[str] | None,
    registry: SemanticCapabilityRegistry | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data = _fixtures()
    return build_semantic_graph(
        buses=data["buses"],
        lines=data["lines"],
        transformers=data["transformers"],
        buildings=data["buildings"],
        connectivity=data["connectivity"],
        asset_registry=data["assets"],
        provider_registry=data["providers"],
        timeseries_manifests=data["timeseries"],
        capabilities=capabilities,
        registry=registry,
    )


def _mark_scenarios(builder: SemanticGraphBuilder, inputs: CapabilityInputs) -> None:
    """A host extender: one marker node per scenario, linked from the scenario."""
    for scenario_id in sorted(
        inputs.asset_registry["scenario_id"].astype(str).unique()
    ):
        marker = f"toy:marker:{scenario_id}"
        builder.add_node(
            _node(
                marker,
                ["Marker"],
                "toy:Marker",
                "Toy",
                "test",
                marker,
                scenario_id=scenario_id,
            )
        )
        builder.add_edge(
            _edge(
                f"scenario:{scenario_id}",
                "MARKS",
                marker,
                "toy:marks",
                "Toy",
                "test",
                marker,
                scenario_id=scenario_id,
            )
        )


def _toy_capability(**overrides: Any) -> SemanticCapability:
    fields: dict[str, Any] = {
        "capability_id": "toy",
        "namespaces": {"toy": "https://example.org/toy#"},
        "primary_standards": {"toy_concern": ("Toy Standard",)},
        "semantic_types": ("toy:Marker",),
        "relationships": (
            RelationshipSpec(
                name="MARKS",
                predicate="toy:marks",
                domain=("dt:Scenario",),
                range=("toy:Marker",),
            ),
        ),
        "extend": _mark_scenarios,
    }
    fields.update(overrides)
    return SemanticCapability(**fields)


def _registry_with(*capabilities: SemanticCapability) -> SemanticCapabilityRegistry:
    """A private registry: the shipped capability plus host ones. Never the default."""
    registry = SemanticCapabilityRegistry()
    registry.register(FLEXIBILITY_CAPABILITY)
    for capability in capabilities:
        register_semantic_capability_extension(
            capability, version="0.1", registry=registry
        )
    return registry


class CapabilityResolutionTest(unittest.TestCase):
    def test_unknown_capability_is_rejected_naming_the_known_set(self) -> None:
        attempts = {
            "profile": lambda: profile_with_capabilities({"agent_interaction"}),
            "graph": lambda: _build({"agent_interaction"}),
        }
        for label, attempt in attempts.items():
            with self.subTest(label):
                with self.assertRaises(UnknownSemanticCapabilityError) as ctx:
                    attempt()
                self.assertIn("'agent_interaction'", str(ctx.exception))
                self.assertIn("known: flexibility", str(ctx.exception))
        self.assertTrue(issubclass(UnknownSemanticCapabilityError, ValueError))

    def test_twin_build_rejects_an_unknown_capability(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_digital_twin_steps(capabilities={"agent-interaction"})
        self.assertIn("agent-interaction", str(ctx.exception))
        self.assertIn("ev-hosting", str(ctx.exception))

    def test_twin_build_passes_its_semantic_capabilities_to_the_semantic_step(
        self,
    ) -> None:
        cases: tuple[tuple[set[str] | None, list[str]], ...] = (
            (None, ["flexibility"]),
            (set(), []),
            ({"ev-hosting"}, []),
            ({"flexibility"}, ["flexibility"]),
            ({"ev-hosting", "flexibility"}, ["flexibility"]),
        )
        for capabilities, expected in cases:
            with self.subTest(capabilities=capabilities):
                step = next(
                    step
                    for step in build_digital_twin_steps(capabilities=capabilities)
                    if step["name"] == "generate_semantic_graph"
                )
                command = step["command"]
                self.assertIn("--semantic-capabilities", command)
                position = command.index("--semantic-capabilities")
                self.assertEqual(command[position + 1 :], expected)

    def test_core_and_host_registrations_are_attributed(self) -> None:
        default = default_semantic_capability_registry()
        self.assertEqual(default.registration_source("flexibility"), "core")
        registry = _registry_with(_toy_capability())
        self.assertEqual(registry.registration_source("toy"), "host")
        self.assertEqual(registry.registration_version("toy"), "0.1")

    def test_duplicate_registration_requires_replace(self) -> None:
        registry = _registry_with(_toy_capability())
        with self.assertRaises(ValueError):
            register_semantic_capability_extension(
                _toy_capability(), version="0.2", registry=registry
            )
        register_semantic_capability_extension(
            _toy_capability(), version="0.2", replace=True, registry=registry
        )
        self.assertEqual(registry.registration_version("toy"), "0.2")

    def test_a_host_capability_extends_the_graph_end_to_end(self) -> None:
        registry = _registry_with(_toy_capability())
        nodes, edges, manifest = _build({"toy"}, registry=registry)
        self.assertEqual(manifest["capabilities"], ["toy"])
        markers = nodes.loc[nodes["semantic_type"] == "toy:Marker"]
        self.assertEqual(
            list(markers["semantic_uri"]), ["https://example.org/toy#Marker"]
        )
        marks = edges.loc[edges["relationship_type"] == "MARKS"]
        self.assertEqual(set(marks["semantic_uri"]), {"https://example.org/toy#marks"})
        profile = profile_with_capabilities({"toy"}, registry=registry)
        report = validate_semantic_graph(nodes, edges, profile)
        self.assertTrue(report["valid"], report["errors"])


class ProfileCompositionTest(unittest.TestCase):
    def test_one_relationship_cannot_carry_two_predicates(self) -> None:
        clash = _toy_capability(
            relationships=(
                RelationshipSpec(
                    name="HAS_LOAD",
                    predicate="dt:hasLoads",
                    domain=("brick:Building",),
                    range=("cim:EnergyConsumer",),
                ),
            )
        )
        with self.assertRaises(ValueError) as ctx:
            profile_with_capabilities({"toy"}, registry=_registry_with(clash))
        for fragment in ("HAS_LOAD", "dt:hasLoad by core", "dt:hasLoads by toy"):
            self.assertIn(fragment, str(ctx.exception))

    def test_a_prefix_cannot_bind_two_iris(self) -> None:
        rebinding = _toy_capability(
            namespaces={
                "toy": "https://example.org/toy#",
                "cim": "https://example.org/not-cim#",
            }
        )
        with self.assertRaises(ValueError) as ctx:
            profile_with_capabilities({"toy"}, registry=_registry_with(rebinding))
        self.assertIn("'cim'", str(ctx.exception))

    def test_a_relationship_cannot_name_an_undeclared_type(self) -> None:
        dangling = _toy_capability(
            relationships=(
                RelationshipSpec(
                    name="MARKS",
                    predicate="toy:marks",
                    domain=("dt:Scenario",),
                    range=("toy:Nothing",),
                ),
            )
        )
        with self.assertRaises(ValueError) as ctx:
            profile_with_capabilities({"toy"}, registry=_registry_with(dangling))
        self.assertIn("toy:Nothing", str(ctx.exception))

    def test_every_emitted_relationship_carries_exactly_its_declared_predicate(
        self,
    ) -> None:
        for capabilities in (set(), {"flexibility"}):
            with self.subTest(capabilities=capabilities):
                _nodes, edges, _manifest = _build(capabilities)
                profile = profile_with_capabilities(capabilities)
                emitted = edges.groupby("relationship_type")["semantic_uri"].unique()
                self.assertGreater(len(emitted), 0)
                for relationship, iris in emitted.items():
                    self.assertEqual(
                        list(iris),
                        [profile["relationships"][relationship]["iri"]],
                        relationship,
                    )
                class_iris = {
                    semantic_uri(semantic_type, profile["namespaces"])
                    for semantic_type in profile["allowed_semantic_types"]
                }
                self.assertEqual(set(edges["semantic_uri"]) & class_iris, set())

    def test_builder_refuses_what_the_profile_does_not_declare(self) -> None:
        builder = SemanticGraphBuilder(north_america_profile())
        with self.assertRaises(ValueError) as ctx:
            builder.add_node(
                _node(
                    "offer:S4:x",
                    ["FlexibilityOffer"],
                    "cls:FlexibilityOffer",
                    "Gridalyn_CLS",
                    "test",
                    "offer:S4:x",
                )
            )
        self.assertIn("cls:FlexibilityOffer", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            builder.add_edge(
                _edge("building:0", "OFFERS", "x", "cls:offers", "CLS", "test", "x")
            )
        self.assertIn("'OFFERS'", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            builder.add_edge(
                _edge(
                    "building:0",
                    "HAS_LOAD",
                    "load:0",
                    "cim:ConnectivityNode",
                    "IEC_CIM",
                    "test",
                    "x",
                )
            )
        self.assertIn("dt:hasLoad", str(ctx.exception))
        self.assertEqual(builder.node_count + builder.edge_count, 0)


class AxiomValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes, self.edges, _manifest = _build({"flexibility"})
        self.profile = profile_with_capabilities({"flexibility"})

    def _errors(self, **overrides: Any) -> list[str]:
        arguments: dict[str, Any] = {
            "nodes": self.nodes,
            "edges": self.edges,
            "profile": self.profile,
        }
        arguments.update(overrides)
        return validate_semantic_graph(**arguments)["errors"]

    def _first(self, relationship: str) -> Any:
        return self.edges.index[self.edges["relationship_type"] == relationship][0]

    def test_the_fixture_graph_satisfies_the_flexibility_axioms(self) -> None:
        report = validate_semantic_graph(
            self.nodes,
            self.edges,
            self.profile,
            expected_scenario_counts={
                "S4": {"n_ev": 1, "n_soft_participants": 1, "n_hard_preferred": 0}
            },
        )
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_an_edge_outside_its_range_is_reported(self) -> None:
        edges = self.edges.copy()
        edges.loc[self._first("OFFERS"), "target_id"] = "transformer:0"
        errors = self._errors(edges=edges)
        self.assertTrue(
            any(
                "OFFERS" in error
                and "outside its range" in error
                and "cim:PowerTransformer" in error
                for error in errors
            ),
            errors,
        )

    def test_an_edge_outside_its_domain_is_reported(self) -> None:
        edges = self.edges.copy()
        edges.loc[self._first("OFFERS"), "source_id"] = "bus:0"
        errors = self._errors(edges=edges)
        self.assertTrue(
            any("OFFERS" in e and "outside its domain" in e for e in errors), errors
        )

    def test_a_predicate_other_than_the_declared_one_is_reported(self) -> None:
        edges = self.edges.copy()
        edges.loc[self._first("HAS_LOAD"), "semantic_uri"] = semantic_uri(
            "cim:ConnectivityNode"
        )
        errors = self._errors(edges=edges)
        self.assertTrue(
            any(
                e.startswith("relationship HAS_LOAD: 1 edge(s) carry IRI")
                for e in errors
            ),
            errors,
        )

    def test_a_declared_cardinality_is_enforced(self) -> None:
        edges = self.edges.drop(index=self._first("HAS_LOAD"))
        self.assertIn(
            "brick:Building building:0 must have exactly 1 HAS_LOAD edge(s), found 0",
            self._errors(edges=edges),
        )

    def test_scenario_counts_are_counted_by_the_profile_rules(self) -> None:
        errors = self._errors(expected_scenario_counts={"S4": {"n_ev": 2}})
        self.assertIn("scenario S4 n_ev expected 2 got 1", errors)

    def test_a_count_without_a_rule_is_an_error_not_a_skip(self) -> None:
        nodes, edges, _manifest = _build(set())
        errors = self._errors(
            nodes=nodes,
            edges=edges,
            profile=north_america_profile(),
            expected_scenario_counts={"S4": {"n_ev": 1}},
        )
        self.assertTrue(any("'n_ev' has no rule" in e for e in errors), errors)

    def test_a_profile_without_axioms_states_what_it_did_not_check(self) -> None:
        profile = {k: v for k, v in self.profile.items() if k != "relationships"}
        report = validate_semantic_graph(self.nodes, self.edges, profile)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["warning_count"], 1)


_SEMANTIC_GRAPH_DOC = (
    Path(__file__).resolve().parents[1] / "docs" / "reference" / "semantic-graph.md"
)


def _per_source(bounds: list[int] | None) -> str:
    if bounds is None:
        return "—"
    low, high = bounds
    return f"exactly {low}" if low == high else f"{low}–{high}"


class DocsRelationshipTableTest(unittest.TestCase):
    def test_the_documented_relationships_are_the_declared_ones(self) -> None:
        """The reference page's table is a second copy; hold it to the first.

        The page's previous hand-written list had already drifted: it said
        ``OBSERVES`` points at an asset, while every emitted edge points at a
        scenario.
        """
        text = _SEMANTIC_GRAPH_DOC.read_text(encoding="utf-8")
        section = text.split("## Main Relationships", 1)[1].split("\n## ", 1)[0]
        documented = {}
        for line in section.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 5 and cells[0].startswith("`"):
                documented[cells[0].strip("`")] = (
                    cells[1].strip("`"),
                    cells[3],
                    cells[4],
                )
        declared = {
            name: (
                spec["predicate"],
                _per_source(spec["source_cardinality"]),
                ", ".join(spec["declared_by"]),
            )
            for name, spec in profile_with_capabilities({"flexibility"})[
                "relationships"
            ].items()
        }
        self.assertEqual(documented, declared)


class ValidateScriptTest(unittest.TestCase):
    def _validate(self, recorded: list[str] | None) -> dict[str, Any]:
        """Validate a full (flexibility) graph whose manifest records ``recorded``."""
        nodes, edges, manifest = _build({"flexibility"})
        if recorded is None:
            manifest.pop("capabilities")
        else:
            manifest["capabilities"] = recorded
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            semantic_dir = root / "semantic"
            semantic_dir.mkdir()
            (root / "scenarios").mkdir()
            nodes.to_parquet(semantic_dir / "nodes.parquet", index=False)
            edges.to_parquet(semantic_dir / "edges.parquet", index=False)
            (semantic_dir / "graph_manifest.json").write_text(json.dumps(manifest))
            return validate_semantic_artifacts(
                semantic_dir=semantic_dir, scenario_dir=root / "scenarios", root=root
            )

    def test_a_graph_validates_against_the_capabilities_it_was_built_with(self) -> None:
        report = self._validate(["flexibility"])
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["capabilities"], ["flexibility"])

    def test_the_recorded_capabilities_decide_the_profile(self) -> None:
        report = self._validate([])
        self.assertFalse(report["valid"])
        self.assertTrue(any("cls:" in e for e in report["errors"]), report["errors"])

    def test_a_manifest_without_capabilities_uses_the_legacy_default_and_says_so(
        self,
    ) -> None:
        report = self._validate(None)
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(
            any("legacy default" in w for w in report["warnings"]), report["warnings"]
        )


if __name__ == "__main__":
    unittest.main()

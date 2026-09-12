"""Gates for gridalyn's own vocabularies: persistent IRIs, published documents, aliases.

``dt:`` and ``cls:`` sat on ``gridalyn.local``, a host nothing resolves, so
every IRI the semantic graph minted for gridalyn's own terms was a name with no
definition behind it. The acceptance of syntgrid-4ky.3, each pinned here:

* the graph emits no ``gridalyn.local`` IRI -- checked on the composed profile
  and on a built graph;
* the alias table covers every former ``cls:`` type and relationship
  predicate, and each alias resolves to a term that is live;
* the published documents (a reference page and a Turtle file per vocabulary)
  are exactly what the declarations generate, give every term an anchor, and
  are what the w3id.org redirects point at.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
import warnings
from pathlib import Path

import pandas as pd

from gridalyn.twin.semantic.ontology import (
    ONTOLOGY_DOCUMENTS,
    build_ontology_page,
    build_ontology_turtle,
)
from gridalyn.twin.semantic.profile import (
    GRIDALYN_ONTOLOGY_BASE,
    profile_with_capabilities,
    resolve_deprecated_term,
    resolve_ingest_iri,
)
from gridalyn.twin.semantic.repository import SemanticGraphRepository
from gridalyn.twin.semantic.vocabulary import TermAlias

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every type and relationship predicate the flexibility capability emitted
#: under ``cls:`` before 2026-09-11, as read from the capability at 21d21f1b.
FORMER_CLS_TERMS = (
    "cls:ConstraintZone",
    "cls:FlexibilityAggregator",
    "cls:FlexibilityOffer",
    "cls:FlexibilityPortfolio",
    "cls:FlexibilityProvider",
    "cls:HardCLSContract",
    "cls:SoftCLSContract",
    "cls:aggregates",
    "cls:constraintZoneFor",
    "cls:describesFlexibility",
    "cls:enablesContract",
    "cls:implementsContract",
    "cls:includesProvider",
    "cls:locatedInConstraintZone",
    "cls:managesPortfolio",
    "cls:offers",
    "cls:participatesIn",
    "cls:targetsConstraint",
)


def _profile() -> dict:
    return profile_with_capabilities({"flexibility"})


def _live_terms(profile: dict) -> set[str]:
    return (
        set(profile["allowed_semantic_types"])
        | {spec["predicate"] for spec in profile["relationships"].values()}
        | set(profile["predicates"])
    )


def _export_tool():
    name = "export_ontology_under_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, REPO_ROOT / "tools" / "export_ontology.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class PersistentIriTest(unittest.TestCase):
    def test_the_profile_binds_no_gridalyn_local_namespace_or_predicate(self) -> None:
        profile = _profile()
        iris = [
            *profile["namespaces"].values(),
            *(spec["iri"] for spec in profile["relationships"].values()),
        ]
        self.assertEqual([iri for iri in iris if "gridalyn.local" in iri], [])

    def test_a_built_graph_emits_no_gridalyn_local_iri(self) -> None:
        from tests.test_semantic_axioms import _build

        nodes, edges, _manifest = _build({"flexibility"})
        self.assertGreater(len(nodes), 0)
        self.assertFalse(nodes["semantic_uri"].str.contains("gridalyn.local").any())
        self.assertFalse(edges["semantic_uri"].str.contains("gridalyn.local").any())
        self.assertTrue(
            nodes["semantic_uri"].str.startswith(GRIDALYN_ONTOLOGY_BASE).any()
        )

    def test_every_document_iri_is_the_namespace_the_profile_binds(self) -> None:
        namespaces = _profile()["namespaces"]
        for document in ONTOLOGY_DOCUMENTS:
            with self.subTest(document=document.document_id):
                self.assertEqual(namespaces[document.prefix], document.namespace)
                self.assertTrue(document.namespace.startswith(GRIDALYN_ONTOLOGY_BASE))


class DeprecatedAliasTest(unittest.TestCase):
    def test_every_former_cls_term_resolves_to_a_live_term(self) -> None:
        live = _live_terms(_profile())
        for term in (*FORMER_CLS_TERMS, "ieee2030_5:EVSE", "efont:hasNetworkImpact"):
            with self.subTest(term=term):
                alias = resolve_deprecated_term(term)
                self.assertIsNotNone(alias, f"{term} has no declared alias")
                self.assertIn(alias.replacement, live)
                self.assertNotIn(term, live)

    def test_the_contract_aliases_carry_the_mode_their_names_encoded(self) -> None:
        for term, mode in (
            ("cls:SoftCLSContract", "soft"),
            ("cls:HardCLSContract", "hard"),
        ):
            alias = resolve_deprecated_term(term)
            self.assertEqual(alias.replacement, "flexint:CurtailmentContract")
            self.assertEqual(dict(alias.properties), {"contract_mode": mode})

    def test_a_query_by_a_deprecated_type_warns_and_filters_by_mode(self) -> None:
        from tests.test_semantic_axioms import _build

        nodes, edges, _manifest = _build({"flexibility"})
        repository = SemanticGraphRepository(nodes=nodes, edges=edges)
        scenario = str(
            nodes.loc[nodes["semantic_type"] == "flexint:CurtailmentContract"].iloc[0][
                "scenario_id"
            ]
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            soft = repository.assets_in_scenario(scenario, "cls:SoftCLSContract")
        self.assertTrue(any(w.category is DeprecationWarning for w in caught))
        current = repository.assets_in_scenario(scenario, "flexint:CurtailmentContract")
        self.assertGreater(len(soft), 0)
        self.assertLess(len(soft), len(current))
        self.assertTrue(all(n["properties"]["contract_mode"] == "soft" for n in soft))

    def test_an_old_graph_evse_still_selects_only_its_ev_load_series(self) -> None:
        def node(node_id: str, semantic_type: str, source_table: str) -> dict:
            return {
                "node_id": node_id,
                "labels": "[]",
                "semantic_type": semantic_type,
                "semantic_uri": "",
                "source_standard": "",
                "source_table": source_table,
                "source_id": node_id,
                "name": None,
                "scenario_id": "S0",
                "properties": "{}",
            }

        series = [
            node("ts:ev", "dt:TimeSeriesDataset", "ev_load_summary"),
            node("ts:pf", "dt:TimeSeriesDataset", "powerflow_summary"),
        ]
        edges = pd.DataFrame(columns=["edge_id", "source_id", "target_id"])
        selected = {}
        for semantic_type in (
            "ieee2030_5:EVSE",
            "brick:Electric_Vehicle_Charging_Station",
            "brick:Building",
        ):
            nodes = pd.DataFrame([node("asset:1", semantic_type, "assets"), *series])
            repository = SemanticGraphRepository(nodes=nodes, edges=edges)
            selected[semantic_type] = [
                record["node_id"]
                for record in repository.timeseries_for_asset("asset:1")
            ]
        self.assertEqual(selected["ieee2030_5:EVSE"], ["ts:ev"])
        self.assertEqual(selected["brick:Electric_Vehicle_Charging_Station"], ["ts:ev"])
        self.assertEqual(selected["brick:Building"], ["ts:ev", "ts:pf"])


class AliasDeclarationTest(unittest.TestCase):
    """Composition refuses an alias table that would not resolve or would shadow."""

    @staticmethod
    def _compose(*aliases: TermAlias) -> dict:
        from tests.test_semantic_axioms import _registry_with, _toy_capability

        registry = _registry_with(_toy_capability(deprecated_aliases=aliases))
        return profile_with_capabilities({"flexibility", "toy"}, registry=registry)

    def test_a_declared_alias_is_rendered_with_its_declarer(self) -> None:
        profile = self._compose(TermAlias("toy:OldMarker", "toy:Marker"))
        rendered = profile["deprecated_aliases"]["toy:OldMarker"]
        self.assertEqual(rendered["replacement"], "toy:Marker")
        self.assertEqual(rendered["declared_by"], "toy")

    def test_an_alias_to_a_term_no_declaration_lists_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no active declaration lists"):
            self._compose(TermAlias("toy:OldMarker", "toy:Missing"))

    def test_an_alias_of_a_term_that_is_still_live_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "still declared as a live term"):
            self._compose(TermAlias("toy:Marker", "flexint:FlexibilityOffer"))

    def test_a_term_aliased_by_two_capabilities_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "aliased twice"):
            self._compose(TermAlias("cls:offers", "toy:Marker"))


class CimIngestTest(unittest.TestCase):
    def test_the_primary_and_the_mapped_ingest_terms_resolve(self) -> None:
        self.assertEqual(
            resolve_ingest_iri("http://iec.ch/TC57/CIM100#ACLineSegment"),
            "cim:ACLineSegment",
        )
        self.assertEqual(
            resolve_ingest_iri("https://cim.ucaiug.io/ns#ConnectivityNode"),
            "cim:ConnectivityNode",
        )

    def test_an_unmapped_ingest_term_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not mapped from it"):
            resolve_ingest_iri("http://cim.ucaiug.io/CIM101/draft#Terminal")
        with self.assertRaisesRegex(ValueError, "no CIM namespace gridalyn reads"):
            resolve_ingest_iri("https://example.org/other#Thing")


class PublishedDocumentTest(unittest.TestCase):
    def test_the_committed_documents_are_the_generated_ones(self) -> None:
        for path, content in _export_tool().document_files(REPO_ROOT).items():
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                self.assertTrue(
                    path.is_file(), f"{path} is missing; run tools/export_ontology.py"
                )
                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    content,
                    "stale; run python tools/export_ontology.py",
                )

    def test_every_gridalyn_term_has_an_anchor_on_its_vocabulary_page(self) -> None:
        pages = {
            document.prefix: build_ontology_page(document.document_id)
            for document in ONTOLOGY_DOCUMENTS
        }
        own = sorted(
            term for term in _live_terms(_profile()) if term.split(":")[0] in pages
        )
        self.assertGreater(len(own), 20)
        for qname in own:
            prefix, _, local_name = qname.partition(":")
            with self.subTest(term=qname):
                anchor = '<a id="' + local_name + '"></a>'
                self.assertIn(anchor + "`" + qname + "`", pages[prefix])

    def test_the_turtle_declares_terms_deprecations_and_its_prefixes(self) -> None:
        turtle = build_ontology_turtle("flexint")
        self.assertIn("flexint:CurtailmentContract a owl:Class ;", turtle)
        self.assertIn("flexint:aggregates a owl:ObjectProperty ;", turtle)
        self.assertIn(
            "<https://gridalyn.local/ontology/cls#SoftCLSContract> owl:deprecated true ;",
            turtle,
        )
        self.assertIn("dcterms:isReplacedBy flexint:CurtailmentContract", turtle)
        without_literals = re.sub(r'"(?:[^"\\]|\\.)*"', '""', turtle)
        without_iris = re.sub(r"<[^>]*>", "<>", without_literals)
        declared = set(re.findall(r"^@prefix (\w+):", turtle, re.M))
        used = set(re.findall(r"(?<![\w@])([A-Za-z]\w*):[A-Za-z_]", without_iris))
        self.assertLessEqual(used, declared)

    def test_the_w3id_redirects_point_at_every_published_document(self) -> None:
        directory = REPO_ROOT / "tools" / "w3id" / "gridalyn"
        htaccess = (directory / ".htaccess").read_text(encoding="utf-8")
        readme = (directory / "README.md").read_text(encoding="utf-8")
        for document in ONTOLOGY_DOCUMENTS:
            with self.subTest(document=document.document_id):
                self.assertIn(f"^ontology/{document.document_id}/?$", htaccess)
                self.assertIn(document.page_url, htaccess)
                self.assertIn(document.turtle_url, htaccess)
                self.assertIn(document.namespace, readme)
        self.assertIn("lirei.info@uqtr.ca", readme)


if __name__ == "__main__":
    unittest.main()

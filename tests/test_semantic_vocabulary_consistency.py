"""Semantic vocabulary consistency: the surrogate speaks the canonical language."""

from __future__ import annotations

import unittest

import pandas as pd

from gridalyn.simulation.analytics.network_impact.surrogate import build_graph_snapshot
from gridalyn.twin.semantic.profile import SEMANTIC_TYPE, _all_namespaces, semantic_uri


class SemanticVocabularyConsistencyTest(unittest.TestCase):
    """Phase 9 finding G10: every generator must emit one canonical vocabulary."""

    def _providers(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "provider_type": "soft_cls_building",
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "ev_id": "ev:S4:0",
                    "pandapower_load": 0,
                    "load_bus_id": "bus:0",
                    "feeder_bus_id": "bus:1",
                    "constraint_zone_id": "transformer:0",
                    "constraint_zone_type": "cim:PowerTransformer",
                    "available_capacity_kw": 6.5,
                    "base_cost_per_kw_h": 3.0,
                    "selection_priority": 1,
                }
            ]
        )

    def _sensitivity(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "provider_id": "provider:S4:building:0:soft_cls",
                    "scenario_id": "S4",
                    "constraint_id": "transformer:0",
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": 0.5,
                    "deliverability_factor": 1.0,
                    "available_relief_kw": 3.0,
                }
            ]
        )

    def test_surrogate_node_types_are_canonical(self) -> None:
        nodes, _edges = build_graph_snapshot(
            self._providers(), self._sensitivity(), scenario_id="S4"
        )
        emitted = set(nodes["semantic_type"])
        # The divergent qnames are gone (G10): the surrogate must emit the
        # canonical spellings, never efont:FlexibilityProvider / s223:Building /
        # ieee2030_5:DER.
        self.assertNotIn("efont:FlexibilityProvider", emitted)
        self.assertNotIn("s223:Building", emitted)
        self.assertNotIn("ieee2030_5:DER", emitted)
        self.assertTrue(emitted.issubset(set(SEMANTIC_TYPE.values())))

    def test_surrogate_uris_resolve_to_namespaces_not_qnames(self) -> None:
        nodes, edges = build_graph_snapshot(
            self._providers(), self._sensitivity(), scenario_id="S4"
        )
        for frame in (nodes, edges):
            for qname, uri in zip(
                frame["semantic_type"], frame["semantic_uri"], strict=True
            ):
                prefix = qname.split(":", 1)[0]
                # Phase 21: the model-first core owns NAMESPACES; the
                # flexibility/DER prefixes (cls:/efont:/ieee2030_5:) resolve
                # through the capability extensions, which semantic_uri uses.
                self.assertIn(prefix, _all_namespaces(), qname)
                self.assertEqual(uri, semantic_uri(qname), qname)
                self.assertNotEqual(uri, qname, qname)

    def test_canonical_types_are_registered(self) -> None:
        # Phase 21: SEMANTIC_TYPE is the shared canonical vocabulary (core +
        # capability); each qname must resolve against the merged namespaces.
        namespaces = _all_namespaces()
        for qname in SEMANTIC_TYPE.values():
            prefix = qname.split(":", 1)[0]
            self.assertIn(prefix, namespaces, qname)
            self.assertTrue(semantic_uri(qname).startswith(namespaces[prefix]))


if __name__ == "__main__":
    unittest.main()

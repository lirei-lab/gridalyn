"""Gates for the ``agent_interaction`` semantic capability (bd 4ky.7).

The acceptance of the issue, each pinned here:

* with the capability off, the graph carries **zero** agent-interaction triples
  (the ``test_twin_model_first`` pattern);
* with it on, the graph validates against the declared domain, range and
  cardinality;
* publication exposes the new classes.

Two of this module's tests exist because the capability may not import
``gridalyn.operations`` -- the semantic layer sits below it -- and therefore
restates two of its contracts as data. A test may import both sides, so the
restatements are pinned against their sources here rather than trusted.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.operations.interaction.log import MESSAGE_LOG_COLUMNS
from gridalyn.operations.interaction.roles import ROLE_ALIGNMENT
from gridalyn.twin.semantic.capabilities.agent_interaction import (
    REQUIRED_LOG_COLUMNS,
    ROLE_ALIGNMENT_TABLE,
    query_agents_answering_constraint,
    query_conversations_for_constraint,
)
from gridalyn.twin.semantic.mappings import build_semantic_graph
from gridalyn.twin.semantic.profile import profile_with_capabilities
from gridalyn.twin.semantic.publication import resolve_semantic_publication
from gridalyn.twin.semantic.repository import SemanticGraphRepository
from gridalyn.twin.semantic.validation import validate_semantic_graph
from tests.test_twin_model_first import _fixtures

CAPABILITY_MODULE = (
    Path(__file__).resolve().parents[1]
    / "gridalyn"
    / "twin"
    / "semantic"
    / "capabilities"
    / "agent_interaction.py"
)

#: Every type the capability adds, so "zero with it off" is checked on all of
#: them rather than on a sample.
AGENT_INTERACTION_TYPES = (
    "flexint:Agent",
    "flexint:Conversation",
    "flexint:DemandResponseEvent",
    "flexint:DemandResponseProgram",
    "flexint:Party",
    "flexint:Role",
)


def _message(
    conversation_id: str,
    protocol: str,
    message_type: str,
    performative: str,
    sender: tuple[str, str, str],
    receiver: tuple[str, str, str],
    sent_at: float,
    payload_json: str = "{}",
    outcome: str = "delivered",
) -> dict[str, Any]:
    """One message-log row, in the columns the log contract writes."""
    return {
        "conversation_id": conversation_id,
        "protocol": protocol,
        "message_type": message_type,
        "performative": performative,
        "sender_agent_id": sender[0],
        "sender_party_id": sender[1],
        "sender_role": sender[2],
        "receiver_agent_id": receiver[0],
        "receiver_party_id": receiver[1],
        "receiver_role": receiver[2],
        "sent_at": sent_at,
        "payload_json": payload_json,
        "outcome": outcome,
    }


_ADMIN = ("admin:0", "party:utility", "program_administrator")
_HOME = ("home:0", "party:home:0", "active_customer")
_HOME_1 = ("home:1", "party:home:1", "active_customer")
_DSO = ("dso:0", "party:utility", "distribution_operator")
_AGR = ("agr:0", "party:aggregator", "aggregator")

_EVENT_PAYLOAD = (
    '{"programID": "winter-2026", "eventName": "evening", '
    '"intervals": [{"id": 0, "payloads": [{"type": '
    '"flexint:IMPORT_CAPACITY_LIMIT_KW", "values": [4.0]}]}], '
    '"flexint:activeFrom": 1020.0, "flexint:activeUntil": 1140.0}'
)
_REPORT_PAYLOAD = (
    '{"clientID": "home:1", "eventID": "evening", "clientName": "home-1", '
    '"resources": []}'
)


def _dr_log() -> pd.DataFrame:
    """A demand-response day: one event notified, one home reporting on it.

    The two conversations reach the event by *different* payload spellings --
    ``eventName`` in the event, ``eventID`` in the report -- which is what the
    emitter has to reconcile.
    """
    return pd.DataFrame(
        [
            _message(
                "evening:0",
                "dr_program",
                "event",
                "inform",
                _ADMIN,
                _HOME,
                1000.0,
                _EVENT_PAYLOAD,
            ),
            _message(
                "evening:0",
                "dr_program",
                "flexint:OptOut",
                "refuse",
                _HOME,
                _ADMIN,
                1030.0,
                '{"eventID": "evening", "clientName": "home-0"}',
                "lost",
            ),
            _message(
                "evening:1",
                "dr_program",
                "event",
                "inform",
                _ADMIN,
                _HOME_1,
                1000.0,
                _EVENT_PAYLOAD,
            ),
            _message(
                "evening:1",
                "dr_program",
                "report",
                "inform",
                _HOME_1,
                _ADMIN,
                1140.0,
                _REPORT_PAYLOAD,
            ),
        ]
    )


def _trading_log() -> pd.DataFrame:
    """A negotiation over one constraint: the DSO asks, the aggregator answers."""
    request = '{"event_id": "e0", "constraint_id": "transformer:64", "timestep": 0}'
    return pd.DataFrame(
        [
            _message(
                "trade:0",
                "flex_trading",
                "FlexRequest",
                "cfp",
                _DSO,
                _AGR,
                10.0,
                request,
            ),
            _message(
                "trade:0",
                "flex_trading",
                "FlexOffer",
                "propose",
                _AGR,
                _DSO,
                11.0,
                '{"offers": []}',
            ),
            _message(
                "trade:1",
                "flex_trading",
                "FlexRequest",
                "cfp",
                _DSO,
                _AGR,
                20.0,
                '{"event_id": "e1", "constraint_id": "transformer:99", "timestep": 1}',
            ),
        ]
    )


def _build(
    capabilities: set[str], interaction_log: pd.DataFrame | None = None
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
        interaction_log=interaction_log,
        capabilities=capabilities,
    )


class CapabilityOffTest(unittest.TestCase):
    def test_a_graph_without_the_capability_carries_no_interaction_type(self) -> None:
        for capabilities in (set(), {"flexibility"}):
            nodes, edges, _manifest = _build(capabilities, _dr_log())
            with self.subTest(capabilities=sorted(capabilities)):
                present = set(nodes["semantic_type"]) & set(AGENT_INTERACTION_TYPES)
                self.assertEqual(present, set())
                relationships = set(edges["relationship_type"])
                self.assertEqual(
                    relationships
                    & {
                        "ACTS_FOR",
                        "FOLLOWS_EVENT",
                        "PARTICIPATES_IN_CONVERSATION",
                        "PLAYS_ROLE",
                        "SCHEDULES_EVENT",
                    },
                    set(),
                )

    def test_the_capability_without_a_log_still_builds_a_valid_graph(self) -> None:
        nodes, edges, _manifest = _build({"agent_interaction"})
        present = set(nodes["semantic_type"]) & set(AGENT_INTERACTION_TYPES)
        self.assertEqual(present, set())
        report = validate_semantic_graph(
            nodes, edges, profile_with_capabilities({"agent_interaction"})
        )
        self.assertTrue(report["valid"], report["errors"])


class EmittedGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes, self.edges, _manifest = _build({"agent_interaction"}, _dr_log())

    def _ids(self, semantic_type: str) -> list[str]:
        selected = self.nodes.loc[self.nodes["semantic_type"] == semantic_type]
        return sorted(selected["node_id"])

    def test_the_log_becomes_agents_parties_roles_and_conversations(self) -> None:
        self.assertEqual(
            self._ids("flexint:Agent"),
            ["agent:admin:0", "agent:home:0", "agent:home:1"],
        )
        self.assertEqual(
            self._ids("flexint:Party"),
            ["party:party:home:0", "party:party:home:1", "party:party:utility"],
        )
        self.assertEqual(
            self._ids("flexint:Role"),
            ["role:active_customer", "role:program_administrator"],
        )
        self.assertEqual(
            self._ids("flexint:Conversation"),
            ["conversation:evening:0", "conversation:evening:1"],
        )

    def test_a_conversation_summarizes_the_messages_the_log_records(self) -> None:
        repository = SemanticGraphRepository(nodes=self.nodes, edges=self.edges)
        summary = repository.get_node("conversation:evening:0")["properties"]
        self.assertEqual(summary["protocol"], "dr_program")
        self.assertEqual(summary["message_count"], 2)
        self.assertEqual(summary["delivered_message_count"], 1)
        self.assertEqual(summary["lost_message_count"], 1)
        self.assertEqual(summary["participant_count"], 2)
        self.assertEqual(summary["first_sent_at_minute"], 1000.0)
        self.assertEqual(summary["last_sent_at_minute"], 1030.0)
        self.assertEqual(summary["event_id"], "evening")
        self.assertNotIn("state", summary)

    def test_both_event_id_spellings_resolve_to_one_openadr_event(self) -> None:
        self.assertEqual(
            self._ids("flexint:DemandResponseEvent"), ["dr-event:winter-2026:evening"]
        )
        self.assertEqual(
            self._ids("flexint:DemandResponseProgram"), ["dr-program:winter-2026"]
        )
        repository = SemanticGraphRepository(nodes=self.nodes, edges=self.edges)
        event = repository.get_node("dr-event:winter-2026:evening")["properties"]
        self.assertEqual(event["aligns_with"], "OpenADR 3.1.0 EVENT")
        self.assertEqual(event["active_from_minute"], 1020.0)
        self.assertEqual(event["capacity_limit_kw"], 4.0)
        followed = self.edges.loc[self.edges["relationship_type"] == "FOLLOWS_EVENT"]
        self.assertEqual(
            sorted(followed["source_id"]),
            [
                "conversation:evening:0",
                "conversation:evening:1",
            ],
        )

    def test_the_emitted_graph_validates_against_its_axioms(self) -> None:
        report = validate_semantic_graph(
            self.nodes, self.edges, profile_with_capabilities({"agent_interaction"})
        )
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["errors"], [])

    def test_publication_exposes_the_new_classes(self) -> None:
        publication = resolve_semantic_publication(graph_nodes=self.nodes)
        published = {
            entry.name: entry.count
            for entry in publication.classes_in("semantic_graph")
        }
        for semantic_type in AGENT_INTERACTION_TYPES:
            with self.subTest(semantic_type=semantic_type):
                self.assertGreater(published.get(semantic_type, 0), 0)

    def test_the_two_capabilities_compose(self) -> None:
        nodes, edges, manifest = _build({"agent_interaction", "flexibility"}, _dr_log())
        self.assertEqual(manifest["capabilities"], ["agent_interaction", "flexibility"])
        types = set(nodes["semantic_type"])
        self.assertIn("flexint:Agent", types)
        self.assertIn("flexint:CurtailmentContract", types)
        report = validate_semantic_graph(
            nodes,
            edges,
            profile_with_capabilities({"agent_interaction", "flexibility"}),
        )
        self.assertTrue(report["valid"], report["errors"])


class ConstraintQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        nodes, edges, _manifest = _build({"agent_interaction"}, _trading_log())
        self.repository = SemanticGraphRepository(nodes=nodes, edges=edges)

    def test_a_constraint_resolves_to_the_conversations_that_named_it(self) -> None:
        conversations = query_conversations_for_constraint(
            self.repository, "transformer:64"
        )
        self.assertEqual(
            [record["node_id"] for record in conversations], ["conversation:trade:0"]
        )

    def test_the_agents_that_answered_a_constraint_are_the_proposing_ones(
        self,
    ) -> None:
        answered = query_agents_answering_constraint(
            self.repository, "transformer:64", performative="propose"
        )
        self.assertEqual(
            [record["node_id"] for record in answered],
            ["agent:agr:0", "agent:dso:0"],
        )
        unanswered = query_agents_answering_constraint(
            self.repository, "transformer:99", performative="propose"
        )
        self.assertEqual(unanswered, ())
        participants = query_agents_answering_constraint(
            self.repository, "transformer:99"
        )
        self.assertEqual(
            [record["node_id"] for record in participants],
            ["agent:agr:0", "agent:dso:0"],
        )


class RestatedContractTest(unittest.TestCase):
    """The capability cannot import operations, so its copies are pinned here."""

    def test_the_role_table_states_what_operations_declares(self) -> None:
        declared = {
            role: {"usef": alignment.usef, "openadr": alignment.openadr}
            for role, alignment in ROLE_ALIGNMENT.items()
        }
        restated = {
            role: dict(alignment) for role, alignment in ROLE_ALIGNMENT_TABLE.items()
        }
        self.assertEqual(restated, declared)

    def test_the_required_columns_are_columns_the_log_contract_writes(self) -> None:
        self.assertLessEqual(set(REQUIRED_LOG_COLUMNS), set(MESSAGE_LOG_COLUMNS))
        order = [
            column for column in MESSAGE_LOG_COLUMNS if column in REQUIRED_LOG_COLUMNS
        ]
        self.assertEqual(list(REQUIRED_LOG_COLUMNS), order)

    def test_the_capability_never_imports_operations(self) -> None:
        tree = ast.parse(CAPABILITY_MODULE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [
            name for name in imported if name.startswith("gridalyn.operations")
        ]
        self.assertEqual(offenders, [])

    def test_a_log_missing_a_column_is_refused_naming_both_sets(self) -> None:
        log = _dr_log().drop(columns=["performative"])
        with self.assertRaises(ValueError) as caught:
            _build({"agent_interaction"}, log)
        message = str(caught.exception)
        self.assertIn("missing column(s) performative", message)
        self.assertIn("present:", message)
        self.assertIn("conversation_id", message)


if __name__ == "__main__":
    unittest.main()

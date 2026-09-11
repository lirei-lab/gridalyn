"""Gate: the flexibility-operations surface speaks closed vocabularies.

syntgrid-4ky.4. Before this gate (measured 2026-09-11) the six vocabularies of
the operations surface were free strings on frozen dataclasses. Unknown values
passed silently in three places: ``_dispatch_action`` gave every provider type
that was not ``hard_cls_ev`` a ``soft_cls_limit`` instruction; clearing selected
a provider of an unknown type and counted its kilowatts as neither soft nor
hard; and ``FlexibilityOperationContext.ontology_profile`` accepted any string
while naming a semantic profile.

Each test below pins one of those behaviours; each was mutation-tested when
written. The mypy tests prove what the ``Literal`` annotations are for: an
invalid value written at a call site is a type error, not a runtime surprise.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, Callable, get_args, get_type_hints

import pandas as pd

from gridalyn.operations.contracts import (
    FlexibilityOperationContext,
    build_operation_context,
)
from gridalyn.operations.domain import (
    DispatchInstruction,
    FlexibilityOffer,
    build_aggregator_portfolios,
    build_dispatch_instructions,
    build_provider_offers,
)
from gridalyn.operations.runs import (
    OperationRun,
    build_operation_run,
    validate_operation_run,
)
from gridalyn.operations.vocabulary import (
    DISPATCH_ACTION_BY_PROVIDER_TYPE,
    DISPATCH_ACTIONS,
    PROVIDER_TYPES,
    ClearingMethod,
    DispatchAction,
    MarketRole,
    OperationStatus,
    OperationType,
    ProviderType,
    parse_clearing_method,
    parse_dispatch_action,
    parse_market_role,
    parse_operation_status,
    parse_operation_type,
    parse_provider_type,
)
from gridalyn.twin.semantic.profile import (
    SEMANTIC_PROFILE_IDS,
    SemanticProfileId,
    profile_with_capabilities,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MYPY_AVAILABLE = importlib.util.find_spec("mypy") is not None


def _instruction(**overrides: Any) -> DispatchInstruction:
    fields: dict[str, Any] = {
        "instruction_id": "dispatch:x",
        "operation_id": "operation:x",
        "event_id": "S0:c:0",
        "scenario_id": "S0",
        "timestep": 0,
        "constraint_id": "c",
        "provider_id": "provider:x",
        "aggregator_id": None,
        "provider_type": "hard_cls_ev",
        "dispatch_action": "hard_cls_interrupt",
        "selected_kw": 1.0,
        "expected_relief_kw": 1.0,
        "estimated_cost_usd": 0.0,
    }
    fields.update(overrides)
    return DispatchInstruction(**fields)


def _offer(**overrides: Any) -> FlexibilityOffer:
    fields: dict[str, Any] = {
        "offer_id": "offer:x",
        "provider_id": "provider:x",
        "aggregator_id": "aggregator:x",
        "scenario_id": "S0",
        "provider_type": "soft_cls_building",
        "quantity_kw": 1.0,
        "price_per_kw_h": 3.0,
        "constraint_zone_id": None,
    }
    fields.update(overrides)
    return FlexibilityOffer(**fields)


def _context(**overrides: Any) -> FlexibilityOperationContext:
    fields: dict[str, Any] = {
        "operation_id": "operation:x",
        "scenario_id": "S0",
        "clearing_method": "surrogate",
        "dt_h": 1.0,
    }
    fields.update(overrides)
    return FlexibilityOperationContext(**fields)


def _run(**overrides: Any) -> OperationRun:
    fields: dict[str, Any] = {
        "operation_id": "operation:x",
        "operation_type": "flexibility_clearing",
        "scenario_id": "S0",
        "network_model_version_id": "model:x",
        "study_run_id": None,
        "input_artifacts": {"providers": "p.parquet"},
        "output_artifacts": {"dispatch": "d.parquet"},
        "kpi_report": "kpi.json",
    }
    fields.update(overrides)
    return OperationRun(**fields)


def _providers(provider_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "provider_id": "provider:a",
                "scenario_id": "S0",
                "provider_type": provider_type,
                "available_capacity_kw": 30.0,
                "base_cost_per_kw_h": 1.0,
                "selection_priority": 0,
            }
        ]
    )


class VocabularyTest(unittest.TestCase):
    PARSERS: tuple[tuple[Callable[[object], str], Any, str], ...] = (
        (parse_provider_type, ProviderType, "provider_type"),
        (parse_dispatch_action, DispatchAction, "dispatch_action"),
        (parse_clearing_method, ClearingMethod, "clearing_method"),
        (parse_market_role, MarketRole, "market_role"),
        (parse_operation_type, OperationType, "operation_type"),
        (parse_operation_status, OperationStatus, "status"),
    )

    def test_each_parser_accepts_its_set_and_names_it_when_refusing(self) -> None:
        for parser, alias, field in self.PARSERS:
            with self.subTest(field=field):
                for term in get_args(alias):
                    self.assertEqual(parser(term), term)
                with self.assertRaises(ValueError) as ctx:
                    parser("bogus")
                message = str(ctx.exception)
                self.assertIn(field, message)
                self.assertIn("'bogus'", message)
                for term in get_args(alias):
                    self.assertIn(repr(term), message)

    def test_parsers_match_exactly_and_the_context_builder_normalizes(self) -> None:
        with self.assertRaises(ValueError):
            parse_clearing_method(" Topology ")
        context = build_operation_context(
            scenario_id="S0",
            clearing_method=" Topology ",
            dt_h=1.0,
            requirements=pd.DataFrame(columns=["constraint_id"]),
            providers=pd.DataFrame(columns=["provider_id"]),
            impact=pd.DataFrame(columns=["constraint_id"]),
        )
        self.assertEqual(context.clearing_method, "topology")

    def test_every_provider_type_has_exactly_one_distinct_dispatch_action(
        self,
    ) -> None:
        self.assertEqual(set(DISPATCH_ACTION_BY_PROVIDER_TYPE), set(PROVIDER_TYPES))
        actions = list(DISPATCH_ACTION_BY_PROVIDER_TYPE.values())
        self.assertLessEqual(set(actions), set(DISPATCH_ACTIONS))
        self.assertEqual(len(set(actions)), len(actions))


class FrozenContractTest(unittest.TestCase):
    def test_field_annotations_are_the_vocabularies(self) -> None:
        expectations = (
            (DispatchInstruction, "provider_type", ProviderType),
            (DispatchInstruction, "dispatch_action", DispatchAction),
            (FlexibilityOffer, "provider_type", ProviderType),
            (FlexibilityOperationContext, "clearing_method", ClearingMethod),
            (FlexibilityOperationContext, "market_role", MarketRole),
            (FlexibilityOperationContext, "ontology_profile", SemanticProfileId),
            (OperationRun, "operation_type", OperationType),
            (OperationRun, "status", OperationStatus),
            (OperationRun, "clearing_method", ClearingMethod | None),
        )
        for cls, field, alias in expectations:
            with self.subTest(cls=cls.__name__, field=field):
                self.assertEqual(get_type_hints(cls)[field], alias)

    def test_construction_refuses_a_value_outside_its_vocabulary(self) -> None:
        cases: tuple[tuple[Callable[..., object], str], ...] = (
            (_instruction, "provider_type"),
            (_instruction, "dispatch_action"),
            (_offer, "provider_type"),
            (_context, "clearing_method"),
            (_context, "market_role"),
            (_context, "ontology_profile"),
            (_run, "operation_type"),
            (_run, "status"),
            (_run, "clearing_method"),
        )
        for factory, field in cases:
            with self.subTest(factory=factory.__name__, field=field):
                with self.assertRaises(ValueError) as ctx:
                    factory(**{field: "bogus"})
                self.assertIn(field, str(ctx.exception))

    def test_a_dispatch_action_must_fit_its_provider_type(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _instruction(provider_type="hard_cls_ev", dispatch_action="soft_cls_limit")
        self.assertIn("expected 'hard_cls_interrupt'", str(ctx.exception))

    def test_the_ontology_profile_is_a_semantic_profile_the_twin_defines(
        self,
    ) -> None:
        self.assertIn(
            profile_with_capabilities(set())["semantic_profile"], SEMANTIC_PROFILE_IDS
        )
        self.assertEqual(_context().ontology_profile, "north_america")


class BoundaryTest(unittest.TestCase):
    def test_clearing_refuses_an_unknown_provider_type_before_selecting_it(
        self,
    ) -> None:
        from gridalyn.operations import run_flexibility_clearing_operation

        impact = pd.DataFrame(
            [
                {
                    "provider_id": "provider:a",
                    "scenario_id": "S0",
                    "constraint_id": "c",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 30.0,
                    "selection_score": 1.0,
                }
            ]
        )
        requirements = pd.DataFrame(
            [{"timestep": 0, "constraint_id": "c", "required_kw": 10.0}]
        )
        with self.assertRaises(ValueError) as ctx:
            run_flexibility_clearing_operation(
                requirements=requirements,
                providers=_providers("battery"),
                impact=impact,
                scenario_id="S0",
                dt_h=1.0,
            )
        self.assertIn("provider_type", str(ctx.exception))
        self.assertIn("'battery'", str(ctx.exception))

    def test_clearing_refuses_an_unknown_provider_type_that_is_never_a_candidate(
        self,
    ) -> None:
        from gridalyn.operations.clearing.selection import build_locational_clearing

        providers = pd.concat(
            [
                _providers("soft_cls_building"),
                _providers("battery").assign(provider_id="provider:b"),
            ],
            ignore_index=True,
        )
        impact = pd.DataFrame(
            [
                {
                    "provider_id": "provider:a",
                    "scenario_id": "S0",
                    "constraint_id": "c",
                    "predicted_deliverability_factor": 1.0,
                    "predicted_relief_kw": 30.0,
                    "selection_score": 1.0,
                }
            ]
        )
        requirements = pd.DataFrame(
            [{"timestep": 0, "constraint_id": "c", "required_kw": 10.0}]
        )
        with self.assertRaises(ValueError) as ctx:
            build_locational_clearing(
                requirements=requirements,
                providers=providers,
                impact=impact,
                scenario_id="S0",
                dt_h=1.0,
            )
        self.assertIn("'battery'", str(ctx.exception))

    def test_domain_builders_refuse_an_unknown_provider_type(self) -> None:
        context = _context()
        selections = pd.DataFrame(
            [
                {
                    "event_id": "S0:c:0",
                    "scenario_id": "S0",
                    "timestep": 0,
                    "constraint_id": "c",
                    "provider_id": "provider:a",
                    "provider_type": "battery",
                    "selected_kw": 5.0,
                    "expected_relief_kw": 5.0,
                    "estimated_cost": 5.0,
                }
            ]
        )
        builders: tuple[tuple[str, Callable[[], object]], ...] = (
            (
                "dispatch",
                lambda: build_dispatch_instructions(
                    selections=selections,
                    providers=_providers("battery"),
                    context=context,
                ),
            ),
            (
                "offers",
                lambda: build_provider_offers(_providers("battery"), scenario_id="S0"),
            ),
            (
                "portfolios",
                lambda: build_aggregator_portfolios(
                    _providers("battery"), scenario_id="S0"
                ),
            ),
        )
        for label, build in builders:
            with self.subTest(builder=label):
                with self.assertRaises(ValueError) as ctx:
                    build()
                self.assertIn("'battery'", str(ctx.exception))

    def test_a_hard_provider_is_dispatched_an_interrupt(self) -> None:
        selections = pd.DataFrame(
            [
                {
                    "event_id": "S0:c:0",
                    "scenario_id": "S0",
                    "timestep": 0,
                    "constraint_id": "c",
                    "provider_id": "provider:a",
                    "provider_type": "hard_cls_ev",
                    "selected_kw": 5.0,
                    "expected_relief_kw": 5.0,
                    "estimated_cost": 5.0,
                }
            ]
        )
        dispatch = build_dispatch_instructions(
            selections=selections,
            providers=_providers("hard_cls_ev"),
            context=_context(),
        )
        self.assertEqual(list(dispatch["dispatch_action"]), ["hard_cls_interrupt"])

    def test_run_builder_and_validator_speak_the_vocabulary(self) -> None:
        with self.assertRaises(ValueError):
            build_operation_run(
                operation_id="operation:x",
                operation_type="settlement_replay",
                scenario_id="S0",
                network_model_version_id="model:x",
                study_run_id=None,
                input_artifacts={"a": "a"},
                output_artifacts={"b": "b"},
                kpi_report="kpi.json",
            )
        payload = _run().to_dict()
        self.assertTrue(validate_operation_run(payload).valid)
        payload["status"] = "failed"
        report = validate_operation_run(payload)
        self.assertFalse(report.valid)
        self.assertTrue(
            any("status 'failed'" in e for e in report.errors), report.errors
        )


_PROBE = """
from gridalyn.operations.domain import DispatchInstruction

DispatchInstruction(
    instruction_id="i",
    operation_id="o",
    event_id="e",
    scenario_id="s",
    timestep=0,
    constraint_id="c",
    provider_id="p",
    aggregator_id=None,
    provider_type="hard_cls_ev",
    dispatch_action={action!r},
    selected_kw=1.0,
    expected_relief_kw=1.0,
    estimated_cost_usd=0.0,
)
"""


def _mypy(action: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(textwrap.dedent(_PROBE.format(action=action)))
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--follow-imports=silent",
                "--ignore-missing-imports",
                "--no-error-summary",
                "--cache-dir",
                str(Path(tmp) / "cache"),
                str(probe),
            ],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )


class MypyCallSiteTest(unittest.TestCase):
    def test_mypy_is_available_where_ci_runs(self) -> None:
        """Kept outside the skip below: a missing mypy must not silently skip."""
        if os.environ.get("CI") and not _MYPY_AVAILABLE:
            self.fail("mypy is not importable in CI; the call-site gate would skip")

    @unittest.skipUnless(
        _MYPY_AVAILABLE,
        "mypy is not importable; install the test extra: pip install -e '.[test]'",
    )
    def test_an_invalid_dispatch_action_at_a_call_site_is_a_type_error(self) -> None:
        refused = _mypy("bogus_action")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn('"dispatch_action"', refused.stdout)
        accepted = _mypy("hard_cls_interrupt")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


if __name__ == "__main__":
    unittest.main()

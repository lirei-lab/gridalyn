"""Frozen public contract for the flexibility clearing/settlement surface.

This module pins the canonical ``gridalyn.operations`` clear+settle contract so
later consolidation phases cannot move the surface silently:

* the 10-symbol frozen public set (API-01 / API-02),
* the exact ``run_flexibility_clearing_operation`` signature (D-04),
* the import-time lazy purity of the operations facade (API-03 / D-03a),
* loose frozen-dataclass shape guards (Pitfall 2),
* a forward-marker placeholder for the Phase-3 determinism obligation (D-05).

The freeze is GREEN against current source; its value is FAILING on future
drift of the frozen set or signature.
"""

from __future__ import annotations

import dataclasses
import inspect
import subprocess
import sys

# The 10-symbol minimal canonical surface (D-01 / D-01a). All are present in
# ``_FLEXIBILITY_EXPORTS`` today; the contract is declared OVER that machinery.
FROZEN_SYMBOLS = {
    "run_flexibility_clearing_operation",
    "build_operation_context",
    "validate_flexibility_operation_inputs",
    "FlexibilityOffer",
    "AggregatorPortfolio",
    "DispatchInstruction",
    "SettlementRecord",
    "NetworkConstraint",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
}

# The seven frozen domain dataclasses, each mapped to a SUBSET of stable
# identifying fields. Loose by design (Pitfall 2): Phase-3 superset additions
# must not trip this freeze, so never assert exact field equality.
FROZEN_DATACLASS_REQUIRED_FIELDS = {
    "FlexibilityOffer": {
        "offer_id",
        "provider_id",
        "quantity_kw",
        "price_per_kw_h",
    },
    "AggregatorPortfolio": {
        "aggregator_id",
        "scenario_id",
        "provider_ids",
        "available_capacity_kw",
    },
    "DispatchInstruction": {
        "instruction_id",
        "operation_id",
        "provider_id",
        "selected_kw",
    },
    "SettlementRecord": {
        "settlement_id",
        "instruction_id",
        "provider_id",
        "payment_usd",
    },
    "NetworkConstraint": {
        "constraint_uid",
        "constraint_id",
        "scenario_id",
        "severity_kw",
    },
    "FlexibilityOperationContext": {
        "operation_id",
        "scenario_id",
        "clearing_method",
        "dt_h",
    },
    "FlexibilityOperationValidation": {
        "valid",
        "errors",
        "warnings",
    },
}


def test_canonical_symbol_set_is_importable_and_frozen() -> None:
    """The 10-symbol canonical surface is importable and a subset of __all__."""
    import gridalyn.operations as ops

    for name in FROZEN_SYMBOLS:
        assert hasattr(ops, name), f"frozen symbol missing from facade: {name}"
    assert FROZEN_SYMBOLS <= set(ops.__all__), (
        "frozen symbols absent from gridalyn.operations.__all__: "
        f"{sorted(FROZEN_SYMBOLS - set(ops.__all__))}"
    )


def test_entry_point_signature_is_frozen() -> None:
    """run_flexibility_clearing_operation keeps its exact D-04 signature."""
    # Imported inside the test: touching the entry point eagerly loads
    # pandapower, so this must stay out of the lazy-purity test (Pitfall 1).
    from gridalyn.operations import run_flexibility_clearing_operation as fn

    sig = inspect.signature(fn)
    params = sig.parameters
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values()
    ), "all parameters must remain keyword-only"
    assert set(params) == {
        "requirements",
        "providers",
        "impact",
        "scenario_id",
        "dt_h",
        "clearing_method",
        "model_version_id",
        "study_run_id",
        "max_selected_providers_per_event",
    }
    assert params["clearing_method"].default == "surrogate"
    assert params["model_version_id"].default is None
    assert params["study_run_id"].default is None
    assert params["max_selected_providers_per_event"].default == 1000
    for required in ("requirements", "providers", "impact", "scenario_id", "dt_h"):
        assert params[required].default is inspect.Parameter.empty
    # Under ``from __future__ import annotations`` this is the STRING, unevaluated.
    assert (
        sig.return_annotation
        == "tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]"
    )


def test_importing_operations_loads_no_heavy_optional_deps() -> None:
    """import gridalyn[.operations] must not eagerly load heavy deps (API-03)."""
    # Subprocess isolation makes this ordering-independent: any in-process test
    # that touched a flexibility symbol would have loaded pandapower already
    # (Pitfall 1), so the check runs in a fresh interpreter.
    code = (
        "import sys, gridalyn, gridalyn.operations\n"
        "heavy = [m for m in ('pandapower', 'lightsim2grid', 'cvxpy') "
        "if m in sys.modules]\n"
        "assert heavy == [], heavy\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_frozen_dataclasses_are_frozen_dataclasses() -> None:
    """Each frozen domain type is a frozen dataclass with its required fields."""
    import gridalyn.operations as ops

    for name, required in FROZEN_DATACLASS_REQUIRED_FIELDS.items():
        cls = getattr(ops, name)
        assert dataclasses.is_dataclass(cls), f"{name} is not a dataclass"
        assert cls.__dataclass_params__.frozen is True, f"{name} is not frozen"
        actual = {f.name for f in dataclasses.fields(cls)}
        # Loose: required must be a SUBSET of actual (Phase-3 supersets allowed).
        assert required <= actual, (
            f"{name} dropped required frozen fields: {sorted(required - actual)}"
        )


def test_clearing_is_deterministic() -> None:
    """Canonical clearing yields a unique result, order-independent (CLEAR-03).

    CLEAR-03 landed in Phase 3 sub-merge 2: the existing
    ``sort_values([..., "provider_id"])`` tie-break makes the locational
    selection order reproducible regardless of provider-row build order. This
    asserts that property directly (the two-PYTHONHASHSEED harness in
    ``tests/test_operations_determinism.py`` is the complementary gate).
    """
    import pandas as pd

    from gridalyn.operations import run_flexibility_clearing_operation

    scenario_id = "sc1"
    requirements = pd.DataFrame(
        [{"timestep": 0, "constraint_id": "c1", "required_kw": 50.0}]
    )
    provider_rows = [
        {
            "provider_id": pid,
            "scenario_id": scenario_id,
            "provider_type": "soft_cls_building",
            "available_capacity_kw": 30.0,
            "base_cost_per_kw_h": 1.0,
            "selection_priority": 0,
        }
        for pid in ("p_a", "p_b", "p_c")
    ]
    impact_rows = [
        {
            "provider_id": r["provider_id"],
            "scenario_id": scenario_id,
            "constraint_id": "c1",
            "predicted_deliverability_factor": 1.0,
            "predicted_relief_kw": 30.0,
            "selection_score": 1.0,
        }
        for r in provider_rows
    ]

    def clear(rows: list[dict]) -> str:
        providers = pd.DataFrame(rows)
        impact = pd.DataFrame(impact_rows)
        _events, selections, _report = run_flexibility_clearing_operation(
            requirements=requirements,
            providers=providers,
            impact=impact,
            scenario_id=scenario_id,
            dt_h=1.0,
        )
        cols = sorted(selections.columns)
        ordered = (
            selections.sort_values(["event_id", "provider_id"])
            .reset_index(drop=True)[cols]
        )
        return ordered.to_json(orient="records")

    assert clear(provider_rows) == clear(list(reversed(provider_rows)))

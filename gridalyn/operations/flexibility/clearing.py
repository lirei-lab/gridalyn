"""Operational facade for flexibility clearing."""

from __future__ import annotations

from typing import Any

import pandas as pd

from gridalyn.operations.constraints import (
    build_network_constraint_set,
    summarize_network_constraints,
)
from gridalyn.operations.contracts import (
    build_operation_context,
    validate_flexibility_operation_inputs,
)
from gridalyn.operations.domain import (
    build_aggregator_portfolios,
    build_dispatch_instructions,
    build_settlement_records,
)
from gridalyn.operations.flexibility.kpis import build_operational_kpi_report
from gridalyn.operations.market.locational_clearing import build_locational_clearing


def run_flexibility_clearing_operation(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
    dt_h: float,
    clearing_method: str = "surrogate",
    model_version_id: str | None = None,
    study_run_id: str | None = None,
    max_selected_providers_per_event: int = 1000,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Validate and execute a flexibility clearing operation."""
    context = build_operation_context(
        scenario_id=scenario_id,
        clearing_method=clearing_method,
        dt_h=dt_h,
        requirements=requirements,
        providers=providers,
        impact=impact,
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    validation = validate_flexibility_operation_inputs(
        requirements=requirements,
        providers=providers,
        impact=impact,
        context=context,
    )
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    events, selections, report = build_locational_clearing(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
        dt_h=dt_h,
        clearing_method=context.clearing_method,
        max_selected_providers_per_event=max_selected_providers_per_event,
    )
    report["operation_context"] = context.to_dict()
    report["governance"] = {
        "model_version_id": model_version_id,
        "study_run_id": study_run_id,
    }
    report["validation"] = validation.to_dict()
    report["input_summary"] = _input_summary(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
    )
    dispatch = build_dispatch_instructions(
        selections=selections,
        providers=providers,
        context=context,
    )
    settlement = build_settlement_records(dispatch, dt_h=dt_h)
    portfolios = build_aggregator_portfolios(providers, scenario_id=scenario_id)
    constraints = build_network_constraint_set(
        requirements,
        scenario_id=scenario_id,
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    report["network_constraints"] = summarize_network_constraints(constraints)
    report["operation_domain"] = {
        "portfolio_count": int(len(portfolios)),
        "dispatch_instruction_count": int(len(dispatch)),
        "settlement_record_count": int(len(settlement)),
        "settlement_usd": float(settlement["payment_usd"].sum())
        if not settlement.empty
        else 0.0,
    }
    report["operational_kpis"] = build_operational_kpi_report(
        events=events,
        dispatch_instructions=dispatch,
        settlement_records=settlement,
        constraints=constraints,
        context=context,
        dt_h=dt_h,
    )
    return events, selections, report


def _input_summary(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
) -> dict[str, Any]:
    scenario_providers = providers.loc[
        providers["scenario_id"].astype(str) == str(scenario_id)
    ]
    aggregator_count = (
        int(scenario_providers["aggregator_id"].dropna().nunique())
        if "aggregator_id" in scenario_providers
        else 0
    )
    return {
        "requirement_count": int(len(requirements)),
        "provider_count": int(len(scenario_providers)),
        "impact_row_count": int(len(impact)),
        "constraint_count": int(requirements["constraint_id"].nunique())
        if "constraint_id" in requirements
        else 0,
        "aggregator_count": aggregator_count,
    }

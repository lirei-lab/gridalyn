"""Domain contracts for flexibility operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from gridalyn.operations.flexibility.contracts import FlexibilityOperationContext


@dataclass(frozen=True)
class AggregatorPortfolio:
    """Aggregator portfolio over a scenario-specific provider set."""

    aggregator_id: str
    scenario_id: str
    provider_ids: list[str]
    constraint_zone_ids: list[str]
    available_capacity_kw: float
    soft_provider_count: int
    hard_provider_count: int

    @property
    def provider_count(self) -> int:
        return len(self.provider_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregator_id": self.aggregator_id,
            "scenario_id": self.scenario_id,
            "provider_ids": ";".join(self.provider_ids),
            "provider_count": self.provider_count,
            "constraint_zone_ids": ";".join(self.constraint_zone_ids),
            "constraint_zone_count": len(self.constraint_zone_ids),
            "available_capacity_kw": float(self.available_capacity_kw),
            "soft_provider_count": int(self.soft_provider_count),
            "hard_provider_count": int(self.hard_provider_count),
        }


@dataclass(frozen=True)
class FlexibilityOffer:
    """Provider offer usable by a utility clearing operation."""

    offer_id: str
    provider_id: str
    aggregator_id: str
    scenario_id: str
    provider_type: str
    quantity_kw: float
    price_per_kw_h: float
    constraint_zone_id: str | None
    source_standard: str = "GridalynFlexibilityOperation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "provider_id": self.provider_id,
            "aggregator_id": self.aggregator_id,
            "scenario_id": self.scenario_id,
            "provider_type": self.provider_type,
            "quantity_kw": float(self.quantity_kw),
            "price_per_kw_h": float(self.price_per_kw_h),
            "constraint_zone_id": self.constraint_zone_id,
            "source_standard": self.source_standard,
        }


@dataclass(frozen=True)
class DispatchInstruction:
    """Cleared dispatch action issued to a provider or aggregator."""

    instruction_id: str
    operation_id: str
    event_id: str
    scenario_id: str
    timestep: int
    constraint_id: str
    provider_id: str
    aggregator_id: str | None
    provider_type: str
    dispatch_action: str
    selected_kw: float
    expected_relief_kw: float
    estimated_cost_usd: float
    model_version_id: str | None = None
    study_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction_id": self.instruction_id,
            "operation_id": self.operation_id,
            "event_id": self.event_id,
            "scenario_id": self.scenario_id,
            "timestep": int(self.timestep),
            "constraint_id": self.constraint_id,
            "provider_id": self.provider_id,
            "aggregator_id": self.aggregator_id,
            "provider_type": self.provider_type,
            "dispatch_action": self.dispatch_action,
            "selected_kw": float(self.selected_kw),
            "expected_relief_kw": float(self.expected_relief_kw),
            "estimated_cost_usd": float(self.estimated_cost_usd),
            "model_version_id": self.model_version_id,
            "study_run_id": self.study_run_id,
        }


@dataclass(frozen=True)
class SettlementRecord:
    """Settlement line for a cleared dispatch instruction."""

    settlement_id: str
    instruction_id: str
    operation_id: str
    provider_id: str
    aggregator_id: str | None
    scenario_id: str
    cleared_kw: float
    expected_relief_kw: float
    payment_usd: float
    dt_h: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "settlement_id": self.settlement_id,
            "instruction_id": self.instruction_id,
            "operation_id": self.operation_id,
            "provider_id": self.provider_id,
            "aggregator_id": self.aggregator_id,
            "scenario_id": self.scenario_id,
            "cleared_kw": float(self.cleared_kw),
            "expected_relief_kw": float(self.expected_relief_kw),
            "payment_usd": float(self.payment_usd),
            "dt_h": float(self.dt_h),
        }


def build_aggregator_portfolios(
    providers: pd.DataFrame,
    *,
    scenario_id: str,
) -> pd.DataFrame:
    """Build one portfolio row per aggregator in a scenario provider registry."""
    frame = _scenario_providers(providers, scenario_id).copy()
    if "aggregator_id" not in frame:
        frame["aggregator_id"] = f"aggregator:{scenario_id}:unassigned"
    frame["aggregator_id"] = frame["aggregator_id"].fillna(
        f"aggregator:{scenario_id}:unassigned"
    )

    rows: list[dict[str, Any]] = []
    for aggregator_id, group in frame.groupby("aggregator_id", sort=True):
        provider_types = group["provider_type"].astype(str)
        portfolio = AggregatorPortfolio(
            aggregator_id=str(aggregator_id),
            scenario_id=str(scenario_id),
            provider_ids=sorted(group["provider_id"].astype(str).tolist()),
            constraint_zone_ids=sorted(
                str(value)
                for value in group.get("constraint_zone_id", pd.Series(dtype=str))
                .dropna()
                .unique()
            ),
            available_capacity_kw=float(group["available_capacity_kw"].astype(float).sum()),
            soft_provider_count=int((provider_types == "soft_cls_building").sum()),
            hard_provider_count=int((provider_types == "hard_cls_ev").sum()),
        )
        rows.append(portfolio.to_dict())
    return pd.DataFrame(rows)


def build_provider_offers(
    providers: pd.DataFrame,
    *,
    scenario_id: str,
) -> pd.DataFrame:
    """Convert provider registry rows into a scenario offer book."""
    frame = _scenario_providers(providers, scenario_id)
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        provider_id = str(row["provider_id"])
        offer = FlexibilityOffer(
            offer_id=f"offer:{scenario_id}:{provider_id}",
            provider_id=provider_id,
            aggregator_id=str(
                row.get("aggregator_id") or f"aggregator:{scenario_id}:unassigned"
            ),
            scenario_id=str(scenario_id),
            provider_type=str(row["provider_type"]),
            quantity_kw=float(row["available_capacity_kw"]),
            price_per_kw_h=float(row["base_cost_per_kw_h"]),
            constraint_zone_id=(
                str(row["constraint_zone_id"])
                if pd.notna(row.get("constraint_zone_id"))
                else None
            ),
        )
        rows.append(offer.to_dict())
    return pd.DataFrame(rows)


def build_dispatch_instructions(
    *,
    selections: pd.DataFrame,
    providers: pd.DataFrame,
    context: FlexibilityOperationContext,
) -> pd.DataFrame:
    """Promote clearing selections into dispatch instructions."""
    if selections.empty:
        return pd.DataFrame(columns=_dispatch_columns())
    provider_lookup = _scenario_providers(providers, context.scenario_id)[
        ["provider_id", "aggregator_id"]
        if "aggregator_id" in providers
        else ["provider_id"]
    ].drop_duplicates("provider_id")
    if "aggregator_id" not in provider_lookup:
        provider_lookup["aggregator_id"] = f"aggregator:{context.scenario_id}:unassigned"
    merged = selections.merge(provider_lookup, on="provider_id", how="left")

    rows: list[dict[str, Any]] = []
    for row in merged.to_dict("records"):
        instruction = DispatchInstruction(
            instruction_id=_stable_id(
                "dispatch",
                context.operation_id,
                row["event_id"],
                row["provider_id"],
            ),
            operation_id=context.operation_id,
            event_id=str(row["event_id"]),
            scenario_id=str(row["scenario_id"]),
            timestep=int(row["timestep"]),
            constraint_id=str(row["constraint_id"]),
            provider_id=str(row["provider_id"]),
            aggregator_id=(
                str(row["aggregator_id"])
                if pd.notna(row.get("aggregator_id"))
                else None
            ),
            provider_type=str(row["provider_type"]),
            dispatch_action=_dispatch_action(str(row["provider_type"])),
            selected_kw=float(row["selected_kw"]),
            expected_relief_kw=float(row["expected_relief_kw"]),
            estimated_cost_usd=float(row.get("estimated_cost", 0.0) or 0.0),
            model_version_id=context.model_version_id,
            study_run_id=context.study_run_id,
        )
        rows.append(instruction.to_dict())
    return pd.DataFrame(rows, columns=_dispatch_columns())


def build_settlement_records(
    dispatch_instructions: pd.DataFrame,
    *,
    dt_h: float,
) -> pd.DataFrame:
    """Build settlement records from dispatch instructions."""
    if dispatch_instructions.empty:
        return pd.DataFrame(columns=_settlement_columns())
    rows: list[dict[str, Any]] = []
    for row in dispatch_instructions.to_dict("records"):
        record = SettlementRecord(
            settlement_id=_stable_id(
                "settlement",
                row["operation_id"],
                row["instruction_id"],
            ),
            instruction_id=str(row["instruction_id"]),
            operation_id=str(row["operation_id"]),
            provider_id=str(row["provider_id"]),
            aggregator_id=(
                str(row["aggregator_id"])
                if pd.notna(row.get("aggregator_id"))
                else None
            ),
            scenario_id=str(row["scenario_id"]),
            cleared_kw=float(row["selected_kw"]),
            expected_relief_kw=float(row["expected_relief_kw"]),
            payment_usd=float(row.get("estimated_cost_usd", 0.0) or 0.0),
            dt_h=float(dt_h),
        )
        rows.append(record.to_dict())
    return pd.DataFrame(rows, columns=_settlement_columns())


def _scenario_providers(providers: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    return providers.loc[providers["scenario_id"].astype(str) == str(scenario_id)].copy()


def _dispatch_action(provider_type: str) -> str:
    if provider_type == "hard_cls_ev":
        return "hard_cls_interrupt"
    return "soft_cls_limit"


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps([str(part) for part in parts], sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def _dispatch_columns() -> list[str]:
    return [
        "instruction_id",
        "operation_id",
        "event_id",
        "scenario_id",
        "timestep",
        "constraint_id",
        "provider_id",
        "aggregator_id",
        "provider_type",
        "dispatch_action",
        "selected_kw",
        "expected_relief_kw",
        "estimated_cost_usd",
        "model_version_id",
        "study_run_id",
    ]


def _settlement_columns() -> list[str]:
    return [
        "settlement_id",
        "instruction_id",
        "operation_id",
        "provider_id",
        "aggregator_id",
        "scenario_id",
        "cleared_kw",
        "expected_relief_kw",
        "payment_usd",
        "dt_h",
    ]

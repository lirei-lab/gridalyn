"""Closed vocabularies of the flexibility-operations surface.

Until 2026-09-11 every value below travelled as a free ``str``:
``provider_type``, ``dispatch_action``, ``clearing_method``, ``market_role``,
``operation_type`` and ``status`` on the frozen operations dataclasses. One set
was checked (``clearing_method``), and two unknowns fell through in silence:
``_dispatch_action`` mapped every provider type that was not ``hard_cls_ev`` to
``soft_cls_limit``, and clearing selected a provider of an unknown type while
counting its kilowatts as neither soft nor hard.

Measured across ``gridalyn/``, ``projects/`` and ``tests/`` before closing
them: ``provider_type`` takes exactly ``soft_cls_building`` and
``hard_cls_ev``; ``operation_type`` only ``flexibility_clearing``; an
``OperationRun`` status only ``completed``. Each set below is that measurement,
so widening one is a deliberate edit here, made together with the producer that
writes the new value.

The aliases are for the type checker. The ``parse_*`` functions are the runtime
boundary where a value read from a DataFrame, a JSON document or a CLI becomes
one of them, and the frozen dataclasses call them on construction, so an
unknown value is refused whether it arrives through typed code or a table row.

Lower layers that emit these strings (``gridalyn.assets.modeling.scenarios``,
the network-impact analytics, the semantic flexibility capability) restate
them rather than import them: imports flow downward only.
"""

from __future__ import annotations

from typing import Literal, TypeVar, get_args

ProviderType = Literal["soft_cls_building", "hard_cls_ev"]
DispatchAction = Literal["soft_cls_limit", "hard_cls_interrupt"]
ClearingMethod = Literal["surrogate", "topology"]
MarketRole = Literal["dso_flexibility_clearing"]
OperationType = Literal["flexibility_clearing"]
OperationStatus = Literal["completed"]

PROVIDER_TYPES: tuple[ProviderType, ...] = get_args(ProviderType)
DISPATCH_ACTIONS: tuple[DispatchAction, ...] = get_args(DispatchAction)
CLEARING_METHODS: tuple[ClearingMethod, ...] = get_args(ClearingMethod)
MARKET_ROLES: tuple[MarketRole, ...] = get_args(MarketRole)
OPERATION_TYPES: tuple[OperationType, ...] = get_args(OperationType)
OPERATION_STATUSES: tuple[OperationStatus, ...] = get_args(OperationStatus)

#: The one dispatch action each provider type receives. Exhaustive by
#: construction: a new provider type without an action fails its gate test.
DISPATCH_ACTION_BY_PROVIDER_TYPE: dict[ProviderType, DispatchAction] = {
    "soft_cls_building": "soft_cls_limit",
    "hard_cls_ev": "hard_cls_interrupt",
}

_Term = TypeVar("_Term", bound=str)


def _parse_term(value: object, allowed: tuple[_Term, ...], field: str) -> _Term:
    for candidate in allowed:
        if value == candidate:
            return candidate
    raise ValueError(
        f"{field} must be one of {', '.join(repr(term) for term in allowed)}; "
        f"found {value!r}"
    )


def parse_provider_type(value: object) -> ProviderType:
    """Return ``value`` as a provider type, refusing anything outside the set.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, PROVIDER_TYPES, "provider_type")


def parse_dispatch_action(value: object) -> DispatchAction:
    """Return ``value`` as a dispatch action, refusing anything outside the set.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, DISPATCH_ACTIONS, "dispatch_action")


def parse_clearing_method(value: object) -> ClearingMethod:
    """Return ``value`` as a clearing method. Exact match: no case folding.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, CLEARING_METHODS, "clearing_method")


def parse_market_role(value: object) -> MarketRole:
    """Return ``value`` as a market role, refusing anything outside the set.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, MARKET_ROLES, "market_role")


def parse_operation_type(value: object) -> OperationType:
    """Return ``value`` as an operation type, refusing anything outside the set.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, OPERATION_TYPES, "operation_type")


def parse_operation_status(value: object) -> OperationStatus:
    """Return ``value`` as an operation-run status, refusing anything else.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, OPERATION_STATUSES, "status")


__all__ = [
    "CLEARING_METHODS",
    "DISPATCH_ACTIONS",
    "DISPATCH_ACTION_BY_PROVIDER_TYPE",
    "MARKET_ROLES",
    "OPERATION_STATUSES",
    "OPERATION_TYPES",
    "PROVIDER_TYPES",
    "ClearingMethod",
    "DispatchAction",
    "MarketRole",
    "OperationStatus",
    "OperationType",
    "ProviderType",
    "parse_clearing_method",
    "parse_dispatch_action",
    "parse_market_role",
    "parse_operation_status",
    "parse_operation_type",
    "parse_provider_type",
]

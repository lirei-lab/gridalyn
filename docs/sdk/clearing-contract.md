# Operations Clearing & Settlement Contract

`run_flexibility_clearing_operation`, reachable as
`from gridalyn.operations import run_flexibility_clearing_operation`, is **the
single documented way** to clear and settle a flexibility operation. It validates
inputs, builds the operation context, runs locational clearing, and produces
dispatch and settlement tables plus an operational KPI report. Studies, tests,
and applications should call this entry point and the frozen domain types below —
nothing else in `gridalyn.operations` is part of this stable surface.

This contract is **frozen**: a later consolidation phase will not move the
symbols or signature recorded here. It is enforced by
`tests/test_operations_contract.py`, which fails on any drift of the frozen set
or the entry-point signature.

## Frozen Surface

These ten symbols are the canonical clearing/settlement contract. All are
importable directly from `gridalyn.operations` (via the lazy `__getattr__`
facade — see [Stable Facade](public-contract.md#stable-facade)).

| Symbol | Kind | Owning module |
| --- | --- | --- |
| `run_flexibility_clearing_operation` | function (entry point) | `clearing/selection.py` |
| `build_operation_context` | function (constructor) | `contracts.py` |
| `validate_flexibility_operation_inputs` | function (validator) | `contracts.py` |
| `FlexibilityOffer` | frozen dataclass | `domain.py` |
| `AggregatorPortfolio` | frozen dataclass | `domain.py` |
| `DispatchInstruction` | frozen dataclass | `domain.py` |
| `SettlementRecord` | frozen dataclass | `domain.py` |
| `NetworkConstraint` | frozen dataclass | `constraints.py` |
| `FlexibilityOperationContext` | frozen dataclass | `contracts.py` |
| `FlexibilityOperationValidation` | frozen dataclass | `contracts.py` |

The seven frozen dataclasses are guaranteed to be `@dataclass(frozen=True)` and
to keep their core identifying fields. Field sets may grow in later phases (a
superset is allowed); the contract test pins a stable required-field **subset**,
never exact field equality, so additive extensions do not break consumers.

## Entry-Point Signature

The entry-point signature is frozen exactly as-is — no typed-result refactor or
signature cleanup is part of this contract.

```python
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
```

- **All parameters are keyword-only** (note the leading `*`).
- **Required (no default):** `requirements`, `providers`, `impact`,
  `scenario_id`, `dt_h`.
- **Defaults:** `clearing_method="surrogate"`, `model_version_id=None`,
  `study_run_id=None`, `max_selected_providers_per_event=1000`.
- **Return:** `tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]`, i.e.
  `(events_df, selections_df, report_dict)`.

## Excluded: DER-Voltage Boundary

The DER-voltage dispatch symbols belong to the out-of-scope
`der_voltage_optimization` study and are **not** part of this frozen
flexibility-market contract. They remain exported from `gridalyn.operations`
exactly as-is (that study depends on them), but consumers of the clearing
contract must not treat them as part of this surface:

| Symbol | Kind |
| --- | --- |
| `DERVoltageDispatchConfig` | dataclass |
| `DERVoltageDispatchResult` | dataclass |
| `run_der_voltage_dispatch` | function |
| `summarize_der_voltage_dispatch` | function |
| `write_der_voltage_dispatch_figure` | function |

## Staged-pipeline API

Alongside the frozen single entry point, `gridalyn.operations` exposes a small
set of **staged-pipeline** building blocks, reachable the same way — directly
via `from gridalyn.operations import ...` (the lazy `__getattr__` facade).
`run_flexibility_clearing_operation` remains the **frozen** single entry point;
these are an additive convenience tier, not a replacement.

!!! warning "Corrected 2026-08-15"

    This page previously described the staged tier as "the additive, canonical
    public surface that the `ev_hosting_flex` proving-ground study composes",
    and called the symbols "blessed, citable". That justification was false:
    `ev_hosting_flex` reaches `clearing.selection`, and neither `selection` nor
    `artifacts` reached `engine_mode` through any import path. Four of the
    symbols listed here — `build_congestion_forecast`,
    `prepare_cls_market_replay_context`, `summarize_stage2_realizations` and
    `run_cls_capacity_allocation` — were **retired with their modules** on
    2026-08-15 as orphans of the `flexibility_cls` retirement. Archived at tag
    `archive/engine-mode-clearing`. The table below lists what remains.

| Symbol | Kind | Stage role |
| --- | --- | --- |
| `validate_cls_output_consistency` | function | Validate cross-stage CLS output consistency |
| `materialize_flexibility_operation_artifacts` | function | Materialize governed operation artifacts |

This tier is **additive and may grow**; unlike the frozen surface, the staged
API is not pinned against drift by the contract test — it is documented as the
supported public composition surface for staged studies.

The pure serialization/labeling helpers `json_default`, `relpath`, and
`scenario_label` are **not** part of this surface. They are study-local helpers,
not SDK public API, and must not be imported from `gridalyn.operations`.

## Internal / Provisional (Not Frozen)

The `gridalyn.operations` (see `clearing/selection.py`, `settlement.py`, `verification.py`, `clearing/allocation.py`) builders (e.g. `build_locational_clearing`,
`build_provider_registry`, `build_flexibility_clearing_scorecard`,
`build_locational_clearing_verification_report`, `apply_spatial_cls`, and the
related scorecard / verification / spatial helpers) are **interior and
provisional**. They are intentionally left unfrozen so a later consolidation
phase can merge, rename, or drop them freely. Consumers must **not** depend on
them as a stable surface — reach the clearing path only through
`run_flexibility_clearing_operation`.

## Determinism Promises

The canonical clearing contract **promises** a deterministic, unique clearing
result, and these guarantees are **enforced** — the CLEAR-03 guarantee:

- a **total sort with an explicit tie-break** so provider selection ordering is
  unique and reproducible;
- a **fixed, ordered build order** for events, selections, and settlement rows;
- a **pinned solver with pinned tolerances** so numerical results are stable
  across runs and environments.

`test_clearing_is_deterministic` in `tests/test_operations_contract.py` asserts
this and passes; it is no longer an `xfail` placeholder.

## See Also

- [SDK Public Contract](public-contract.md) — the SDK-wide stable import surface.
- [Markets And Transactions](../flexibility/clearing.md) — narrative guide to the
  clearing path this contract freezes.

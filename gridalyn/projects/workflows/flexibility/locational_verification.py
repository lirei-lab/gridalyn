"""Replay locational clearing selections through pandapower."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import (
    ArtifactLayout,
    ReportMetadata,
    file_reference,
    write_report,
)
from gridalyn.operations import (
    apply_locational_selections,
    build_locational_clearing_verification_report,
    write_locational_verification_outputs,
)
from gridalyn.projects.workflows.flexibility.spatial_powerflow_validation import (
    _load_s4_inputs,
    _powerflow_metrics,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__: in an installed wheel that resolves to
# site-packages, where reads return {} and writes land inside the package.
_DEFAULT_ROOT = Path(".")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def _clearing_constraint_ids(clearing_report: dict[str, Any]) -> list[str]:
    """Read constraint ids from a clearing report, old or new envelope.

    The governed envelope (report-contract audit §5.5) carries them under
    ``summary.constraint_ids``; the pre-conversion flat report carried them at
    the top level. Returns an empty list when neither location is present so
    the caller can fall back to deriving them from the selections table.
    """
    summary = clearing_report.get("summary")
    if isinstance(summary, dict) and summary.get("constraint_ids"):
        return [str(item) for item in summary["constraint_ids"]]
    if clearing_report.get("constraint_ids"):
        return [str(item) for item in clearing_report["constraint_ids"]]
    return []


def _comparison_validation(comparison: dict[str, Any]) -> dict[str, Any]:
    """Derive the contract ``validation`` block from the replay comparison.

    Errors when the cleared case creates more overloads than the unmanaged
    one — the replay then contradicts the clearing's purpose. Warnings when a
    loading or voltage metric regresses without adding overloads.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if comparison["trafo_overload_delta"] > 0:
        errors.append(
            "locational clearing increased transformer overload count by "
            f"{comparison['trafo_overload_delta']} vs unmanaged"
        )
    if comparison["line_overload_delta"] > 0:
        errors.append(
            "locational clearing increased line overload count by "
            f"{comparison['line_overload_delta']} vs unmanaged"
        )
    if comparison["trafo_max_loading_reduction_pctpt"] < 0:
        warnings.append(
            "transformer max loading worsened by "
            f"{-comparison['trafo_max_loading_reduction_pctpt']:.3f} pctpt"
        )
    if comparison["v_min_improvement_pu"] < 0:
        warnings.append(
            f"minimum voltage worsened by {-comparison['v_min_improvement_pu']:.4f} pu"
        )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def generate_report(
    *,
    root: Path,
    provider_path: Path,
    selections_path: Path,
    clearing_report_path: Path,
    dispatch_out: Path,
    report_out: Path,
    scenario_id: str,
    cache_dir: Path,
    market_dispatch_path: Path,
) -> dict[str, Any]:
    """Generate a pandapower verification report for locational clearing.

    Args:
        root: Workspace root containing ``instances/default/digital_twin``;
            paths in the report are recorded relative to it.
        provider_path: Provider registry parquet.
        selections_path: Locational clearing selections parquet.
        clearing_report_path: Clearing report JSON (governed envelope or the
            pre-conversion flat shape).
        dispatch_out: Destination for the dispatch parquet artifact.
        report_out: Destination for the governed verification report.
        scenario_id: Scenario to verify; only ``"S4"`` is supported.
        cache_dir: Digital-twin cache directory holding the pandapower net.
        market_dispatch_path: Market dispatch timeseries parquet.

    Returns:
        The governed report payload written to ``report_out``.

    Raises:
        FileNotFoundError: If ``root`` holds no digital-twin artifact tree —
            the guard that keeps an installed package from reading empty
            inputs and writing artifacts outside a workspace.
        ValueError: If ``scenario_id`` is not ``"S4"``.
    """
    root = root.resolve()
    layout = ArtifactLayout(root)
    if not layout.digital_twin.is_dir():
        raise FileNotFoundError(
            f"{layout.digital_twin}: no digital-twin artifact tree under root "
            f"{root}; the verification report would be built from empty inputs "
            "and written outside a workspace. Run from a workspace root "
            "containing instances/default/digital_twin, or pass "
            "root=<workspace> (--root on the command line)."
        )
    if scenario_id != "S4":
        raise ValueError(
            "Current powerflow verification loader supports scenario_id='S4'"
        )

    providers = pd.read_parquet(provider_path)
    selections = pd.read_parquet(selections_path)
    clearing_report = _load_json(clearing_report_path)

    _buildings, _registry, building_kw, ev_kw, _soft_kw, _hard_kw, _rebound_kw = (
        _load_s4_inputs(
            cache_dir=cache_dir,
            market_dispatch_path=market_dispatch_path,
        )
    )
    dt_h = 5.0 / 60.0
    if building_kw.shape[0] > 1:
        dt_h = 24.0 / float(building_kw.shape[0])

    result = apply_locational_selections(
        building_kw=building_kw,
        ev_kw=ev_kw,
        selections=selections,
        providers=providers,
        dt_h=dt_h,
    )

    unmanaged_p_total_mw = (building_kw + ev_kw) / 1000.0
    locational_p_total_mw = (
        result["managed_building_kw"] + result["managed_ev_kw"]
    ) / 1000.0
    unmanaged_q_mvar = (building_kw / 1000.0) * 0.1
    locational_q_mvar = (result["managed_building_kw"] / 1000.0) * 0.1

    case_metrics = {
        "unmanaged": _powerflow_metrics(
            "unmanaged",
            unmanaged_p_total_mw,
            unmanaged_q_mvar,
            cache_dir=cache_dir,
        ),
        "locational_clearing": _powerflow_metrics(
            "locational_clearing",
            locational_p_total_mw,
            locational_q_mvar,
            cache_dir=cache_dir,
        ),
    }
    clearing_summary = {
        **result["summary"],
        "rebound_delivered_mwh": 0.0,
    }
    constraint_ids = _clearing_constraint_ids(clearing_report) or sorted(
        selections["constraint_id"].dropna().astype(str).unique()
    )

    verification = build_locational_clearing_verification_report(
        scenario_id=scenario_id,
        clearing_summary=clearing_summary,
        case_metrics=case_metrics,
        constraint_ids=list(constraint_ids),
    )
    outputs = write_locational_verification_outputs(
        dispatch=result["dispatch"],
        dispatch_path=dispatch_out,
        report_path=report_out,
    )
    return write_report(
        report_out,
        metadata=ReportMetadata(
            report_id="locational_clearing_verification",
            source_domain="operations",
        ),
        inputs=[
            file_reference(path, root)
            for path in (
                provider_path,
                selections_path,
                clearing_report_path,
                cache_dir,
                market_dispatch_path,
            )
        ],
        artifacts=[file_reference(outputs["dispatch"], root)],
        summary={
            "scenario_id": verification["scenario_id"],
            "constraint_ids": verification["constraint_ids"],
            "authority": verification["validation"]["authority"],
            "policy": verification["validation"]["policy"],
            "dispatch": verification["dispatch"],
            "cases": verification["cases"],
            "comparisons": verification["comparisons"],
        },
        validation=_comparison_validation(
            verification["comparisons"]["locational_clearing_vs_unmanaged"]
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help=(
            "Workspace root containing instances/default/digital_twin "
            "(default: current directory)."
        ),
    )
    parser.add_argument("--provider-path", type=Path, default=None)
    parser.add_argument("--selections-path", type=Path, default=None)
    parser.add_argument("--clearing-report-path", type=Path, default=None)
    parser.add_argument("--dispatch-out", type=Path, default=None)
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--market-dispatch-path", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    layout = ArtifactLayout(args.root.resolve())
    flexibility = layout.flexibility
    report = generate_report(
        root=args.root,
        provider_path=args.provider_path or flexibility / "provider_registry.parquet",
        selections_path=args.selections_path
        or flexibility / "locational_clearing_selections.parquet",
        clearing_report_path=args.clearing_report_path
        or flexibility / "locational_flexibility_clearing_report.json",
        dispatch_out=args.dispatch_out
        or flexibility / "locational_clearing_dispatch.parquet",
        report_out=args.report_out
        or flexibility / "locational_clearing_verification_report.json",
        scenario_id=args.scenario_id,
        cache_dir=args.cache_dir or layout.cache,
        market_dispatch_path=args.market_dispatch_path
        or flexibility / "market_dispatch_timeseries.parquet",
    )
    print(
        json.dumps(
            {
                "scenario_id": report["summary"]["scenario_id"],
                "constraint_ids": report["summary"]["constraint_ids"],
                "dispatch": report["summary"]["dispatch"],
                "comparisons": report["summary"]["comparisons"],
                "artifacts": report["artifacts"],
                "validation": report["validation"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

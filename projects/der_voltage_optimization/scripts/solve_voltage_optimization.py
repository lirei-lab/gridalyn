"""Run Gridalyn DER voltage dispatch and write project artifacts."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.operations import (
    DERVoltageDispatchConfig,
    run_der_voltage_dispatch,
    summarize_der_voltage_dispatch,
    write_der_voltage_dispatch_figure,
)

from network_model import build_der_feeder


PROJECT_NAME = "der_voltage_optimization"
V_MIN = 0.95
V_MAX = 1.05
PERTURBATION_MW = 0.05


def _ensure_outputs() -> None:
    for relative in (
        "outputs/data",
        "outputs/figures",
        "outputs/operations",
        "outputs/reports",
        "outputs/cache",
    ):
        Path(relative).mkdir(parents=True, exist_ok=True)


def main() -> int:
    _ensure_outputs()
    der_assets_path = Path("outputs/data/der_assets.csv")
    der_assets = pd.read_csv(der_assets_path)
    result = run_der_voltage_dispatch(
        build_der_feeder,
        der_assets,
        DERVoltageDispatchConfig(
            voltage_min_pu=V_MIN,
            voltage_max_pu=V_MAX,
            perturbation_mw=PERTURBATION_MW,
        ),
    )

    sensitivity_path = Path("outputs/data/voltage_sensitivity_matrix.csv")
    dispatch_path = Path("outputs/operations/der_dispatch.csv")
    verification_path = Path("outputs/data/pandapower_verification.csv")
    result.sensitivity.to_csv(sensitivity_path, index=False)
    result.dispatch.to_csv(dispatch_path, index=False)
    result.verification.to_csv(verification_path, index=False)
    figure_path = write_der_voltage_dispatch_figure(
        result.verification,
        result.dispatch,
        "outputs/figures/der_voltage_optimization.png",
        voltage_max_pu=V_MAX,
    )

    summary = summarize_der_voltage_dispatch(result)
    max_after = float(summary["verified_max_voltage_after_pu"])
    valid = bool(
        result.optimized_converged
        and result.optimization_metadata["solver_status"] in {"optimal", "optimal_inaccurate"}
        and max_after <= V_MAX + 1e-3
    )
    write_report(
        Path("outputs/reports/der_voltage_optimization_report.json"),
        metadata=ReportMetadata(
            report_id="der_voltage_optimization_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(der_assets_path),
            {"name": "gridalyn_der_voltage_dispatch_model", "type": "optimization_model"},
        ],
        artifacts=[
            file_reference(sensitivity_path),
            file_reference(dispatch_path),
            file_reference(verification_path),
            file_reference(figure_path),
        ],
        summary=summary,
        validation={
            "valid": valid,
            "errors": [] if valid else ["optimized pandapower verification exceeded voltage limit"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run Gridalyn DER voltage dispatch and write project artifacts."""

from __future__ import annotations

import pandas as pd
from network_model import build_der_feeder

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.operations import (
    DERVoltageDispatchConfig,
    run_der_voltage_dispatch,
    summarize_der_voltage_dispatch,
    write_der_voltage_dispatch_figure,
)
from gridalyn.projects.scripting import project_script

V_MIN = 0.95
V_MAX = 1.05
PERTURBATION_MW = 0.05


def main() -> int:
    script = project_script()
    require_capabilities("sim", context="the DER voltage optimization")
    der_assets_path = script.data_dir / "der_assets.csv"
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

    sensitivity_path = script.data_dir / "voltage_sensitivity_matrix.csv"
    dispatch_path = script.operations_dir / "der_dispatch.csv"
    verification_path = script.data_dir / "pandapower_verification.csv"
    result.sensitivity.to_csv(sensitivity_path, index=False)
    result.dispatch.to_csv(dispatch_path, index=False)
    result.verification.to_csv(verification_path, index=False)
    figure_path = write_der_voltage_dispatch_figure(
        result.verification,
        result.dispatch,
        script.figures_dir / "der_voltage_optimization.png",
        voltage_max_pu=V_MAX,
    )

    summary = summarize_der_voltage_dispatch(result)
    max_after = float(summary["verified_max_voltage_after_pu"])
    valid = bool(
        result.optimized_converged
        and result.optimization_metadata["solver_status"]
        in {"optimal", "optimal_inaccurate"}
        and max_after <= V_MAX + 1e-3
    )
    script.write_report(
        "der_voltage_optimization_report",
        inputs=[
            script.file_reference(der_assets_path),
            {
                "name": "gridalyn_der_voltage_dispatch_model",
                "type": "optimization_model",
            },
        ],
        artifacts=[
            script.file_reference(sensitivity_path),
            script.file_reference(dispatch_path),
            script.file_reference(verification_path),
            script.file_reference(figure_path),
        ],
        summary=summary,
        validation={
            "valid": valid,
            "errors": (
                []
                if valid
                else ["optimized pandapower verification exceeded voltage limit"]
            ),
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

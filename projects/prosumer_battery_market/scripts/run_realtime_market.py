"""Run the prosumer real-time market through the Gridalyn operations API."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridalyn.operations import (
    ProsumerRealtimeMarketConfig,
    build_prosumer_realtime_market_summary,
    run_prosumer_realtime_market,
    write_prosumer_market_dispatch_figure,
)
from gridalyn.projects.scripting import ProjectScript, project_script

from network_model import build_synthetic_feeder


def _market_config(script: ProjectScript) -> ProsumerRealtimeMarketConfig:
    """Market parameters; the load shape comes from the declared loadGeneration."""
    # pv_factors is the single source of truth for the interval count; deriving
    # interval_count from its length keeps the two in lockstep (avoids the
    # magic-number duplication flagged in review).
    pv_factors = (
        0.34,
        0.30,
        0.25,
        0.19,
        0.13,
        0.08,
        0.04,
        0.02,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    return ProsumerRealtimeMarketConfig(
        interval_minutes=5,
        interval_count=len(pv_factors),
        import_limit_mw=2.55,
        forecast_horizon_intervals=4,
        reserve_fraction=0.55,
        locational_credit_usd_per_mwh=2.0,
        scarcity_adder_usd_per_mwh=6.0,
        load_multipliers=tuple(
            round(float(value), 4)
            for value in script.load_generated_load_multipliers()
        ),
        pv_factors=pv_factors,
        load_forecast_bias_by_lead=(0.0, 0.006, -0.004, 0.01),
        pv_forecast_bias_by_lead=(0.0, -0.015, 0.01, -0.02),
    )


def _write_tables(script: ProjectScript, result) -> dict[str, Path]:
    paths = {
        "clearing": script.operations_dir / "realtime_market_clearing.csv",
        "dispatch": script.operations_dir / "battery_dispatch.csv",
        "forecast": script.data_dir / "realtime_market_forecast.csv",
        "offers": script.operations_dir / "realtime_market_offers.csv",
        "powerflow": script.data_dir / "realtime_powerflow_results.csv",
    }
    result.clearing.to_csv(paths["clearing"], index=False)
    result.dispatch.to_csv(paths["dispatch"], index=False)
    result.forecast.to_csv(paths["forecast"], index=False)
    result.offers.to_csv(paths["offers"], index=False)
    result.powerflow.to_csv(paths["powerflow"], index=False)
    return paths


def main() -> int:
    script = project_script()
    market_config = _market_config(script)
    prosumer_path = script.data_dir / "prosumers.csv"
    prosumers = pd.read_csv(prosumer_path)
    result = run_prosumer_realtime_market(
        prosumers=prosumers,
        build_feeder=build_synthetic_feeder,
        config=market_config,
    )
    paths = _write_tables(script, result)
    figure_path = write_prosumer_market_dispatch_figure(
        result.clearing,
        script.figures_dir / "prosumer_market_dispatch.png",
        import_limit_mw=market_config.import_limit_mw,
    )
    valid = bool(
        result.powerflow["converged"].all()
        and result.clearing["cleared_mw"].sum() > 0
    )

    script.write_report(
        "prosumer_realtime_market_report",
        inputs=[
            script.file_reference(prosumer_path),
            script.file_reference(paths["forecast"]),
            {
                "name": "real_time_import_limit",
                "type": "market_parameter",
                "import_limit_mw": market_config.import_limit_mw,
            },
            {
                "name": "market_algorithm",
                "type": "published_method_family",
                "algorithm": "rolling_horizon_uniform_price_auction",
                "forecast_horizon_intervals": market_config.forecast_horizon_intervals,
            },
            {
                "name": "loadGeneration",
                "type": "generated_load_profile",
                **dict(script.input("loadGeneration")),
            },
        ],
        artifacts=[
            script.file_reference(paths["clearing"]),
            script.file_reference(paths["dispatch"]),
            script.file_reference(paths["offers"]),
            script.file_reference(paths["powerflow"]),
            script.file_reference(figure_path),
        ],
        summary=build_prosumer_realtime_market_summary(result, config=market_config),
        validation={
            "valid": valid,
            "errors": []
            if valid
            else ["market did not clear any reduction or a power flow failed"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

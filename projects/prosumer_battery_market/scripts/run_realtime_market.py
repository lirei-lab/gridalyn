"""Run the prosumer real-time market through the Gridalyn operations API."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.operations.market import (
    ProsumerRealtimeMarketConfig,
    build_prosumer_realtime_market_summary,
    run_prosumer_realtime_market,
    write_prosumer_market_dispatch_figure,
)

from network_model import build_synthetic_feeder


PROJECT_NAME = "prosumer_battery_market"

MARKET_CONFIG = ProsumerRealtimeMarketConfig(
    interval_minutes=5,
    interval_count=12,
    import_limit_mw=2.55,
    forecast_horizon_intervals=4,
    reserve_fraction=0.55,
    locational_credit_usd_per_mwh=2.0,
    scarcity_adder_usd_per_mwh=6.0,
    load_multipliers=(
        0.98,
        1.03,
        1.08,
        1.12,
        1.17,
        1.22,
        1.24,
        1.21,
        1.16,
        1.10,
        1.04,
        0.99,
    ),
    pv_factors=(
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
    ),
    load_forecast_bias_by_lead=(0.0, 0.006, -0.004, 0.01),
    pv_forecast_bias_by_lead=(0.0, -0.015, 0.01, -0.02),
)


def _write_tables(result) -> dict[str, Path]:
    paths = {
        "clearing": Path("outputs/operations/realtime_market_clearing.csv"),
        "dispatch": Path("outputs/operations/battery_dispatch.csv"),
        "forecast": Path("outputs/data/realtime_market_forecast.csv"),
        "offers": Path("outputs/operations/realtime_market_offers.csv"),
        "powerflow": Path("outputs/data/realtime_powerflow_results.csv"),
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    result.clearing.to_csv(paths["clearing"], index=False)
    result.dispatch.to_csv(paths["dispatch"], index=False)
    result.forecast.to_csv(paths["forecast"], index=False)
    result.offers.to_csv(paths["offers"], index=False)
    result.powerflow.to_csv(paths["powerflow"], index=False)
    return paths


def main() -> int:
    prosumer_path = Path("outputs/data/prosumers.csv")
    prosumers = pd.read_csv(prosumer_path)
    result = run_prosumer_realtime_market(
        prosumers=prosumers,
        build_feeder=build_synthetic_feeder,
        config=MARKET_CONFIG,
    )
    paths = _write_tables(result)
    figure_path = write_prosumer_market_dispatch_figure(
        result.clearing,
        "outputs/figures/prosumer_market_dispatch.png",
        import_limit_mw=MARKET_CONFIG.import_limit_mw,
    )
    valid = bool(
        result.powerflow["converged"].all()
        and result.clearing["cleared_mw"].sum() > 0
    )

    write_report(
        Path("outputs/reports/prosumer_realtime_market_report.json"),
        metadata=ReportMetadata(
            report_id="prosumer_realtime_market_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(prosumer_path),
            file_reference(paths["forecast"]),
            {
                "name": "real_time_import_limit",
                "type": "market_parameter",
                "import_limit_mw": MARKET_CONFIG.import_limit_mw,
            },
            {
                "name": "market_algorithm",
                "type": "published_method_family",
                "algorithm": "rolling_horizon_uniform_price_auction",
                "forecast_horizon_intervals": MARKET_CONFIG.forecast_horizon_intervals,
            },
        ],
        artifacts=[
            file_reference(paths["clearing"]),
            file_reference(paths["dispatch"]),
            file_reference(paths["offers"]),
            file_reference(paths["powerflow"]),
            file_reference(figure_path),
        ],
        summary=build_prosumer_realtime_market_summary(result, config=MARKET_CONFIG),
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

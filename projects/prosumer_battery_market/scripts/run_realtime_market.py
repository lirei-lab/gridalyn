"""Run a deterministic real-time market for distributed prosumer batteries."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pandapower as pp

from gridalyn.assets import apply_battery_dispatch_to_pandapower, apply_pv_generation_to_pandapower
from gridalyn.foundation import ReportMetadata, file_reference, write_report

from network_model import build_synthetic_feeder


PROJECT_NAME = "prosumer_battery_market"
INTERVAL_MINUTES = 5
INTERVAL_COUNT = 12
DT_H = INTERVAL_MINUTES / 60.0
IMPORT_LIMIT_MW = 2.55
FORECAST_HORIZON_INTERVALS = 4
RESERVE_FRACTION = 0.55
LOCATIONAL_CREDIT_USD_PER_MWH = 2.0
SCARCITY_ADDER_USD_PER_MWH = 6.0
LOAD_MULTIPLIERS = (0.98, 1.03, 1.08, 1.12, 1.17, 1.22, 1.24, 1.21, 1.16, 1.10, 1.04, 0.99)
PV_FACTORS = (0.34, 0.30, 0.25, 0.19, 0.13, 0.08, 0.04, 0.02, 0.0, 0.0, 0.0, 0.0)
LOAD_FORECAST_BIAS_BY_LEAD = (0.0, 0.006, -0.004, 0.01)
PV_FORECAST_BIAS_BY_LEAD = (0.0, -0.015, 0.01, -0.02)


def _ensure_outputs() -> None:
    for relative in (
        "outputs/data",
        "outputs/figures",
        "outputs/operations",
        "outputs/reports",
        "outputs/cache",
    ):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _market_timestamps() -> list[str]:
    return [f"RT-{index:02d}" for index in range(INTERVAL_COUNT)]


def _build_interval_forecast(
    issue_index: int,
    base_load_mw: float,
    total_pv_capacity_mw: float,
) -> pd.DataFrame:
    """Create a rolling forecast issued before clearing one market interval."""
    rows = []
    for lead in range(FORECAST_HORIZON_INTERVALS):
        target_index = min(issue_index + lead, INTERVAL_COUNT - 1)
        load_multiplier = LOAD_MULTIPLIERS[target_index] * (1.0 + LOAD_FORECAST_BIAS_BY_LEAD[lead])
        pv_factor = max(PV_FACTORS[target_index] * (1.0 + PV_FORECAST_BIAS_BY_LEAD[lead]), 0.0)
        pv_generation_mw = total_pv_capacity_mw * pv_factor
        import_mw = base_load_mw * load_multiplier - pv_generation_mw
        rows.append(
            {
                "issue_interval_index": issue_index,
                "issue_interval_id": f"RT-{issue_index:02d}",
                "target_interval_index": target_index,
                "target_interval_id": f"RT-{target_index:02d}",
                "lead_interval": lead,
                "forecast_load_multiplier": load_multiplier,
                "forecast_pv_factor": pv_factor,
                "forecast_pv_generation_mw": pv_generation_mw,
                "forecast_import_mw": import_mw,
                "forecast_required_reduction_mw": max(import_mw - IMPORT_LIMIT_MW, 0.0),
            }
        )
    return pd.DataFrame(rows)


def _clear_interval(
    prosumers: pd.DataFrame,
    soc: dict[str, float],
    forecast: pd.DataFrame,
) -> tuple[list[dict], list[dict], float, float, float | None]:
    dispatch_rows: list[dict] = []
    offers: list[dict] = []
    current = forecast.loc[forecast["lead_interval"] == 0].iloc[0]
    required_mw = float(current["forecast_required_reduction_mw"])
    remaining = max(required_mw, 0.0)
    accepted_offer_prices: list[float] = []

    total_power_mw = float(prosumers["battery_power_mw"].sum())
    future_required_mwh = float(
        (forecast.loc[forecast["lead_interval"] > 0, "forecast_required_reduction_mw"] * DT_H).sum()
    )
    usable_energy_mwh = sum(
        max(soc[str(row.prosumer_id)] - float(row.min_soc_mwh), 0.0)
        for row in prosumers.itertuples(index=False)
    )
    scarcity_ratio = future_required_mwh / max(usable_energy_mwh, 1e-9)

    cleared_by_prosumer = {str(row.prosumer_id): 0.0 for row in prosumers.itertuples(index=False)}
    offer_rows = []
    for row in prosumers.itertuples(index=False):
        prosumer_id = str(row.prosumer_id)
        future_reserve_mwh = (
            future_required_mwh
            * (float(row.battery_power_mw) / max(total_power_mw, 1e-9))
            * RESERVE_FRACTION
        )
        available_energy_mwh = max(soc[prosumer_id] - float(row.min_soc_mwh) - future_reserve_mwh, 0.0)
        offered_quantity_mw = min(float(row.battery_power_mw), available_energy_mwh / DT_H)
        locational_priority = float(row.bus_id) / float(prosumers["bus_id"].max())
        submitted_price = float(row.offer_price_usd_per_mwh) + SCARCITY_ADDER_USD_PER_MWH * scarcity_ratio
        network_adjusted_price = submitted_price - LOCATIONAL_CREDIT_USD_PER_MWH * locational_priority
        offer_rows.append(
            {
                "prosumer_id": prosumer_id,
                "bus_id": int(row.bus_id),
                "submitted_offer_price_usd_per_mwh": submitted_price,
                "network_adjusted_bid_price_usd_per_mwh": network_adjusted_price,
                "offered_quantity_mw": offered_quantity_mw,
                "future_reserve_mwh": future_reserve_mwh,
                "forecast_scarcity_ratio": scarcity_ratio,
            }
        )

    offer_book = pd.DataFrame(offer_rows).sort_values(
        ["network_adjusted_bid_price_usd_per_mwh", "prosumer_id"]
    )
    for row in offer_book.itertuples(index=False):
        prosumer_id = str(row.prosumer_id)
        dispatch_mw = min(float(row.offered_quantity_mw), remaining)
        if dispatch_mw > 0:
            soc[prosumer_id] -= dispatch_mw * DT_H
            remaining -= dispatch_mw
            accepted_offer_prices.append(float(row.submitted_offer_price_usd_per_mwh))
            cleared_by_prosumer[prosumer_id] = dispatch_mw
        if remaining <= 1e-9:
            break

    clearing_price = max(accepted_offer_prices) if accepted_offer_prices else None
    cleared_cost = sum(cleared_by_prosumer.values()) * DT_H * float(clearing_price or 0.0)

    for row in prosumers.sort_values("prosumer_id").itertuples(index=False):
        prosumer_id = str(row.prosumer_id)
        offer = offer_book.loc[offer_book["prosumer_id"] == prosumer_id].iloc[0]
        dispatch_mw = float(cleared_by_prosumer[prosumer_id])
        dispatch_rows.append(
            {
                "prosumer_id": prosumer_id,
                "bus_id": int(row.bus_id),
                "submitted_offer_price_usd_per_mwh": float(offer.submitted_offer_price_usd_per_mwh),
                "network_adjusted_bid_price_usd_per_mwh": float(offer.network_adjusted_bid_price_usd_per_mwh),
                "market_clearing_price_usd_per_mwh": clearing_price,
                "settlement_price_usd_per_mwh": clearing_price if dispatch_mw > 0 else 0.0,
                "dispatch_mw": dispatch_mw,
                "dispatch_mwh": dispatch_mw * DT_H,
                "payment_usd": dispatch_mw * DT_H * float(clearing_price or 0.0),
                "soc_mwh_after": float(soc[prosumer_id]),
            }
        )
        offer_dict = offer.to_dict()
        offer_dict["accepted_mw"] = dispatch_mw
        offer_dict["market_clearing_price_usd_per_mwh"] = clearing_price
        offers.append(offer_dict)
    return dispatch_rows, offers, required_mw - remaining, cleared_cost, clearing_price


def _run_powerflow(load_multiplier: float, prosumers: pd.DataFrame, pv_factor: float, dispatch: pd.DataFrame) -> dict:
    net = build_synthetic_feeder()
    net.load["p_mw"] = net.load["p_mw"] * load_multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * load_multiplier

    apply_pv_generation_to_pandapower(net, prosumers, pv_factor=pv_factor)
    apply_battery_dispatch_to_pandapower(net, dispatch)

    pp.runpp(net, algorithm="nr", init="auto")
    return {
        "converged": bool(net.converged),
        "min_voltage_pu": float(net.res_bus.vm_pu.min()),
        "max_voltage_pu": float(net.res_bus.vm_pu.max()),
        "max_line_loading_percent": float(net.res_line.loading_percent.max()),
        "line_loss_mw": float(net.res_line.pl_mw.sum()),
    }


def _write_market_figure(clearing: pd.DataFrame) -> Path:
    figure_path = Path("outputs/figures/prosumer_market_dispatch.png")
    x = range(len(clearing))
    fig, ax = plt.subplots(figsize=(9.4, 4.8))
    ax.plot(x, clearing["import_before_mw"], marker="o", linewidth=1.8, label="Import before")
    ax.plot(x, clearing["import_after_mw"], marker="o", linewidth=1.8, label="Import after")
    ax.axhline(IMPORT_LIMIT_MW, color="#c0392b", linestyle="--", linewidth=1.2, label="Import limit")
    ax.bar(x, clearing["cleared_mw"], alpha=0.26, color="#2ca02c", label="Cleared battery MW")
    ax.set_title("Prosumer Battery Real-Time Market")
    ax.set_xlabel("5-minute interval")
    ax.set_ylabel("Power [MW]")
    ax.set_xticks(list(x))
    ax.set_xticklabels(clearing["interval_id"], rotation=45, ha="right")
    ax.grid(True, alpha=0.28)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _summary(clearing: pd.DataFrame, dispatch: pd.DataFrame, powerflow: pd.DataFrame) -> dict:
    return {
        "algorithm": "rolling_horizon_uniform_price_auction",
        "published_method_family": "transactive_energy_real_time_uniform_price_auction_with_mpc_forecast_horizon",
        "forecast_horizon_intervals": FORECAST_HORIZON_INTERVALS,
        "interval_count": int(len(clearing)),
        "interval_minutes": INTERVAL_MINUTES,
        "prosumer_count": int(dispatch["prosumer_id"].nunique()),
        "import_limit_mw": IMPORT_LIMIT_MW,
        "peak_import_before_mw": float(clearing["import_before_mw"].max()),
        "peak_import_after_mw": float(clearing["import_after_mw"].max()),
        "total_required_mwh": float((clearing["required_reduction_mw"] * DT_H).sum()),
        "total_cleared_mwh": float((clearing["cleared_mw"] * DT_H).sum()),
        "unserved_reduction_mwh": float((clearing["unserved_mw"] * DT_H).sum()),
        "total_market_cost_usd": float(clearing["cleared_cost_usd"].sum()),
        "min_voltage_after_pu": float(powerflow["min_voltage_pu"].min()),
        "max_line_loading_after_percent": float(powerflow["max_line_loading_percent"].max()),
    }


def main() -> int:
    _ensure_outputs()
    prosumer_path = Path("outputs/data/prosumers.csv")
    prosumers = pd.read_csv(prosumer_path)
    base_load_mw = float(sum(build_synthetic_feeder().load.p_mw))
    soc = {
        str(row.prosumer_id): float(row.initial_soc_mwh)
        for row in prosumers.itertuples(index=False)
    }

    clearing_rows: list[dict] = []
    dispatch_rows: list[dict] = []
    forecast_rows: list[dict] = []
    offer_rows: list[dict] = []
    powerflow_rows: list[dict] = []
    timestamps = _market_timestamps()
    total_pv_capacity_mw = float(prosumers["pv_capacity_mw"].sum())
    for index, interval_id in enumerate(timestamps):
        load_multiplier = LOAD_MULTIPLIERS[index]
        pv_factor = PV_FACTORS[index]
        pv_mw = float((prosumers["pv_capacity_mw"] * pv_factor).sum())
        import_before_mw = base_load_mw * load_multiplier - pv_mw
        forecast = _build_interval_forecast(index, base_load_mw, total_pv_capacity_mw)
        forecast_rows.extend(forecast.to_dict(orient="records"))
        current_forecast = forecast.loc[forecast["lead_interval"] == 0].iloc[0]
        required_mw = float(current_forecast["forecast_required_reduction_mw"])
        interval_dispatch, interval_offers, cleared_mw, cleared_cost, clearing_price = _clear_interval(
            prosumers, soc, forecast
        )
        interval_dispatch_df = pd.DataFrame(interval_dispatch)
        powerflow = _run_powerflow(load_multiplier, prosumers, pv_factor, interval_dispatch_df)
        import_after_mw = import_before_mw - cleared_mw

        clearing_rows.append(
            {
                "interval_id": interval_id,
                "interval_index": index,
                "load_multiplier": load_multiplier,
                "pv_factor": pv_factor,
                "pv_generation_mw": pv_mw,
                "import_before_mw": import_before_mw,
                "forecast_import_mw": float(current_forecast["forecast_import_mw"]),
                "forecast_required_reduction_mw": required_mw,
                "required_reduction_mw": required_mw,
                "cleared_mw": cleared_mw,
                "unserved_mw": max(required_mw - cleared_mw, 0.0),
                "import_after_mw": import_after_mw,
                "market_clearing_price_usd_per_mwh": clearing_price,
                "cleared_cost_usd": cleared_cost,
            }
        )
        for row in interval_dispatch:
            row["interval_id"] = interval_id
            row["interval_index"] = index
            dispatch_rows.append(row)
        for row in interval_offers:
            row["interval_id"] = interval_id
            row["interval_index"] = index
            offer_rows.append(row)
        powerflow["interval_id"] = interval_id
        powerflow["interval_index"] = index
        powerflow_rows.append(powerflow)

    clearing = pd.DataFrame(clearing_rows)
    dispatch = pd.DataFrame(dispatch_rows)
    forecast = pd.DataFrame(forecast_rows)
    offers = pd.DataFrame(offer_rows)
    powerflow = pd.DataFrame(powerflow_rows)

    clearing_path = Path("outputs/operations/realtime_market_clearing.csv")
    dispatch_path = Path("outputs/operations/battery_dispatch.csv")
    forecast_path = Path("outputs/data/realtime_market_forecast.csv")
    offers_path = Path("outputs/operations/realtime_market_offers.csv")
    powerflow_path = Path("outputs/data/realtime_powerflow_results.csv")
    clearing.to_csv(clearing_path, index=False)
    dispatch.to_csv(dispatch_path, index=False)
    forecast.to_csv(forecast_path, index=False)
    offers.to_csv(offers_path, index=False)
    powerflow.to_csv(powerflow_path, index=False)
    figure_path = _write_market_figure(clearing)
    report_path = Path("outputs/reports/prosumer_realtime_market_report.json")
    valid = bool(powerflow["converged"].all() and clearing["cleared_mw"].sum() > 0)

    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="prosumer_realtime_market_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(prosumer_path),
            file_reference(forecast_path),
            {
                "name": "real_time_import_limit",
                "type": "market_parameter",
                "import_limit_mw": IMPORT_LIMIT_MW,
            },
            {
                "name": "market_algorithm",
                "type": "published_method_family",
                "algorithm": "rolling_horizon_uniform_price_auction",
                "forecast_horizon_intervals": FORECAST_HORIZON_INTERVALS,
            },
        ],
        artifacts=[
            file_reference(clearing_path),
            file_reference(dispatch_path),
            file_reference(offers_path),
            file_reference(powerflow_path),
            file_reference(figure_path),
        ],
        summary=_summary(clearing, dispatch, powerflow),
        validation={
            "valid": valid,
            "errors": [] if valid else ["market did not clear any reduction or a power flow failed"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Run spatial pandapower time-series for digital-twin EV scenarios.

This runner combines the stochastic building baseline with per-building EV load:

    p_total = p_building + p_ev

EV reactive power is kept explicit as zero in this first unmanaged EV pass, so
q_total follows only the building-load power factor used by the existing
dashboard simulation.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandapower as pp
from pandapower.control import ConstControl
from pandapower.timeseries import DFData, OutputWriter, run_timeseries

from gridalyn.foundation import GridalynWorkspace

ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = GridalynWorkspace(ROOT)
DEFAULT_BASE_DIR = WORKSPACE.layout.base
DEFAULT_TIMESERIES_DIR = WORKSPACE.layout.timeseries
DEFAULT_CACHE_DIR = WORKSPACE.layout.cache
DEFAULT_CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
DEFAULT_SCENARIOS = ("S0", "S1")
DEFAULT_START = "2024-01-01 00:00:00"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def _scenario_sort_key(summary: dict[str, Any]) -> tuple[int, str]:
    scenario_id = str(summary.get("scenario_id", ""))
    if scenario_id.startswith("S") and scenario_id[1:].isdigit():
        return int(scenario_id[1:]), scenario_id
    return 10_000, scenario_id


def _coords_from_geo(geo: Any) -> tuple[float, float]:
    if pd.isna(geo):
        return 0.0, 0.0
    try:
        data = json.loads(str(geo).replace("'", '"'))
        coords = data.get("coordinates", [0.0, 0.0])
        return float(coords[0]), float(coords[1])
    except Exception:
        return 0.0, 0.0


def _bus_category(name: str, vn_kv: float) -> str:
    if name.startswith("lv_") or np.isclose(vn_kv, 0.4):
        return "LV"
    if name.startswith("mv_") or np.isclose(vn_kv, 25.0):
        return "MV"
    if name.startswith("hv_") or vn_kv >= 100.0:
        return "HV"
    return "UNKNOWN"


def _load_net(cache_dir: Path):
    with (cache_dir / "pp_net_cache.pkl").open("rb") as f:
        return pickle.load(f)


def _generate_base_building_loads(
    n_houses: int,
    resolution_minutes: int,
    seed: int,
    generator_type: str,
) -> tuple[np.ndarray, np.ndarray]:
    from gridalyn.assets.datagen.core import GridLoadFacade
    from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day

    macro_rng = np.random.default_rng(seed)
    cold_day = select_cold_day(download_tmy())
    t_offset = float(macro_rng.normal(0, 1.5))
    perturbed_temp_air = cold_day["temp_air"] + t_offset

    heat_kw, bg_kw = GridLoadFacade.generate_loads(
        generator_type=generator_type,
        df_weather=perturbed_temp_air,
        n_houses=n_houses,
        resolution_minutes=resolution_minutes,
        seed=seed,
    )
    total_kw = heat_kw + bg_kw

    n_steps = total_kw.shape[0]
    ar1_macro = np.zeros(n_steps, dtype=np.float32)
    rho_macro = 0.95
    shock_std = 0.04 * np.sqrt(1 - rho_macro**2)
    ar1_macro[0] = macro_rng.normal(0, 0.04)
    for t_step in range(1, n_steps):
        ar1_macro[t_step] = rho_macro * ar1_macro[t_step - 1] + macro_rng.normal(0, shock_std)

    total_kw = total_kw * (1.0 + ar1_macro)[:, np.newaxis]
    temperature = (
        cold_day["temp_air"]
        .resample(f"{resolution_minutes}min")
        .mean()
        .interpolate()
        .to_numpy(dtype=np.float32)
    )
    return total_kw.astype(np.float32), temperature[:n_steps]


def _load_ev_matrix(path: Path, timestamps: pd.Index, load_index: pd.Index) -> np.ndarray:
    ev = pd.read_parquet(path, columns=["timestamp", "pandapower_load", "p_ev_kw"])
    ev_wide = (
        ev.pivot(index="timestamp", columns="pandapower_load", values="p_ev_kw")
        .reindex(index=timestamps.astype(str), columns=load_index, fill_value=0.0)
        .fillna(0.0)
    )
    return ev_wide.to_numpy(dtype=np.float32)


def _normalize_pandapower_timeseries_net(net) -> None:
    """Normalize cached pandapower networks before time-series replay."""

    pp.convert_format(net)
    template = pp.create_empty_network()
    for table in ["vsc_stacked", "vsc_bipolar", "res_vsc_stacked", "res_vsc_bipolar"]:
        if table not in net:
            net[table] = template[table].copy()
    for column in [
        "const_z_p_percent",
        "const_i_p_percent",
        "const_z_q_percent",
        "const_i_q_percent",
    ]:
        if column not in net.load.columns:
            net.load[column] = 0.0


def _run_powerflow(net, p_total_mw: np.ndarray, q_total_mvar: np.ndarray):
    import lightsim2grid  # noqa: F401

    _normalize_pandapower_timeseries_net(net)
    time_steps = range(p_total_mw.shape[0])
    p_mw_df = pd.DataFrame(p_total_mw, index=time_steps, columns=net.load.index)
    q_mvar_df = pd.DataFrame(q_total_mvar, index=time_steps, columns=net.load.index)

    if "controller" in net and len(net.controller):
        net.controller.drop(net.controller.index, inplace=True)

    ConstControl(
        net,
        element="load",
        variable="p_mw",
        element_index=net.load.index,
        data_source=DFData(p_mw_df),
        profile_name=net.load.index,
    )
    ConstControl(
        net,
        element="load",
        variable="q_mvar",
        element_index=net.load.index,
        data_source=DFData(q_mvar_df),
        profile_name=net.load.index,
    )

    ow = OutputWriter(net, time_steps=time_steps)
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_line", "loading_percent")
    ow.log_variable("res_trafo", "loading_percent")
    ow.log_variable("res_ext_grid", "p_mw")

    def run_klu(net_obj, **kwargs):
        pp.runpp(net_obj, lightsim2grid=True, **kwargs)

    with np.errstate(divide="ignore", invalid="ignore", over="ignore", under="ignore"):
        run_timeseries(net, time_steps=time_steps, run=run_klu, verbose=False)

    return {
        "spatial_v": ow.output["res_bus.vm_pu"].to_numpy(copy=True),
        "spatial_line": ow.output["res_line.loading_percent"].to_numpy(copy=True),
        "spatial_trafo": ow.output["res_trafo.loading_percent"].to_numpy(copy=True),
        "ext_p_mw": ow.output["res_ext_grid.p_mw"].sum(axis=1).abs().to_numpy(copy=True),
    }


def _export_results(
    net,
    scenario_id: str,
    timestamps: pd.Index,
    temperature_c: np.ndarray,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    results: dict[str, np.ndarray],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp_values = timestamps.astype(str).to_numpy()

    bus_rows = []
    for bus_idx, row in net.bus.iterrows():
        lat, lon = _coords_from_geo(row.get("geo"))
        bus_rows.append(
            {
                "bus_idx": int(bus_idx),
                "lon": lon,
                "lat": lat,
                "category": _bus_category(str(row["name"]), float(row["vn_kv"])),
            }
        )
    bus_ref = pd.DataFrame(bus_rows)

    node_df = pd.DataFrame(results["spatial_v"], index=timestamp_values, columns=net.bus.index)
    node_long = node_df.reset_index(names="timestamp").melt(
        id_vars="timestamp", var_name="bus_idx", value_name="v_pu"
    )
    node_long["scenario_id"] = scenario_id
    node_long = node_long.merge(bus_ref, on="bus_idx", how="left")
    node_long.to_parquet(out_dir / f"{scenario_id}_powerflow_nodes.parquet", index=False)

    line_ref = net.line[["from_bus", "to_bus"]].reset_index(names="line_idx")
    line_ref["line_idx"] = line_ref["line_idx"].astype(int)
    line_df = pd.DataFrame(results["spatial_line"], index=timestamp_values, columns=net.line.index)
    line_long = line_df.reset_index(names="timestamp").melt(
        id_vars="timestamp", var_name="line_idx", value_name="loading_percent"
    )
    line_long["scenario_id"] = scenario_id
    line_long = line_long.merge(line_ref, on="line_idx", how="left")
    line_long.to_parquet(out_dir / f"{scenario_id}_powerflow_lines.parquet", index=False)

    trafo_ref = net.trafo[["hv_bus", "lv_bus", "sn_mva", "vn_hv_kv", "vn_lv_kv"]].reset_index(
        names="trafo_idx"
    )
    trafo_ref["trafo_idx"] = trafo_ref["trafo_idx"].astype(int)
    trafo_df = pd.DataFrame(results["spatial_trafo"], index=timestamp_values, columns=net.trafo.index)
    trafo_long = trafo_df.reset_index(names="timestamp").melt(
        id_vars="timestamp", var_name="trafo_idx", value_name="loading_percent"
    )
    trafo_long["scenario_id"] = scenario_id
    trafo_long = trafo_long.merge(trafo_ref, on="trafo_idx", how="left")
    trafo_long.to_parquet(out_dir / f"{scenario_id}_powerflow_transformers.parquet", index=False)

    p_total_mw = (building_kw + ev_kw) / 1000.0
    power = pd.DataFrame(
        {
            "timestamp": np.repeat(timestamp_values, len(net.load.index)),
            "scenario_id": scenario_id,
            "pandapower_load": np.tile(net.load.index.to_numpy(dtype=np.int64), len(timestamp_values)),
            "p_building_mw": building_kw.reshape(-1) / 1000.0,
            "p_ev_mw": ev_kw.reshape(-1) / 1000.0,
            "p_total_mw": p_total_mw.reshape(-1),
            "q_total_mvar": (building_kw.reshape(-1) / 1000.0) * 0.1,
            "temperature_c": np.repeat(temperature_c[: len(timestamp_values)], len(net.load.index)),
        }
    )
    power.to_parquet(out_dir / f"{scenario_id}_powerflow_power.parquet", index=False)

    summary = {
        "scenario_id": scenario_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_timestamps": int(len(timestamp_values)),
        "n_loads": int(len(net.load)),
        "n_buses": int(len(net.bus)),
        "n_lines": int(len(net.line)),
        "n_transformers": int(len(net.trafo)),
        "building_peak_mw": float(np.max(building_kw.sum(axis=1)) / 1000.0),
        "ev_peak_mw": float(np.max(ev_kw.sum(axis=1)) / 1000.0),
        "load_peak_mw": float(np.max(p_total_mw.sum(axis=1))),
        "ext_grid_peak_mw": float(np.max(results["ext_p_mw"])),
        "v_min_pu": float(np.min(results["spatial_v"])),
        "v_mean_pu": float(np.mean(results["spatial_v"])),
        "line_max_loading_percent": float(np.max(results["spatial_line"])),
        "trafo_max_loading_percent": float(np.max(results["spatial_trafo"])),
        "q_ev_policy": "zero_reactive_power",
        "paths": {
            "nodes": str((out_dir / f"{scenario_id}_powerflow_nodes.parquet").relative_to(ROOT)),
            "lines": str((out_dir / f"{scenario_id}_powerflow_lines.parquet").relative_to(ROOT)),
            "transformers": str((out_dir / f"{scenario_id}_powerflow_transformers.parquet").relative_to(ROOT)),
            "power": str((out_dir / f"{scenario_id}_powerflow_power.parquet").relative_to(ROOT)),
        },
    }
    with (out_dir / f"{scenario_id}_powerflow_summary.json").open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary


def run_scenarios(
    scenarios: list[str],
    base_dir: Path,
    timeseries_dir: Path,
    cache_dir: Path,
    config_path: Path,
    start_timestamp: str,
) -> None:
    config = _load_json(config_path)
    sim_config = config.get("simulation", {})
    resolution_minutes = int(sim_config.get("resolution_minutes", 5))
    seed = int(sim_config.get("seed", 42))
    generator_type = str(sim_config.get("generator", "parametric"))

    buildings = pd.read_parquet(base_dir / "buildings.parquet").sort_values("pandapower_load")
    net_probe = _load_net(cache_dir)
    if list(buildings["pandapower_load"].astype(int)) != list(net_probe.load.index.astype(int)):
        raise RuntimeError("Base twin pandapower_load order does not match cached pandapower net.")

    print("Generating shared base building load matrix...")
    building_kw, temperature_c = _generate_base_building_loads(
        n_houses=len(buildings),
        resolution_minutes=resolution_minutes,
        seed=seed,
        generator_type=generator_type,
    )
    timestamps = pd.date_range(start_timestamp, periods=building_kw.shape[0], freq=f"{resolution_minutes}min")

    summaries = []
    for scenario_id in scenarios:
        print(f"\n=== Running digital-twin EV powerflow: {scenario_id} ===")
        net = _load_net(cache_dir)
        ev_kw = _load_ev_matrix(
            timeseries_dir / f"{scenario_id}_ev_load.parquet",
            timestamps=timestamps,
            load_index=net.load.index,
        )
        if ev_kw.shape != building_kw.shape:
            raise RuntimeError(f"{scenario_id}: EV matrix {ev_kw.shape} does not match building matrix {building_kw.shape}.")

        p_total_mw = (building_kw + ev_kw) / 1000.0
        q_total_mvar = (building_kw / 1000.0) * 0.1
        results = _run_powerflow(net, p_total_mw=p_total_mw, q_total_mvar=q_total_mvar)
        summary = _export_results(
            net=net,
            scenario_id=scenario_id,
            timestamps=timestamps,
            temperature_c=temperature_c,
            building_kw=building_kw,
            ev_kw=ev_kw,
            results=results,
            out_dir=timeseries_dir,
        )
        summaries.append(summary)
        print(
            f"{scenario_id}: ext peak {summary['ext_grid_peak_mw']:.2f} MW | "
            f"EV peak {summary['ev_peak_mw']:.2f} MW | "
            f"v_min {summary['v_min_pu']:.4f} | "
            f"line max {summary['line_max_loading_percent']:.2f}% | "
            f"trafo max {summary['trafo_max_loading_percent']:.2f}%"
        )

    summary_path = timeseries_dir / "powerflow_smoke_summary.json"
    merged_summaries = {}
    if summary_path.exists():
        existing = _load_json(summary_path)
        for item in existing.get("scenarios", []):
            merged_summaries[str(item["scenario_id"])] = item
    for item in summaries:
        merged_summaries[str(item["scenario_id"])] = item

    with summary_path.open("w") as f:
        json.dump(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "scenarios": sorted(merged_summaries.values(), key=_scenario_sort_key),
                "resolution_minutes": resolution_minutes,
                "load_realization_seed": seed,
                "generator_type": generator_type,
                "p_total_policy": "p_building + p_ev",
                "q_ev_policy": "zero_reactive_power",
            },
            f,
            indent=2,
            sort_keys=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run digital-twin EV powerflow smoke scenarios.")
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--timeseries-dir", type=Path, default=DEFAULT_TIMESERIES_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--start-timestamp", default=DEFAULT_START)
    args = parser.parse_args()

    run_scenarios(
        scenarios=args.scenarios,
        base_dir=args.base_dir,
        timeseries_dir=args.timeseries_dir,
        cache_dir=args.cache_dir,
        config_path=args.config,
        start_timestamp=args.start_timestamp,
    )


if __name__ == "__main__":
    main()

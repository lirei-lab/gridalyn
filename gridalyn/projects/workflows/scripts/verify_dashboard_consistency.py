"""
Verify that dashboard simulation artifacts are internally consistent.

This script intentionally does not use building floor area for load generation.
It checks that the network sizing assumptions, pandapower transformer model,
and dashboard Parquet exports describe the same scenario.
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pandapower as pp

from gridalyn.foundation import GridalynWorkspace

ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = GridalynWorkspace(ROOT)
CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
DEFAULT_CACHE_DIR = WORKSPACE.layout.cache
PUBLIC_DIR = ROOT / "dashboard" / "public"


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def _std_type_sn_mva(std_type: str, cfg: dict) -> float:
    if cfg.get("custom_type", False):
        return float(cfg["capacity_kva"]) / 1000.0
    net = pp.create_empty_network()
    params = pp.std_types.load_std_type(net, std_type, "trafo")
    return float(params["sn_mva"])


def _load_cache(cache_dir: Path):
    with (cache_dir / "pp_net_cache.pkl").open("rb") as f:
        net = pickle.load(f)
    with (cache_dir / "pg_graph_cache.pkl").open("rb") as f:
        pg = pickle.load(f)
    return net, pg


def _load_parquets(public_dir: Path):
    return {
        "nodes": pd.read_parquet(public_dir / "kepler_timeseries_nodes.parquet"),
        "lines": pd.read_parquet(public_dir / "kepler_timeseries_lines.parquet"),
        "power": pd.read_parquet(public_dir / "kepler_timeseries_power.parquet"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--public-dir", type=Path, default=PUBLIC_DIR)
    args = parser.parse_args()
    config = _load_json(CONFIG_PATH)
    lv_cfg = config["transformers"]["lv_mv"]
    declared_mva = float(lv_cfg["capacity_kva"]) / 1000.0
    std_mva = _std_type_sn_mva(lv_cfg["std_type"], lv_cfg)

    print("=== Transformer Sizing Contract ===")
    print(f"LV/MV config capacity_kva : {lv_cfg['capacity_kva']} kVA")
    print(f"LV/MV std_type           : {lv_cfg['std_type']} ({std_mva:.3f} MVA)")
    if not np.isclose(declared_mva, std_mva, rtol=0.0, atol=1e-6):
        raise SystemExit(
            "ERROR: lv_mv.capacity_kva does not match the pandapower std_type sn_mva."
        )
    print("OK: declared capacity matches pandapower transformer rating.")

    net, pg = _load_cache(args.cache_dir)
    pq = _load_parquets(args.public_dir)

    lv_trafos = net.trafo[np.isclose(net.trafo["vn_lv_kv"].astype(float), 0.4)]
    if lv_trafos.empty:
        raise SystemExit("ERROR: no LV/MV transformers found in cached pandapower network.")
    actual_lv_ratings = sorted(set(round(float(v), 6) for v in lv_trafos["sn_mva"]))
    if actual_lv_ratings != [round(std_mva, 6)]:
        raise SystemExit(
            "ERROR: cached pandapower LV/MV transformer ratings do not match config. "
            f"cache={actual_lv_ratings}, config={std_mva:.6f}. Rebuild the grid cache."
        )

    print("\n=== Dashboard Parquet Schemas ===")
    expected = {
        "nodes": {"timestamp", "bus_idx", "lon", "lat", "v_pu", "category"},
        "lines": {"timestamp", "line_idx", "lon_from", "lat_from", "lon_to", "lat_to", "loading_percent", "category"},
        "power": {"timestamp", "bus_idx", "p_mw", "temperature_c"},
    }
    for name, df in pq.items():
        missing = expected[name] - set(df.columns)
        if missing:
            raise SystemExit(f"ERROR: {name}.parquet missing columns: {sorted(missing)}")
        print(f"{name:5s}: {len(df):9d} rows | {df['timestamp'].nunique():3d} timestamps")

    node_times = set(pq["nodes"]["timestamp"].unique())
    line_times = set(pq["lines"]["timestamp"].unique())
    power_times = set(pq["power"]["timestamp"].unique())
    if node_times != line_times or node_times != power_times:
        raise SystemExit("ERROR: timestamp sets differ between dashboard Parquet files.")
    print("OK: timestamp sets are aligned.")

    print("\n=== Network Size ===")
    print(f"pandapower buses : {len(net.bus)}")
    print(f"loads            : {len(net.load)}")
    print(f"lines            : {len(net.line)}")
    print(f"transformers     : {len(net.trafo)}")
    print(f"dashboard nodes  : {pq['nodes']['bus_idx'].nunique()}")
    print(f"dashboard lines  : {pq['lines']['line_idx'].nunique()}")
    print(f"dashboard loads  : {pq['power']['bus_idx'].nunique()}")

    if len(net.bus) != pq["nodes"]["bus_idx"].nunique():
        raise SystemExit("ERROR: node Parquet bus count does not match pandapower bus count.")
    if len(net.line) != pq["lines"]["line_idx"].nunique():
        raise SystemExit("ERROR: line Parquet line count does not match pandapower line count.")
    if len(net.load) != pq["power"]["bus_idx"].nunique():
        raise SystemExit("ERROR: power Parquet load count does not match pandapower load count.")
    print("OK: Parquet element counts match the pandapower model.")

    print("\n=== Voltage and Loading Summary ===")
    print(pq["nodes"].groupby("category")["v_pu"].agg(["min", "mean", "median", "max"]).round(4))
    print("\nLine loading percent:")
    print(pq["lines"]["loading_percent"].agg(["min", "mean", "median", "max"]).round(2).to_string())
    print(f"Lines over 100% at any timestamp: {(pq['lines'].groupby('line_idx')['loading_percent'].max() > 100).sum()}")

    print("\n=== LV Transformer Cluster Check ===")
    bus_name = net.bus["name"].to_dict()
    labels = pg.labels_lv
    load_cluster = {}
    for load_idx, row in net.load.iterrows():
        name = str(bus_name[row["bus"]])
        match = re.search(r"lv_bus_(\d+)", name)
        if match:
            load_cluster[int(load_idx)] = int(labels[int(match.group(1))])

    cluster_map = pd.DataFrame(
        {"bus_idx": list(load_cluster.keys()), "cluster": list(load_cluster.values())}
    )
    power = pq["power"].merge(cluster_map, on="bus_idx", how="inner")
    peak_cluster_kw = power.groupby(["cluster", "timestamp"])["p_mw"].sum().groupby("cluster").max() * 1000.0
    n_by_cluster = cluster_map.groupby("cluster")["bus_idx"].count()

    rating_kw = float(lv_cfg["capacity_kva"])
    utilization = peak_cluster_kw / rating_kw
    summary = pd.DataFrame(
        {
            "n_buildings": n_by_cluster,
            "peak_kw": peak_cluster_kw,
            "rating_kw": rating_kw,
            "peak_over_rating": utilization,
        }
    )
    print(summary["peak_over_rating"].describe().round(3).to_string())
    print(f"Clusters above rating: {(summary['peak_over_rating'] > 1.0).sum()} / {len(summary)}")
    print("\nWorst LV clusters:")
    print(summary.sort_values("peak_over_rating", ascending=False).head(10).round(2).to_string())


if __name__ == "__main__":
    main()

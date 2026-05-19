"""Validate CLS dispatch on the granular digital-twin pandapower model."""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from gridalyn.foundation import GridalynWorkspace
from gridalyn.operations.market.spatial_cls import (
    allocate_addition_by_headroom,
    apply_spatial_cls,
)
from gridalyn.workflows.scripts.run_digital_twin_ev_powerflow import (
    _generate_base_building_loads,
    _load_ev_matrix,
    _load_json,
    _run_powerflow,
)

ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = GridalynWorkspace(ROOT)
BASE_DIR = WORKSPACE.layout.base
TIMESERIES_DIR = WORKSPACE.layout.timeseries
DEFAULT_CACHE_DIR = WORKSPACE.layout.cache
CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
SCENARIO_DIR = WORKSPACE.layout.scenarios
ASSET_REGISTRY_PATH = SCENARIO_DIR / "asset_registry.parquet"
DEFAULT_MARKET_DISPATCH_PATH = WORKSPACE.layout.flexibility / "market_dispatch_timeseries.parquet"
DEFAULT_OUT_DIR = WORKSPACE.layout.flexibility


def _load_net(cache_dir: Path = DEFAULT_CACHE_DIR):
    with (cache_dir / "pp_net_cache.pkl").open("rb") as f:
        return pickle.load(f)


def _load_s4_asset_registry(buildings: pd.DataFrame) -> pd.DataFrame:
    if not ASSET_REGISTRY_PATH.exists():
        raise FileNotFoundError(
            "Missing digital-twin asset registry. Run "
            "gridalyn.interfaces.cli.digital_twin asset-registry first."
        )

    registry = (
        pd.read_parquet(ASSET_REGISTRY_PATH)
        .loc[lambda df: df["scenario_id"] == "S4"]
        .sort_values("pandapower_load")
        .reset_index(drop=True)
    )
    if len(registry) != len(buildings):
        raise ValueError(
            "S4 asset registry row count does not match base building count"
        )
    if not np.array_equal(
        registry["pandapower_load"].to_numpy(),
        buildings["pandapower_load"].to_numpy(),
    ):
        raise ValueError("S4 asset registry is not aligned to pandapower load order")
    return registry


def _load_s4_inputs(
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    market_dispatch_path: Path = DEFAULT_MARKET_DISPATCH_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    config = _load_json(CONFIG_PATH)
    sim_config = config.get("simulation", {})
    resolution_minutes = int(sim_config.get("resolution_minutes", 5))
    seed = int(sim_config.get("seed", 42))
    generator_type = str(sim_config.get("generator", "parametric"))

    buildings = pd.read_parquet(BASE_DIR / "buildings.parquet").sort_values("pandapower_load").reset_index(drop=True)
    building_kw, _temperature_c = _generate_base_building_loads(
        n_houses=len(buildings),
        resolution_minutes=resolution_minutes,
        seed=seed,
        generator_type=generator_type,
    )
    timestamps = pd.date_range(
        "2024-01-01 00:00:00",
        periods=building_kw.shape[0],
        freq=f"{resolution_minutes}min",
    )

    net = _load_net(cache_dir)
    ev_kw = _load_ev_matrix(
        TIMESERIES_DIR / "S4_ev_load.parquet",
        timestamps=timestamps,
        load_index=net.load.index,
    )
    dispatch = pd.read_parquet(market_dispatch_path)
    n_steps = min(len(dispatch), building_kw.shape[0], ev_kw.shape[0])
    return (
        buildings,
        _load_s4_asset_registry(buildings),
        building_kw[:n_steps],
        ev_kw[:n_steps],
        dispatch["p_soft_cls_mw"].to_numpy(dtype=float)[:n_steps] * 1000.0,
        dispatch["p_hard_cls_mw"].to_numpy(dtype=float)[:n_steps] * 1000.0,
        dispatch["p_rebound_mw"].to_numpy(dtype=float)[:n_steps] * 1000.0,
    )


def _powerflow_metrics(
    label: str,
    p_total_mw: np.ndarray,
    q_total_mvar: np.ndarray,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict:
    net = _load_net(cache_dir)
    results = _run_powerflow(net, p_total_mw=p_total_mw, q_total_mvar=q_total_mvar)
    return {
        "label": label,
        "ext_grid_peak_mw": float(np.max(results["ext_p_mw"])),
        "v_min_pu": float(np.min(results["spatial_v"])),
        "v_mean_pu": float(np.mean(results["spatial_v"])),
        "line_max_loading_percent": float(np.max(results["spatial_line"])),
        "trafo_max_loading_percent": float(np.max(results["spatial_trafo"])),
        "n_line_overloads": int(np.sum(np.max(results["spatial_line"], axis=0) > 100.0)),
        "n_trafo_overloads": int(np.sum(np.max(results["spatial_trafo"], axis=0) > 100.0)),
    }


def generate_spatial_cls_powerflow_validation(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    market_dispatch_path: Path = DEFAULT_MARKET_DISPATCH_PATH,
) -> dict:
    buildings, registry, building_kw, ev_kw, soft_kw, hard_kw, rebound_kw = _load_s4_inputs(
        cache_dir=cache_dir,
        market_dispatch_path=market_dispatch_path,
    )
    config = _load_json(CONFIG_PATH)
    soft_eligible = registry["soft_cls_participant"].to_numpy(dtype=bool)
    hard_enabled = registry["hard_cls_enabled"].to_numpy(dtype=bool)
    ev_eligible = registry["has_ev"].to_numpy(dtype=bool)
    charger_kw = registry["charger_kw"].to_numpy(dtype=float)
    hard_preferred = ev_eligible & hard_enabled & ~soft_eligible

    cls = apply_spatial_cls(
        building_kw=building_kw,
        ev_kw=ev_kw,
        soft_cls_kw=soft_kw,
        hard_cls_kw=hard_kw,
        soft_eligible=soft_eligible,
        hard_preferred=hard_preferred,
        ev_eligible=ev_eligible,
    )
    rebound_added_kw, rebound_delivered_kw = allocate_addition_by_headroom(
        cls.managed_ev_kw,
        rebound_kw,
        ev_eligible,
        charger_kw,
    )
    managed_ev_kw = cls.managed_ev_kw + rebound_added_kw

    unmanaged_p_total_mw = (building_kw + ev_kw) / 1000.0
    managed_p_total_mw = (cls.managed_building_kw + managed_ev_kw) / 1000.0
    unmanaged_q_mvar = (building_kw / 1000.0) * 0.1
    managed_q_mvar = (cls.managed_building_kw / 1000.0) * 0.1

    dt_h = int(config.get("simulation", {}).get("resolution_minutes", 5)) / 60.0
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": "S4",
        "n_timesteps": int(building_kw.shape[0]),
        "n_loads": int(building_kw.shape[1]),
        "n_ev": int(ev_eligible.sum()),
        "n_soft_participants": int(soft_eligible.sum()),
        "n_soft_and_ev": int(np.sum(soft_eligible & ev_eligible)),
        "n_hard_preferred_ev": int(np.sum(hard_preferred)),
        "asset_registry_path": str(ASSET_REGISTRY_PATH.relative_to(ROOT)),
        "soft_participant_policy": str(registry["soft_assignment_policy"].iloc[0]),
        "hard_dispatch_policy": "prefer_non_soft_participant_evs_then_fallback_to_all_active_evs",
        "rebound_policy": "allocate_to_active_ev_charger_headroom",
        "dispatch_window_hours": float(building_kw.shape[0] * dt_h),
        "aggregate_targets_mwh": {
            "soft": float(np.sum(soft_kw) * dt_h / 1000.0),
            "hard": float(np.sum(hard_kw) * dt_h / 1000.0),
            "rebound": float(np.sum(rebound_kw) * dt_h / 1000.0),
        },
        "spatial_delivered_mwh": {
            "soft": float(np.sum(cls.soft_delivered_kw) * dt_h / 1000.0),
            "hard": float(np.sum(cls.hard_delivered_kw) * dt_h / 1000.0),
            "rebound": float(np.sum(rebound_delivered_kw) * dt_h / 1000.0),
        },
        "unmanaged_powerflow": _powerflow_metrics(
            "unmanaged", unmanaged_p_total_mw, unmanaged_q_mvar, cache_dir=cache_dir
        ),
        "cls_managed_powerflow": _powerflow_metrics(
            "cls_managed", managed_p_total_mw, managed_q_mvar, cache_dir=cache_dir
        ),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "spatial_cls_powerflow_validation.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    summary["artifacts"] = {"report": str(out_path)}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--market-dispatch-path", type=Path, default=DEFAULT_MARKET_DISPATCH_PATH)
    args = parser.parse_args()
    summary = generate_spatial_cls_powerflow_validation(
        out_dir=args.out_dir,
        cache_dir=args.cache_dir,
        market_dispatch_path=args.market_dispatch_path,
    )
    print(f"[Gridalyn] Spatial CLS powerflow validation saved to {summary['artifacts']['report']}")
    print(
        "  unmanaged -> managed ext peak: "
        f"{summary['unmanaged_powerflow']['ext_grid_peak_mw']:.2f} -> "
        f"{summary['cls_managed_powerflow']['ext_grid_peak_mw']:.2f} MW"
    )
    print(
        "  unmanaged -> managed v_min: "
        f"{summary['unmanaged_powerflow']['v_min_pu']:.4f} -> "
        f"{summary['cls_managed_powerflow']['v_min_pu']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

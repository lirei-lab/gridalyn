from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import pandapower as pp

from gridalyn.simulation.simulators.powerflow.runner import PowerflowMonteCarloRunner
from gridalyn.twin.core.graph import PowerGridGraph


def test_monte_carlo_prepare_grid_returns_cached_net_path(tmp_path: Path) -> None:
    config = {"simulation": {"n_realizations": 1, "resolution_minutes": 5}}
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_schema = "gridalyn-powerflow-cache-v2"
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    net = pp.create_empty_network()
    pp.create_bus(net, vn_kv=0.4)
    (cache_dir / "pg_graph_cache.pkl").write_bytes(pickle.dumps(PowerGridGraph()))
    (cache_dir / "pp_net_cache.pkl").write_bytes(pickle.dumps(net))
    (cache_dir / "grid_cache_meta.json").write_text(
        json.dumps(
            {
                "cache_schema": cache_schema,
                "config_hash": config_hash,
                "config": config,
            }
        ),
        encoding="utf-8",
    )
    runner = PowerflowMonteCarloRunner(
        input_file="examples/tutorials/data/buildings_inside_polygon.geojson",
        cache_dir=str(cache_dir),
        config=config,
    )

    cache_path = runner._prepare_grid()

    assert cache_path == str(cache_dir / "pp_net_cache.pkl")

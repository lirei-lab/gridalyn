"""Public synthetic distribution-network generation API.

This module turns building-footprint GeoJSON into a reproducible Gridalyn
network bundle: a :class:`PowerGridGraph`, a pandapower network, optional cache
files, and a validation report. It keeps the historical graph builder as the
engine, but exposes a project-friendly contract that can be used from CLI,
workflows, tests, and future utility adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

import pandapower as pp

from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.simulation.simulators.powerflow.builder import PandapowerGridBuilder


@dataclass(frozen=True)
class SyntheticNetworkBuildResult:
    """Artifacts created by :func:`build_synthetic_network_from_geojson`."""

    power_grid: PowerGridGraph
    net: pp.pandapowerNet
    validation_report: dict[str, Any]
    report_path: Path | None


def build_synthetic_network_from_geojson(
    *,
    footprints_path: Path | str,
    config_path: Path | str,
    out_dir: Path | str | None = None,
    clustering_crs: str | int | None = "auto",
    write_cache: bool = False,
    run_powerflow: bool = False,
) -> SyntheticNetworkBuildResult:
    """Build a synthetic distribution network from building footprints.

    Args:
        footprints_path: GeoJSON file with building polygons.
        config_path: Grid configuration JSON.
        out_dir: Optional directory for cache files and validation report.
        clustering_crs: Metric CRS for clustering. ``"auto"`` estimates a
            local UTM CRS from the footprint layer. Graph geodata remains
            longitude/latitude.
        write_cache: When true, write ``pg_graph_cache.pkl`` and
            ``pp_net_cache.pkl`` in ``out_dir`` for downstream adapters.
        run_powerflow: When true, run a pandapower AC power flow and record
            convergence in the report.
    """

    footprints = Path(footprints_path)
    config_file = Path(config_path)
    output_dir = Path(out_dir) if out_dir is not None else None
    config = _load_json(config_file)

    power_grid = PowerGridGraph()
    buildings = power_grid.extract_building_centers_and_areas(
        str(footprints),
        clustering_crs=clustering_crs,
    )

    _build_graph_hierarchy(power_grid, config)
    net = _build_pandapower_network(power_grid, config)

    powerflow = _run_optional_powerflow(net, run_powerflow)
    topology = _topology_report(power_grid)
    report = _validation_report(
        footprints_path=footprints,
        config_path=config_file,
        config=config,
        power_grid=power_grid,
        buildings_count=len(buildings),
        net=net,
        topology=topology,
        powerflow=powerflow,
    )

    report_path: Path | None = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "synthetic_network_validation_report.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        if write_cache:
            _write_cache(output_dir, power_grid, net)

    return SyntheticNetworkBuildResult(
        power_grid=power_grid,
        net=net,
        validation_report=report,
        report_path=report_path,
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_graph_hierarchy(power_grid: PowerGridGraph, config: dict[str, Any]) -> None:
    loads = config["loads"]
    transformers = config["transformers"]
    max_load_per_building = float(loads["max_load_per_building"])
    diversity_factor_lv = float(loads.get("diversity_factor_lv", 5.0))
    diversity_factor_mv = float(loads.get("diversity_factor_mv", 1.3))
    diversity_factor_hv = float(loads.get("diversity_factor_hv", 1.1))
    mv_lv_capacity = float(transformers["lv_mv"]["capacity_kva"])
    hv_mv_capacity = float(transformers["mv_hv"]["capacity_kva"])
    utilization = float(transformers["lv_mv"].get("utilization_margin", 0.8))

    power_grid.create_lv_graph(
        max_load_per_building=max_load_per_building,
        mv_lv_transformer_capacity=mv_lv_capacity,
        capacity_utilization_factor=utilization,
        diversity_factor_lv=diversity_factor_lv,
    )
    power_grid.extend_graph_with_cim("graph_lv_buses")
    power_grid.create_building_graph(
        max_load_per_building=max_load_per_building,
        diversity_factor_lv=diversity_factor_lv,
    )

    power_grid.create_mv_graph(
        mv_lv_transformer_capacity=mv_lv_capacity,
        hv_mv_transformer_capacity=hv_mv_capacity,
        diversity_factor_mv=diversity_factor_mv,
    )
    power_grid.extend_graph_with_cim("graph_mv_buses")

    hv_substation_capacity = (
        len(power_grid.labels_mv) if power_grid.labels_mv is not None else 1
    ) * hv_mv_capacity
    power_grid.create_hv_substation_graph(
        hv_mv_transformer_capacity=hv_mv_capacity,
        hv_substation_capacity=hv_substation_capacity,
        diversity_factor_hv=diversity_factor_hv,
    )
    power_grid.extend_graph_with_cim("graph_hv_buses")
    power_grid.merge_graphs()


def _build_pandapower_network(
    power_grid: PowerGridGraph,
    config: dict[str, Any],
) -> pp.pandapowerNet:
    pp_config = {
        "buses": config["buses"],
        "lines": config["lines"],
        "transformers": {
            "lv_mv": dict(config["transformers"]["lv_mv"]),
            "mv_hv": dict(config["transformers"]["mv_hv"]),
        },
    }
    builder = PandapowerGridBuilder(power_grid=power_grid, config=pp_config)
    builder.build_lv_buses_and_lines()
    builder.build_mv_buses_and_lines()
    builder.build_hv_buses_and_lines()
    builder.build_loads_from_graph_buildings()
    builder.validate_network_consistency()
    builder.build_lv_mv_power_transformers()
    builder.build_mv_hv_power_transformers()
    builder.connect_hv_bus_to_ext_grid()
    builder.create_bus_geodata()
    return builder.get_pandapower_net()


def _run_optional_powerflow(net: pp.pandapowerNet, run_powerflow: bool) -> dict[str, Any]:
    if not run_powerflow:
        return {"attempted": False, "converged": None, "error": None}
    try:
        pp.runpp(
            net,
            algorithm="nr",
            init="auto",
            max_iteration=100,
            calculate_voltage_angles=True,
            enforce_q_lims=False,
        )
    except Exception as exc:  # pragma: no cover - exercised through report state
        return {"attempted": True, "converged": False, "error": str(exc)}
    return {"attempted": True, "converged": bool(net.converged), "error": None}


def _topology_report(power_grid: PowerGridGraph) -> dict[str, Any]:
    isolated = power_grid.check_for_isolated_nodes()
    counts = {name: len(nodes or []) for name, nodes in isolated.items()}
    return {
        "isolated_nodes_by_graph": counts,
        "isolated_nodes_total": int(sum(counts.values())),
    }


def _validation_report(
    *,
    footprints_path: Path,
    config_path: Path,
    config: dict[str, Any],
    power_grid: PowerGridGraph,
    buildings_count: int,
    net: pp.pandapowerNet,
    topology: dict[str, Any],
    powerflow: dict[str, Any],
) -> dict[str, Any]:
    valid = topology["isolated_nodes_total"] == 0
    if powerflow["attempted"]:
        valid = valid and bool(powerflow["converged"])

    return {
        "report_id": "synthetic_network_validation",
        "valid": valid,
        "source": {
            "footprints_path": str(footprints_path),
            "footprints_sha256": _sha256(footprints_path),
            "config_path": str(config_path),
            "config_sha256": _sha256(config_path),
        },
        "coordinate_reference_systems": {
            "source_crs": power_grid.source_crs,
            "geographic_crs": "EPSG:4326",
            "clustering_crs": power_grid.clustering_crs,
        },
        "sizing": {
            "max_load_per_building_kw": config["loads"]["max_load_per_building"],
            "diversity_factor_lv": config["loads"].get("diversity_factor_lv"),
            "diversity_factor_mv": config["loads"].get("diversity_factor_mv"),
            "diversity_factor_hv": config["loads"].get("diversity_factor_hv"),
            "lv_mv_transformer_capacity_kva": config["transformers"]["lv_mv"]["capacity_kva"],
            "lv_mv_utilization_margin": config["transformers"]["lv_mv"].get(
                "utilization_margin"
            ),
            "mv_hv_transformer_capacity_kva": config["transformers"]["mv_hv"][
                "capacity_kva"
            ],
        },
        "counts": {
            "buildings": int(buildings_count),
            "lv_graph_nodes": _graph_node_count(power_grid.graph_lv_buses),
            "mv_graph_nodes": _graph_node_count(power_grid.graph_mv_buses),
            "hv_graph_nodes": _graph_node_count(power_grid.graph_hv_buses),
            "pandapower_buses": int(len(net.bus)),
            "pandapower_lines": int(len(net.line)),
            "pandapower_transformers": int(len(net.trafo)),
            "pandapower_loads": int(len(net.load)),
            "external_grids": int(len(net.ext_grid)),
        },
        "topology": topology,
        "powerflow": powerflow,
    }


def _graph_node_count(graph: Any) -> int:
    return int(len(graph.nodes)) if graph is not None else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_cache(out_dir: Path, power_grid: PowerGridGraph, net: pp.pandapowerNet) -> None:
    with (out_dir / "pg_graph_cache.pkl").open("wb") as handle:
        pickle.dump(power_grid, handle)
    with (out_dir / "pp_net_cache.pkl").open("wb") as handle:
        pickle.dump(net, handle)


__all__ = [
    "SyntheticNetworkBuildResult",
    "build_synthetic_network_from_geojson",
]

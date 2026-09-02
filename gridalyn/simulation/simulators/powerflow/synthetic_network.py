"""Synthetic distribution-network generation for pandapower simulations.

This module turns building-footprint GeoJSON into a reproducible Gridalyn
network bundle: a :class:`PowerGridGraph`, a pandapower network, optional cache
files, and a validation report. It keeps the historical graph builder as the
engine, but exposes a project-friendly contract that can be used from CLI,
workflows, tests, and future utility adapters.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandapower as pp

from gridalyn.simulation.backends.registry import solve_power_flow
from gridalyn.twin.adapters.pandapower_builder import build_power_grid_and_network
from gridalyn.twin.core.graph import PowerGridGraph

# Cap on the number of over-capacity line indices recorded in the report so a
# pathologically undersized network cannot bloat the JSON; counts remain exact.
_OVER_CAPACITY_INDEX_CAP = 32

VALIDATION_FILENAME = "synthetic_network_validation.json"
"""File name of the build's domain diagnostic.

Renamed from ``synthetic_network_validation_report.json`` on 2026-09-02, and
the name is the whole point. This payload carries eight DOMAIN keys --
``counts``, ``topology``, ``sizing``, ``powerflow``,
``coordinate_reference_systems``, ``source``, ``valid``, ``report_id`` -- and
none of ``REQUIRED_REPORT_FIELDS``. It is a diagnostic of the network that was
built, not the run's own account of itself, so it is not a platform report and
must not look like one: the project catalog classified it ``unknown`` for
exactly that reason, and ``tests/test_report_contract.py`` treats a
``*_report.json`` name as a governed destination.

The alternative -- wrapping it in a report envelope -- was considered and
rejected on the repo's own rule: making a non-report into one breaks its own
consumers, and a diagnostic is not a run's account of itself.
"""


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
    building_peak_loads_kw: Sequence[float] | None = None,
    check_line_sizing: bool = False,
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
        building_peak_loads_kw: Optional per-building peak loads (kW) that
            override the uniform config envelope, one value per network load
            in load-table order. Transformer and line sizing still use the
            declared envelope; q/p ratios are preserved.
        check_line_sizing: When true, run the read-only line-sizing diagnostic
            on a deep copy after the build and emit a runtime warning on
            over-100% loading or a ~0 downstream-load/conductor correlation.
            Adds no report bytes. Defaults to ``False`` (zero behavior change).
    """

    config_file = Path(config_path)
    config = _load_json(config_file)
    return build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=config,
        out_dir=out_dir,
        config_source=config_file,
        clustering_crs=clustering_crs,
        write_cache=write_cache,
        run_powerflow=run_powerflow,
        building_peak_loads_kw=building_peak_loads_kw,
        check_line_sizing=check_line_sizing,
    )


def build_synthetic_network_from_config(
    *,
    footprints_path: Path | str,
    config: dict[str, Any],
    out_dir: Path | str | None = None,
    config_source: Path | str = "runtime_config",
    clustering_crs: str | int | None = "auto",
    write_cache: bool = False,
    run_powerflow: bool = False,
    building_peak_loads_kw: Sequence[float] | None = None,
    check_line_sizing: bool = False,
) -> SyntheticNetworkBuildResult:
    """Build a synthetic distribution network from an explicit config mapping.

    Args:
        footprints_path: GeoJSON file with building polygons.
        config: Grid configuration mapping.
        out_dir: Optional directory for cache files and validation report.
        config_source: Provenance label or path recorded in the report.
        clustering_crs: Metric CRS for clustering (``"auto"`` estimates UTM).
        write_cache: When true, write the graph/net cache pickles to ``out_dir``.
        run_powerflow: When true, run an AC power flow and record convergence.
        building_peak_loads_kw: Optional per-building peak loads (kW) overriding
            the uniform config envelope.
        check_line_sizing: When true, run the read-only line-sizing diagnostic
            on a deep copy after the build and warn on over-100% loading or a
            ~0 downstream-load/conductor correlation. Adds no report bytes.
            Defaults to ``False`` (zero behavior change).

    Returns:
        A :class:`SyntheticNetworkBuildResult`.
    """

    footprints = Path(footprints_path)
    output_dir = Path(out_dir) if out_dir is not None else None

    power_grid, net = build_power_grid_and_network(
        footprints_path=footprints,
        config=config,
        clustering_crs=clustering_crs,
    )
    line_sizing = _apply_load_aware_sizing_if_configured(net, config)
    if building_peak_loads_kw is not None:
        _apply_building_peak_loads(net, building_peak_loads_kw)

    powerflow = _run_optional_powerflow(net, run_powerflow)
    topology = _topology_report(power_grid)
    report = _validation_report(
        footprints_path=footprints,
        config_source=config_source,
        config=config,
        power_grid=power_grid,
        buildings_count=len(power_grid.building_data),
        net=net,
        topology=topology,
        powerflow=powerflow,
        loads_source=(
            "generated" if building_peak_loads_kw is not None else "config_envelope"
        ),
        line_sizing=line_sizing,
    )

    if check_line_sizing:
        _warn_on_line_sizing(net)

    report_path: Path | None = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / VALIDATION_FILENAME
        report_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        if write_cache:
            _write_cache(output_dir, power_grid, net)

    return SyntheticNetworkBuildResult(
        power_grid=power_grid,
        net=net,
        validation_report=report,
        report_path=report_path,
    )


def _warn_on_line_sizing(net: pp.pandapowerNet) -> None:
    """Run the read-only line-sizing diagnostic on a copy and warn on issues.

    The diagnostic runs on a deep copy so the build result's network is never
    mutated. A runtime warning (no report bytes) is emitted when any voltage
    level shows lines loaded over 100% at design, or when the structural
    downstream-load vs ``max_i_ka`` correlation is finite and near zero (the
    conductor-bias signal: ratings that do not track downstream load).

    Args:
        net: The freshly built pandapower network. Not mutated.
    """
    # Local import keeps the default import graph unchanged (mirrors the local
    # ``line_sizing_select`` import on the load-aware path); the diagnostic is
    # read-only and runs no power flow here.
    import copy

    from gridalyn.simulation.analytics.line_sizing import analyze_line_sizing

    diag = analyze_line_sizing(copy.deepcopy(net))

    over_levels = [
        level
        for level, agg in diag.per_level.items()
        if agg.get("share_above_100pct") is not None
        and float(agg["share_above_100pct"]) > 0
    ]
    if over_levels:
        warnings.warn(
            "check_line_sizing: lines loaded over 100% at design on level(s) "
            f"{sorted(over_levels)} -- some conductors are undersized for the "
            "load they carry. Review the line catalog or enable load-aware "
            "sizing.",
            UserWarning,
            stacklevel=2,
        )

    pearson = diag.correlations.get("downstream_load_vs_max_i_ka", {}).get("pearson")
    if pearson is not None and np.isfinite(pearson) and abs(float(pearson)) < 0.1:
        warnings.warn(
            "check_line_sizing: downstream-load vs max_i_ka correlation is "
            f"~0 (pearson={float(pearson):.3f}) -- conductor ratings do not "
            "track downstream load (uniform-per-level sizing). Enable "
            "load-aware sizing to size lines for transiting load.",
            UserWarning,
            stacklevel=2,
        )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _apply_load_aware_sizing_if_configured(
    net: pp.pandapowerNet,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Run the opt-in load-aware line-sizing post-pass, if configured.

    Returns:
        ``None`` under the default ``uniform`` sizing mode (so the validation
        report stays byte-identical to the historical generator output) or a
        deterministic summary block when ``config["lines"]["sizing"]["mode"]
        == "load_aware"`` ran.
    """
    mode = config.get("lines", {}).get("sizing", {}).get("mode", "uniform")
    if mode != "load_aware":
        return None
    # Local import keeps the default ``uniform`` path's import graph
    # unchanged, preserving byte-identity with the historical generator.
    from gridalyn.simulation.simulators.powerflow.line_sizing_select import (
        size_lines_load_aware,
    )

    sizing_rows = size_lines_load_aware(net, config)
    return _summarize_line_sizing(sizing_rows)


def _summarize_line_sizing(sizing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce per-line sizing rows to a deterministic report summary block.

    Surfaces conductor over-capacity (a line whose design current exceeds the
    largest catalog conductor, so it stays thermally over 100% at design load).
    These shortfalls are an accepted physical limit at the catalog ceiling
    rather than a build failure, but they must be visible in the report instead
    of silently dropped (CR-01).

    Args:
        sizing_rows: The per-line summary returned by
            :func:`size_lines_load_aware` (one dict per on-tree line).

    Returns:
        A deterministic summary block with the sizing mode, the count of lines
        sized, the over-capacity count, the per-level over-capacity breakdown
        (only non-zero levels, level-sorted), and a capped, sorted list of the
        over-capacity line indices.
    """
    over_rows = [row for row in sizing_rows if row.get("over_capacity")]
    over_levels: dict[str, int] = {}
    for row in over_rows:
        level = str(row["level"])
        over_levels[level] = over_levels.get(level, 0) + 1

    return {
        "mode": "load_aware",
        "lines_sized": len(sizing_rows),
        "over_capacity_count": len(over_rows),
        "over_capacity_levels": dict(sorted(over_levels.items())),
        "over_capacity_line_indices": sorted(int(row["idx"]) for row in over_rows)[
            :_OVER_CAPACITY_INDEX_CAP
        ],
    }


def _apply_building_peak_loads(
    net: pp.pandapowerNet,
    building_peak_loads_kw: Sequence[float],
) -> None:
    """Override per-building load magnitudes, preserving each load's q/p ratio."""
    if len(building_peak_loads_kw) != len(net.load):
        raise ValueError(
            f"building_peak_loads_kw has {len(building_peak_loads_kw)} values "
            f"but the network has {len(net.load)} loads"
        )
    for position, load_idx in enumerate(net.load.index):
        p_old = float(net.load.at[load_idx, "p_mw"])
        q_old = float(net.load.at[load_idx, "q_mvar"])
        ratio = q_old / p_old if p_old else 0.0
        p_new = float(building_peak_loads_kw[position]) / 1000.0
        if p_new <= 0:
            raise ValueError(
                f"building_peak_loads_kw[{position}] must be positive, got {p_new * 1000.0}"
            )
        net.load.at[load_idx, "p_mw"] = p_new
        net.load.at[load_idx, "q_mvar"] = p_new * ratio


def _run_optional_powerflow(
    net: pp.pandapowerNet, run_powerflow: bool
) -> dict[str, Any]:
    if not run_powerflow:
        return {"attempted": False, "converged": None, "error": None}
    try:
        solve_power_flow(
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
    config_source: Path | str,
    config: dict[str, Any],
    power_grid: PowerGridGraph,
    buildings_count: int,
    net: pp.pandapowerNet,
    topology: dict[str, Any],
    powerflow: dict[str, Any],
    loads_source: str = "config_envelope",
    line_sizing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid = topology["isolated_nodes_total"] == 0
    if powerflow["attempted"]:
        valid = valid and bool(powerflow["converged"])

    report: dict[str, Any] = {
        "report_id": "synthetic_network_validation",
        "valid": valid,
        "source": {
            "footprints_path": str(footprints_path),
            "footprints_sha256": _sha256(footprints_path),
            "config_path": str(config_source),
            "config_sha256": _config_sha256(config, config_source),
        },
        "coordinate_reference_systems": {
            "source_crs": power_grid.source_crs,
            "geographic_crs": "EPSG:4326",
            "clustering_crs": power_grid.clustering_crs,
        },
        "sizing": {
            "loads_source": loads_source,
            "max_load_per_building_kw": config["loads"]["max_load_per_building"],
            "diversity_factor_lv": config["loads"].get("diversity_factor_lv"),
            "diversity_factor_mv": config["loads"].get("diversity_factor_mv"),
            "diversity_factor_hv": config["loads"].get("diversity_factor_hv"),
            "lv_mv_transformer_capacity_kva": config["transformers"]["lv_mv"][
                "capacity_kva"
            ],
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

    # Strictly gated on the opt-in load-aware path: under ``uniform``/default
    # ``line_sizing`` is ``None`` and NO key (no new bytes) is added, so
    # historical project reports stay byte-identical (LINESIZE-01 / CR-01).
    if line_sizing is not None:
        report["line_sizing"] = line_sizing
        over_count = int(line_sizing.get("over_capacity_count", 0))
        if over_count > 0:
            levels = line_sizing.get("over_capacity_levels", {})
            warning = (
                f"line_sizing: {over_count} line(s) over capacity at the "
                f"catalog conductor ceiling (per-level: {levels}); design "
                "current exceeds the largest available conductor so these "
                "lines stay thermally over 100% at design load (accepted "
                "physical limit, surfaced not silently clipped)."
            )
            report.setdefault("warnings", []).append(warning)

    return report


def _graph_node_count(graph: Any) -> int:
    return int(len(graph.nodes)) if graph is not None else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_sha256(config: dict[str, Any], source: Path | str) -> str:
    source_path = Path(source)
    if source_path.exists():
        return _sha256(source_path)
    payload = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_cache(
    out_dir: Path, power_grid: PowerGridGraph, net: pp.pandapowerNet
) -> None:
    with (out_dir / "pg_graph_cache.pkl").open("wb") as handle:
        pickle.dump(power_grid, handle)
    with (out_dir / "pp_net_cache.pkl").open("wb") as handle:
        pickle.dump(net, handle)


__all__ = [
    "SyntheticNetworkBuildResult",
    "build_synthetic_network_from_config",
    "build_synthetic_network_from_geojson",
]

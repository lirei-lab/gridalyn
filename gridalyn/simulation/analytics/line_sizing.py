"""Read-only AC line-sizing diagnostic.

Quantifies whether AC lines are sized for the load they carry. For every line
in a pandapower network this computes the aggregated downstream demand sitting
on the far-from-root side of the line (sum of load ``p_mw`` in that subtree of
the rooted radial tree) and cross-tabulates it against the line's thermal
rating (``max_i_ka``) and its post-power-flow ``loading_percent`` -- per voltage
level, with Pearson/Spearman correlations and over/under-utilization shares.

The core entry point is strictly read-only: it never mutates the input network
nor any baseline. The synthetic convenience wrapper runs any fallback power flow
on a deep copy so the build result's network is likewise left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: F401  (re-exported for typed wrapper signatures)
from typing import Any, Mapping, Sequence

import networkx as nx
import numpy as np
from scipy import stats

_ROW_KEYS: tuple[str, ...] = (
    "idx",
    "level",
    "max_i_ka",
    "length_km",
    "downstream_load_mw",
    "downstream_count",
    "loading_percent",
)


@dataclass(frozen=True)
class LineSizingResult:
    """Structured result of a read-only line-sizing diagnostic.

    Attributes:
        converged: Whether the loading_percent values reflect a converged power
            flow. When ``False`` every ``loading_percent`` row entry is ``NaN``
            but the structural downstream-load vs ``max_i_ka`` correlation is
            still populated.
        rows: One dict per on-tree line, each carrying the keys ``idx``,
            ``level``, ``max_i_ka``, ``length_km``, ``downstream_load_mw``,
            ``downstream_count`` and ``loading_percent``.
        per_level: Per voltage-level aggregates keyed by ``"LV"`` / ``"MV"`` /
            ``"HV"`` (only levels present on the tree appear).
        correlations: Correlation blocks. ``"downstream_load_vs_max_i_ka"`` is
            always present (structural); ``"downstream_load_vs_loading_percent"``
            is present only when finite loading values exist.
    """

    converged: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    per_level: dict[str, dict[str, Any]] = field(default_factory=dict)
    correlations: dict[str, dict[str, float]] = field(default_factory=dict)


def _classify_level(vn_kv: float) -> str:
    """Classify a voltage level from a nominal bus voltage in kV.

    Args:
        vn_kv: Nominal voltage of the line's ``from_bus`` in kV.

    Returns:
        ``"LV"`` when below 1 kV, ``"MV"`` when below 60 kV, else ``"HV"``.
    """
    if vn_kv < 1:
        return "LV"
    if vn_kv < 60:
        return "MV"
    return "HV"


def _build_bus_graph(net: Any) -> nx.Graph:
    """Build an undirected bus graph with lines and transformers as edges.

    Args:
        net: A pandapower network (read only).

    Returns:
        A graph whose nodes are bus indices; line edges carry ``kind="line"``
        and the originating line ``idx``, transformer edges carry
        ``kind="trafo"``.
    """
    graph = nx.Graph()
    graph.add_nodes_from(net.bus.index.tolist())
    for line_idx, row in net.line.iterrows():
        graph.add_edge(
            int(row["from_bus"]),
            int(row["to_bus"]),
            kind="line",
            idx=int(line_idx),
        )
    for _, row in net.trafo.iterrows():
        graph.add_edge(int(row["hv_bus"]), int(row["lv_bus"]), kind="trafo")
    return graph


def _root_and_accumulate(
    graph: nx.Graph, root: int, load_by_bus: Mapping[int, float]
) -> tuple[dict[int, int], dict[int, float], dict[int, int]]:
    """Root the tree and post-order accumulate subtree load and count.

    Args:
        graph: Undirected bus graph.
        root: Root bus index (the ext_grid bus).
        load_by_bus: Per-bus aggregated load in MW.

    Returns:
        Tuple of parent pointers, per-bus subtree load (MW) and per-bus subtree
        load count.
    """
    parent: dict[int, int] = {root: -1}
    order: list[int] = []
    for node in nx.bfs_tree(graph, root):
        order.append(node)
        for neighbor in graph.neighbors(node):
            if neighbor not in parent:
                parent[neighbor] = node
    subtree_load = {b: float(load_by_bus.get(b, 0.0)) for b in graph.nodes}
    subtree_count = {b: (1 if b in load_by_bus else 0) for b in graph.nodes}
    for node in reversed(order):
        p = parent.get(node, -1)
        if p != -1:
            subtree_load[p] += subtree_load[node]
            subtree_count[p] += subtree_count[node]
    return parent, subtree_load, subtree_count


def _line_loading_percent(net: Any, line_idx: int, converged: bool) -> float:
    """Read a line's post-power-flow loading percent without running a flow.

    Args:
        net: pandapower network (read only).
        line_idx: Line index.
        converged: Whether a converged power flow result is available.

    Returns:
        ``loading_percent`` from ``net.res_line`` when available, else ``NaN``.
    """
    res_line = getattr(net, "res_line", None)
    if converged and res_line is not None and line_idx in res_line.index:
        return float(res_line.at[line_idx, "loading_percent"])
    return float("nan")


def _build_rows(
    net: Any,
    parent: Mapping[int, int],
    subtree_load: Mapping[int, float],
    subtree_count: Mapping[int, int],
    converged: bool,
) -> list[dict[str, Any]]:
    """Build per-line diagnostic rows for on-tree lines.

    Args:
        net: pandapower network (read only).
        parent: Parent pointers from the rooted tree.
        subtree_load: Per-bus subtree load in MW.
        subtree_count: Per-bus subtree load count.
        converged: Whether a converged power flow result is available.

    Returns:
        A list of row dicts, one per on-tree line.
    """
    bus_vn = net.bus["vn_kv"].to_dict()
    rows: list[dict[str, Any]] = []
    for line_idx, row in net.line.iterrows():
        from_bus, to_bus = int(row["from_bus"]), int(row["to_bus"])
        if parent.get(to_bus) == from_bus:
            child = to_bus
        elif parent.get(from_bus) == to_bus:
            child = from_bus
        else:
            continue
        rows.append(
            {
                "idx": int(line_idx),
                "level": _classify_level(float(bus_vn[from_bus])),
                "max_i_ka": float(row["max_i_ka"]),
                "length_km": float(row["length_km"]),
                "downstream_load_mw": float(subtree_load[child]),
                "downstream_count": int(subtree_count[child]),
                "loading_percent": _line_loading_percent(net, int(line_idx), converged),
            }
        )
    return rows


def _corr(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Compute NaN-masked Pearson and Spearman correlations.

    Args:
        a: First sample vector.
        b: Second sample vector.

    Returns:
        A mapping with ``"pearson"`` and ``"spearman"``; both ``NaN`` when fewer
        than three finite pairs remain or either side has zero variance.
    """
    mask = ~(np.isnan(a) | np.isnan(b))
    x, y = a[mask], b[mask]
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return {"pearson": float("nan"), "spearman": float("nan")}
    return {
        "pearson": float(stats.pearsonr(x, y)[0]),
        "spearman": float(stats.spearmanr(x, y)[0]),
    }


def _level_aggregate(level_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the aggregate summary for the lines of a single voltage level.

    Args:
        level_rows: Diagnostic rows belonging to one voltage level.

    Returns:
        A mapping of distinct max_i_ka values, downstream-load and
        loading_percent summary statistics, and loading-band shares.
    """
    load = np.array([r["downstream_load_mw"] for r in level_rows], dtype=float)
    max_i = np.array([r["max_i_ka"] for r in level_rows], dtype=float)
    loading = np.array([r["loading_percent"] for r in level_rows], dtype=float)
    distinct = sorted({round(v, 6) for v in max_i.tolist()})
    aggregate: dict[str, Any] = {
        "line_count": len(level_rows),
        "distinct_max_i_ka": distinct,
        "downstream_load_mw_min": float(load.min()),
        "downstream_load_mw_median": float(np.median(load)),
        "downstream_load_mw_max": float(load.max()),
        "loading_percent_min": None,
        "loading_percent_median": None,
        "loading_percent_max": None,
        "share_below_20pct": None,
        "share_above_80pct": None,
        "share_above_100pct": None,
    }
    finite = loading[np.isfinite(loading)]
    if finite.size:
        aggregate.update(
            {
                "loading_percent_min": float(finite.min()),
                "loading_percent_median": float(np.median(finite)),
                "loading_percent_max": float(finite.max()),
                "share_below_20pct": float((finite < 20).mean()),
                "share_above_80pct": float((finite > 80).mean()),
                "share_above_100pct": float((finite > 100).mean()),
            }
        )
    return aggregate


def _build_per_level(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group rows by voltage level and build each level's aggregate.

    Args:
        rows: All on-tree diagnostic rows.

    Returns:
        A mapping from level name to its aggregate (only present levels appear).
    """
    per_level: dict[str, dict[str, Any]] = {}
    for level in ("LV", "MV", "HV"):
        level_rows = [r for r in rows if r["level"] == level]
        if level_rows:
            per_level[level] = _level_aggregate(level_rows)
    return per_level


def _build_correlations(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Build structural and (optional) loading correlations over all lines.

    Args:
        rows: All on-tree diagnostic rows.

    Returns:
        Always includes ``"downstream_load_vs_max_i_ka"``; includes
        ``"downstream_load_vs_loading_percent"`` only when finite loading values
        exist.
    """
    load = np.array([r["downstream_load_mw"] for r in rows], dtype=float)
    max_i = np.array([r["max_i_ka"] for r in rows], dtype=float)
    loading = np.array([r["loading_percent"] for r in rows], dtype=float)
    correlations: dict[str, dict[str, float]] = {
        "downstream_load_vs_max_i_ka": _corr(load, max_i),
    }
    if np.isfinite(loading).any():
        correlations["downstream_load_vs_loading_percent"] = _corr(load, loading)
    return correlations


def analyze_line_sizing(
    net: Any, *, assume_converged: bool | None = None
) -> LineSizingResult:
    """Diagnose AC line sizing against downstream load -- strictly read-only.

    The input network is treated as immutable: only ``net.bus``, ``net.load``,
    ``net.line``, ``net.trafo``, ``net.ext_grid`` and (when present)
    ``net.res_line`` are read. No power flow is run here; this entry only reads
    existing results. Use :func:`analyze_synthetic_line_sizing` when a flow may
    need to be (re)run on a copy.

    Args:
        net: A pandapower network. Not mutated.
        assume_converged: Override convergence detection. When ``None`` the
            value of ``net.converged`` is used.

    Returns:
        A :class:`LineSizingResult` with per-line rows, per-level aggregates and
        correlations. When the flow has not converged, ``loading_percent``
        entries are ``NaN`` and ``converged`` is ``False`` but the structural
        downstream-load vs ``max_i_ka`` correlation is still computed.
    """
    converged = (
        bool(assume_converged)
        if assume_converged is not None
        else bool(getattr(net, "converged", False))
    )
    load_by_bus: dict[int, float] = net.load.groupby("bus")["p_mw"].sum().to_dict()
    graph = _build_bus_graph(net)
    root = int(net.ext_grid["bus"].iloc[0])
    parent, subtree_load, subtree_count = _root_and_accumulate(graph, root, load_by_bus)
    rows = _build_rows(net, parent, subtree_load, subtree_count, converged)
    return LineSizingResult(
        converged=converged,
        rows=rows,
        per_level=_build_per_level(rows),
        correlations=_build_correlations(rows),
    )


def _converge_on_copy(net: Any) -> tuple[Any, bool]:
    """Run a robust power flow on a deep copy of ``net``.

    Args:
        net: pandapower network to copy and solve. Not mutated.

    Returns:
        Tuple of the solved deep copy and its convergence flag.
    """
    import copy

    import pandapower as pp

    work = copy.deepcopy(net)
    converged = bool(getattr(work, "converged", False))
    if converged:
        return work, converged
    fallbacks: Sequence[dict[str, Any]] = (
        {},
        {"init": "flat", "max_iteration": 100},
        {"algorithm": "bfsw", "max_iteration": 100},
    )
    for kwargs in fallbacks:
        try:
            pp.runpp(work, **kwargs)
        except Exception:
            continue
        converged = bool(work.converged)
        if converged:
            break
    return work, converged


def analyze_synthetic_line_sizing(
    *,
    footprints_path: Path | str,
    config: Mapping[str, Any],
    clustering_crs: str | int | None = "auto",
    run_powerflow: bool = True,
    **build_kwargs: Any,
) -> LineSizingResult:
    """Build a synthetic network then run the read-only line-sizing diagnostic.

    Args:
        footprints_path: Path to the building-footprints GeoJSON.
        config: Synthetic-network configuration mapping.
        clustering_crs: CRS used to cluster footprints (``"auto"`` by default).
        run_powerflow: When ``True``, ensure a power flow is solved (on a deep
            copy) before reading loading values, so the build result's network
            stays unmodified.
        **build_kwargs: Forwarded to ``build_synthetic_network_from_config``
            (e.g. ``out_dir``, ``write_cache``).

    Returns:
        A :class:`LineSizingResult`. Non-convergence is handled gracefully:
        ``loading_percent`` is optional while the structural correlation is
        always computed.
    """
    from gridalyn.foundation.platform.capabilities import require_capabilities
    from gridalyn.simulation.simulators.powerflow.synthetic_network import (
        build_synthetic_network_from_config,
    )

    require_capabilities("sim", context="line-sizing diagnostic")
    build_kwargs.setdefault("write_cache", False)
    result = build_synthetic_network_from_config(
        footprints_path=footprints_path,
        config=dict(config),
        clustering_crs=clustering_crs,
        run_powerflow=run_powerflow,
        **build_kwargs,
    )
    net = result.net
    if run_powerflow and not bool(getattr(net, "converged", False)):
        work, converged = _converge_on_copy(net)
        return analyze_line_sizing(work, assume_converged=converged)
    return analyze_line_sizing(net)

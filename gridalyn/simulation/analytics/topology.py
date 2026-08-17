"""Radial-feeder topology analytics for grid and digital-twin studies.

Closes the two SDK gaps the flagship ``ev_hosting_flex/_topology.py`` named:

* **GAP-1 (TWIN-02):** per-line / per-transformer kW thermal rating
  (``kW = max_i_ka * vn_kv * sqrt(3) * 1000 * pf`` for lines;
  ``sn_mva * 1000 * pf`` for transformers).
* **GAP-2 (TWIN-03):** a radial downstream-bus map reconstructed by BFS over the
  ``net.line`` *and* ``net.trafo`` integer-index edges rooted at the ext_grid
  bus — traversing transformer hops so a feeder-head transformer's downstream
  set includes the LV subtree below it (D-04).

Plus the radiality + no-embedded-generation assertion (TWIN-04).

Dict keys follow the ``gridalyn/operations/constraints.py`` convention
(``line:{idx}`` -> ``cim:ACLineSegment``, ``transformer:{idx}`` ->
``cim:PowerTransformer``) so ``build_network_constraint_set`` plugs in cleanly.

This module operates ONLY on an already-loaded ``net`` object (an attribute-bag
of pandas DataFrames). It MUST NOT import ``pandapower`` / ``geopandas`` /
``lightsim2grid`` at module scope; ``networkx`` and ``numpy`` are graph/numeric
helpers, not in the heavy denylist.
"""

from __future__ import annotations

from typing import Any, Mapping

import networkx as nx
import numpy as np

__all__ = [
    "assert_radial_no_generation",
    "downstream_bus_map",
    "size_feeder_subtree_kw",
    "thermal_ratings_kw",
]


def _resolve_power_factor(pf: float | None, power_factor: float | None) -> float:
    """Resolve the effective power factor from ``pf`` and its deprecated alias.

    ``power_factor`` is the deprecated alias for ``pf``; either works alone,
    and passing both that disagree is a conflict. Returns the default 0.95
    when neither is given.

    Args:
        pf: Primary power factor, or ``None`` for the default.
        power_factor: Deprecated alias, or ``None``.

    Returns:
        The resolved power factor as a float.

    Raises:
        ValueError: If both ``pf`` and ``power_factor`` are given and disagree.
    """
    if pf is not None and power_factor is not None and float(power_factor) != float(pf):
        raise ValueError(
            f"thermal_ratings_kw received conflicting pf={pf!r} and "
            f"power_factor={power_factor!r}; pass only one of them."
        )
    if pf is not None:
        return float(pf)
    if power_factor is not None:
        return float(power_factor)
    return 0.95


def thermal_ratings_kw(
    net: Any, *, pf: float | None = None, power_factor: float | None = None
) -> dict[str, float]:
    """Return the per-line and per-transformer kW thermal ratings.

    GAP-1 (TWIN-02): for each line ``kW = max_i_ka * vn_kv(from_bus) * sqrt(3) *
    1000 * pf``; for each transformer ``kW = sn_mva * 1000 * pf``. Keys follow
    the constraints convention ``line:{idx}`` / ``transformer:{idx}``.

    Args:
        net: Loaded pandapower-style net (attribute-bag of pandas DataFrames
            with ``bus``, ``line`` and ``trafo`` tables).
        pf: Power factor in ``(0, 1]`` for the kW conversion (default 0.95).
        power_factor: Deprecated alias for ``pf``; if both are given they must
            agree.

    Returns:
        Mapping ``{"line:{idx}": float, "transformer:{idx}": float}`` aligned to
        the net's ``line`` and ``trafo`` row order.

    Raises:
        ValueError: If ``pf`` is not in ``(0, 1]``, if both ``pf`` and
            ``power_factor`` are given and disagree, or if a required net table
            or column is absent.
    """
    resolved_pf = _resolve_power_factor(pf, power_factor)
    if not 0.0 < resolved_pf <= 1.0:
        raise ValueError(
            f"thermal_ratings_kw received pf={resolved_pf}, which is outside "
            "(0, 1]; pass a power factor in (0, 1] for the kW conversion."
        )
    for table in ("bus", "line", "trafo"):
        if not hasattr(net, table) or getattr(net, table) is None:
            raise ValueError(
                f"thermal_ratings_kw requires the net.{table} table; the "
                "provided net has none. Remediation: pass a loaded pandapower-"
                "style net with bus/line/trafo."
            )
    # Located column validation: a missing column raises a ValueError naming
    # the table and column (and the fix), not a bare pandas KeyError.
    required_columns = {
        "bus": ("vn_kv",),
        "line": ("from_bus", "to_bus", "max_i_ka"),
        "trafo": ("hv_bus", "lv_bus", "sn_mva"),
    }
    for table, columns in required_columns.items():
        frame = getattr(net, table)
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(
                f"thermal_ratings_kw requires net.{table} columns "
                f"{', '.join(missing)}; the provided net.{table} has: "
                f"{', '.join(str(c) for c in frame.columns) or 'no columns'}. "
                "Remediation: pass a loaded pandapower-style net with the full "
                "bus/line/trafo column set."
            )
    vn = net.bus["vn_kv"].to_numpy(dtype="float64")
    from_bus = net.line["from_bus"].to_numpy()
    vn_from = vn[from_bus]
    max_i_ka = net.line["max_i_ka"].to_numpy(dtype="float64")
    line_kw = max_i_ka * vn_from * np.sqrt(3.0) * 1000.0 * resolved_pf
    trafo_kw = net.trafo["sn_mva"].to_numpy(dtype="float64") * 1000.0 * resolved_pf
    ratings: dict[str, float] = {}
    for idx, value in zip(net.line.index, line_kw, strict=True):
        ratings[f"line:{int(idx)}"] = float(value)
    for idx, value in zip(net.trafo.index, trafo_kw, strict=True):
        ratings[f"transformer:{int(idx)}"] = float(value)
    return ratings


def _network_graph(net: Any) -> nx.Graph:
    """Build the undirected line+transformer connectivity graph (integer buses)."""
    graph = nx.Graph()
    graph.add_nodes_from(net.bus.index.tolist())
    for a, b in net.line[["from_bus", "to_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    for a, b in net.trafo[["hv_bus", "lv_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    return graph


def downstream_bus_map(
    net: Any, root_bus: int | None = None
) -> dict[str, frozenset[int]]:
    """Return per-element downstream-bus frozensets keyed ``line:``/``transformer:``.

    GAP-2 (TWIN-03): reconstructs a directed radial tree rooted at the ext_grid
    bus (or a caller-supplied root) from the ``net.line`` and ``net.trafo``
    integer-index edges (transformer-hop aware, D-04). For each line and
    transformer, the value is the frozenset of buses strictly on the far-from-
    root side of that edge (including the far endpoint itself).

    Args:
        net: Loaded pandapower-style net.
        root_bus: Optional integer bus index to root the tree at. Defaults to
            the ext_grid bus.

    Returns:
        Mapping ``{f"line:{idx}" | f"transformer:{idx}": frozenset[bus_idx]}``.

    Raises:
        ValueError: If no ext_grid table exists (and no root is supplied).
    """
    if root_bus is None:
        if not hasattr(net, "ext_grid") or len(net.ext_grid) == 0:
            raise ValueError(
                "downstream_bus_map requires a net.ext_grid table (or an explicit "
                "root_bus=) to root the radial tree; the provided net has none."
            )
        root = int(net.ext_grid["bus"].iloc[0])
    else:
        root = int(root_bus)
    graph = _network_graph(net)

    line_edges = [
        (int(a), int(b))
        for a, b in net.line[["from_bus", "to_bus"]].itertuples(index=False)
    ]
    trafo_edges = [
        (int(a), int(b))
        for a, b in net.trafo[["hv_bus", "lv_bus"]].itertuples(index=False)
    ]

    # Orient edges away from the root -> directed tree for descendant queries.
    parent = {child: par for child, par in nx.bfs_predecessors(graph, root)}
    directed = nx.DiGraph((par, child) for child, par in parent.items())
    directed.add_node(root)

    downstream: dict[str, frozenset[int]] = {}
    for idx, (a, b) in zip(net.line.index, line_edges, strict=True):
        # The far-from-root endpoint is the child of the other endpoint.
        far = b if parent.get(b) == a else a
        downstream[f"line:{int(idx)}"] = frozenset(
            nx.descendants(directed, far) | {far}
        )
    for idx, (hv, lv) in zip(net.trafo.index, trafo_edges, strict=True):
        far = lv if parent.get(lv) == hv else hv
        downstream[f"transformer:{int(idx)}"] = frozenset(
            nx.descendants(directed, far) | {far}
        )
    return downstream


def assert_radial_no_generation(net: Any) -> None:
    """Assert the modeled net is a single radial tree with no embedded generation.

    Precondition for the downstream-sum congestion proxy (TWIN-04). Fails loudly
    with a located, remediating :class:`ValueError` when the line+transformer
    graph is not a tree, or when ``net.gen`` / ``net.sgen`` is non-empty.

    Args:
        net: Loaded pandapower-style net.

    Raises:
        ValueError: If the network is non-radial or carries embedded generation.
    """
    graph = _network_graph(net)
    if not nx.is_tree(graph):
        raise ValueError(
            "topology is not radial: the line+transformer graph has "
            f"{nx.number_connected_components(graph)} component(s) and "
            f"{graph.number_of_edges()} edges for {graph.number_of_nodes()} buses "
            "(a radial tree needs edges == buses-1). The downstream-sum congestion "
            "proxy requires a single loop-free feeder. Remediation: rebuild the "
            "topology cache, or restrict the study to the extracted single feeder "
            "subtree."
        )
    if (hasattr(net, "gen") and len(net.gen)) or (
        hasattr(net, "sgen") and len(net.sgen)
    ):
        raise ValueError(
            "topology has embedded generation "
            f"(gen={len(net.gen)}, sgen={len(net.sgen)}); the downstream-sum proxy "
            "assumes load-only radial flow. Remediation: exclude the generation or "
            "extend the proxy to net injection."
        )


def size_feeder_subtree_kw(
    element_keys: Mapping[str, frozenset[int]],
    nameplate_kw_by_bus: Mapping[int, float],
    *,
    peak_factor: float,
    utilization_margin: float = 0.8,
) -> dict[str, float]:
    """Load-aware size every feeder-subtree element to its annual winter peak.

    For each element (the feeder transformer AND every interior line in the
    feeder subtree), the downstream nameplate sum is taken over the element's
    downstream buses and resized via ``ceil((nameplate * peak_factor) /
    utilization_margin)``. Only elements present in ``element_keys`` are sized;
    every other ``line:*`` / ``transformer:*`` rating is left untouched by the
    caller.

    Args:
        element_keys: Mapping ``element_key -> downstream-bus frozenset`` for the
            feeder-subtree elements to resize (transformer + interior lines).
        nameplate_kw_by_bus: Per-bus nameplate kW (the static nameplate sum, NOT
            the annual peak).
        peak_factor: The annual winter-peak multiplier (``> 0``).
        utilization_margin: Headroom margin in ``(0, 1]`` (default 0.8).

    Returns:
        Mapping ``element_key -> resized kW rating`` (float64, rounded up).
    """
    import math

    if not 0.0 < utilization_margin <= 1.0:
        raise ValueError(
            f"size_feeder_subtree_kw received utilization_margin="
            f"{utilization_margin}, which is outside (0, 1]. Remediation: pass a "
            "headroom fraction in (0, 1] (the line precedent uses 0.8)."
        )
    resized: dict[str, float] = {}
    for key, downstream_buses in element_keys.items():
        downstream_nameplate_kw = float(
            sum(float(nameplate_kw_by_bus.get(int(b), 0.0)) for b in downstream_buses)
        )
        required = (downstream_nameplate_kw * float(peak_factor)) / float(
            utilization_margin
        )
        resized[key] = float(math.ceil(required))
    return resized

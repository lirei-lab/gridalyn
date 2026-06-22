"""Project-local radial-feeder topology helpers for ev_hosting_flex.

Closes the two SDK gaps over the cached pandapower ``net`` that the
downstream-sum congestion proxy depends on:

* **GAP-1 (TWIN-02):** per-line / per-transformer kW thermal rating
  (``kW = max_i_ka * vn_kv * √3 * 1000 * pf`` for lines; ``sn_mva * 1000 * pf``
  for transformers).
* **GAP-2 (TWIN-03):** a radial downstream-bus map reconstructed by BFS over the
  ``net.line`` *and* ``net.trafo`` integer-index edges rooted at the ext_grid bus
  — traversing transformer hops so a feeder-head transformer's downstream set
  includes the LV subtree below it (D-04).

Plus the radiality + no-embedded-generation assertion (TWIN-04) and the
deterministic single-feeder selection rule (D-01/D-02).

Dict keys follow the ``gridalyn/operations/constraints.py`` convention
(``line:{idx}`` → ``cim:ACLineSegment``, ``transformer:{idx}`` →
``cim:PowerTransformer``) so Phase 9's ``build_network_constraint_set`` plugs in
cleanly.

GUARD-02: this module operates ONLY on the already-loaded ``net`` object (an
attribute-bag of pandas DataFrames). It must NOT ``import pandapower`` /
``geopandas`` / ``lightsim2grid`` at module scope; ``networkx`` and ``numpy``
are graph/numeric helpers, not in the heavy denylist.

Numeric anchors verified against the real cached net (RESEARCH.md Code Examples
263-359): line0 ≈ 230.363 kW, trafo0 = 199.50 kW at pf=0.95, ext_grid root bus
3561, selected ``trafo_idx=64``.
"""

from __future__ import annotations

from typing import Any, Mapping

import networkx as nx
import numpy as np

from projects.ev_hosting_flex.scripts.config import FEEDER_ID, POWER_FACTOR

# MV/LV distribution-transformer voltage signature (kV) used for feeder ranking.
_MV_LV_VOLTAGE = (25.0, 0.4)


def line_rating_kw(net: Any, pf: float = POWER_FACTOR) -> np.ndarray:
    """Return the per-line apparent-power kW rating in float64.

    ``kW = max_i_ka * vn_kv(from_bus) * √3 * 1000 * pf``.

    Args:
        net: Loaded pandapower-style net (attribute-bag of pandas DataFrames).
        pf: Power factor for the kW conversion (D-05; default ``POWER_FACTOR``).

    Returns:
        A float64 ``numpy`` array aligned to ``net.line`` row order.
    """
    vn = net.bus["vn_kv"].to_numpy(dtype="float64")
    from_bus = net.line["from_bus"].to_numpy()
    vn_from = vn[from_bus]
    max_i_ka = net.line["max_i_ka"].to_numpy(dtype="float64")
    return max_i_ka * vn_from * np.sqrt(3.0) * 1000.0 * float(pf)


def trafo_rating_kw(net: Any, pf: float = POWER_FACTOR) -> np.ndarray:
    """Return the per-transformer kW rating in float64.

    ``kW = sn_mva * 1000 * pf``.

    Args:
        net: Loaded pandapower-style net.
        pf: Power factor for the kW conversion (D-05; default ``POWER_FACTOR``).

    Returns:
        A float64 ``numpy`` array aligned to ``net.trafo`` row order.
    """
    sn_mva = net.trafo["sn_mva"].to_numpy(dtype="float64")
    return sn_mva * 1000.0 * float(pf)


def _network_graph(net: Any) -> nx.Graph:
    """Build the undirected line+transformer connectivity graph (integer buses)."""
    graph = nx.Graph()
    graph.add_nodes_from(net.bus.index.tolist())
    for a, b in net.line[["from_bus", "to_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    for a, b in net.trafo[["hv_bus", "lv_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    return graph


def build_downstream_map(net: Any) -> dict[str, frozenset[int]]:
    """Return per-element downstream-bus frozensets keyed ``line:``/``transformer:``.

    Reconstructs a directed radial tree rooted at the ext_grid bus from the
    ``net.line`` and ``net.trafo`` integer-index edges (transformer-hop aware,
    TWIN-03/D-04). For each line and transformer, the value is the frozenset of
    buses strictly on the far-from-root side of that edge (including the far
    endpoint itself).

    Args:
        net: Loaded pandapower-style net.

    Returns:
        Mapping ``{f"line:{idx}" | f"transformer:{idx}": frozenset[bus_idx]}``.
    """
    root = int(net.ext_grid["bus"].iloc[0])
    graph = _network_graph(net)

    line_edges = [
        (int(a), int(b))
        for a, b in net.line[["from_bus", "to_bus"]].itertuples(index=False)
    ]
    trafo_edges = [
        (int(a), int(b))
        for a, b in net.trafo[["hv_bus", "lv_bus"]].itertuples(index=False)
    ]

    # Orient edges away from the root → directed tree for descendant queries.
    parent = {child: par for child, par in nx.bfs_predecessors(graph, root)}
    directed = nx.DiGraph((par, child) for child, par in parent.items())
    directed.add_node(root)

    downstream: dict[str, frozenset[int]] = {}
    for idx, (a, b) in zip(net.line.index, line_edges):
        # The far-from-root endpoint is the child of the other endpoint.
        far = b if parent.get(b) == a else a
        downstream[f"line:{int(idx)}"] = frozenset(
            nx.descendants(directed, far) | {far}
        )
    for idx, (hv, lv) in zip(net.trafo.index, trafo_edges):
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
            "ev_hosting_flex topology is not radial: the line+transformer graph "
            f"has {nx.number_connected_components(graph)} component(s) and "
            f"{graph.number_of_edges()} edges for {graph.number_of_nodes()} buses "
            "(a radial tree needs edges == buses-1). The downstream-sum congestion "
            "proxy requires a single loop-free feeder. Remediation: rebuild the "
            "topology cache, or restrict the study to the extracted single feeder "
            "subtree."
        )
    if len(net.gen) or len(net.sgen):
        raise ValueError(
            "ev_hosting_flex topology has embedded generation "
            f"(gen={len(net.gen)}, sgen={len(net.sgen)}); the downstream-sum proxy "
            "assumes load-only radial flow. Remediation: exclude the generation or "
            "extend the proxy to net injection."
        )


def select_feeder(
    net: Any,
    downstream_map: Mapping[str, frozenset[int]],
    config: Mapping[str, Any] | None = None,
) -> int:
    """Deterministically select the study feeder's MV/LV transformer index.

    Honors a ``config["feeder_id"]`` (or module ``FEEDER_ID``) override; otherwise
    ranks the MV/LV (25→0.4 kV) distribution transformers by their downstream
    building load and picks the maximum, with a deterministic ``(-load_kw, idx)``
    tie-break (D-01/D-02).

    Args:
        net: Loaded pandapower-style net.
        downstream_map: Output of :func:`build_downstream_map`.
        config: Optional mapping; ``feeder_id`` (if not ``None``) overrides the
            ranking and is returned verbatim.

    Returns:
        The selected transformer integer index.
    """
    override = config.get("feeder_id") if config else None
    if override is None:
        override = FEEDER_ID
    if override is not None:
        return int(override)

    load_by_bus = net.load.groupby("bus")["p_mw"].sum()
    vn = net.bus["vn_kv"]
    candidates: list[tuple[float, int]] = []
    for idx, row in net.trafo.iterrows():
        signature = (float(vn.loc[int(row.hv_bus)]), float(vn.loc[int(row.lv_bus)]))
        if signature != _MV_LV_VOLTAGE:
            continue
        downstream = downstream_map[f"transformer:{int(idx)}"]
        load_kw = (
            float(load_by_bus.reindex(list(downstream)).fillna(0.0).sum()) * 1000.0
        )
        candidates.append((load_kw, int(idx)))

    if not candidates:
        raise ValueError(
            "ev_hosting_flex feeder selection found no MV/LV (25/0.4 kV) "
            "distribution transformer in the net. Remediation: verify the topology "
            "cache was built from the expected radial twin, or set FEEDER_ID in "
            "config.py to the intended transformer index."
        )

    # Deterministic: largest downstream load, then smallest transformer index.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]

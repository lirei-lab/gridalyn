"""Opt-in, load-aware AC line conductor selection.

This module implements the ``lines.sizing.mode == "load_aware"`` post-pass for
the synthetic-network generator. It is intentionally a *post-pass* over a fully
built pandapower network (buses, lines, transformers, loads and ext_grid all
present): per-line downstream demand must be aggregated over the whole rooted
radial tree across transformer hops (the synthetic twin is multi-cluster
LV/MV/HV feeding one HV substation, not a single flat feeder), which is only
possible once transformers exist.

For each on-tree line the design current is

    ``I_design = S_down / (sqrt(3) * V_line_kv)``

where ``S_down`` is the *coincident* downstream demand (non-coincident subtree
load divided by the per-level diversity factor, mirroring the transformer
sizing convention) and ``V_line_kv`` is the line's ``from_bus`` nominal voltage.
The line is then snapped to the first pandapower standard line type of the
matching voltage family whose ``max_i_ka >= I_design * utilization_margin``; the
chosen catalog row's ``r/x/c/max_i_ka`` are copied verbatim onto the line so the
network stays physically consistent (impedances are never hand-invented).

The ``uniform`` default never calls into this module, guaranteeing byte-identity
with the historical generator output.

This module is *not* a package ``__init__``; a module-scope ``import pandapower``
is therefore allowed (matching ``builder.py``). pandapower must never be imported
at module scope from any package ``__init__``.
"""

from __future__ import annotations

import math
from typing import Any

import pandapower as pp

from gridalyn.simulation.analytics.line_sizing import (
    _build_bus_graph,
    _classify_level,
    _root_and_accumulate,
)

_DEFAULT_DIVERSITY = {"LV": 5.0, "MV": 1.3, "HV": 1.1}
_DEFAULT_UTILIZATION_MARGIN = 0.8
_SUMMARY_FLOAT_DECIMALS = 6


def select_line_std_type(
    net: Any,
    *,
    level: str,
    i_design_ka: float,
    utilization_margin: float,
) -> tuple[str, dict[str, float], bool]:
    """Snap a design current to a pandapower standard line type.

    The catalog is :func:`pandapower.available_std_types` filtered to the
    matching ``voltage_rating`` family and sorted ascending by
    ``(max_i_ka, std_type_name)`` so ties are deterministic regardless of
    catalog/dict ordering. The first entry whose ``max_i_ka`` is at least
    ``i_design_ka * utilization_margin`` is chosen. When the required current
    exceeds the largest entry, the largest is returned with ``over_capacity``
    set so the shortfall is surfaced rather than silently clipped (parallel
    feeders are out of scope).

    Args:
        net: A pandapower network (read only; used to read the std-type catalog).
        level: Voltage level family, ``"LV"`` / ``"MV"`` / ``"HV"``
            (case-insensitive).
        i_design_ka: Design current in kA.
        utilization_margin: Headroom factor in ``(0, 1]`` applied to the design
            current before snapping (e.g. ``0.8`` reserves 20% headroom).

    Returns:
        A tuple ``(std_type_name, catalog_row, over_capacity)`` where
        ``catalog_row`` is a mapping with ``max_i_ka``, ``r_ohm_per_km``,
        ``x_ohm_per_km`` and ``c_nf_per_km`` from the chosen entry.

    Raises:
        ValueError: When no catalog entry exists for ``level`` -- the message
            lists the available families to remediate.
    """
    family = level.upper()
    catalog = pp.available_std_types(net, element="line")
    subset = catalog[catalog["voltage_rating"] == family]
    if subset.empty:
        available = sorted(catalog["voltage_rating"].dropna().unique().tolist())
        raise ValueError(
            f"no '{family}' line catalog entry in pandapower available_std_types; "
            f"available voltage families: {available}"
        )

    # Deterministic order: (max_i_ka, std_type name). std_type name is the index.
    ordered = sorted(
        subset.iterrows(),
        key=lambda item: (float(item[1]["max_i_ka"]), str(item[0])),
    )
    threshold = i_design_ka * utilization_margin

    chosen_name: str | None = None
    chosen_row: Any = None
    for name, row in ordered:
        if float(row["max_i_ka"]) >= threshold:
            chosen_name, chosen_row = str(name), row
            break

    over_capacity = chosen_name is None
    if over_capacity:
        chosen_name, chosen_row = str(ordered[-1][0]), ordered[-1][1]

    catalog_row = {
        "max_i_ka": float(chosen_row["max_i_ka"]),
        "r_ohm_per_km": float(chosen_row["r_ohm_per_km"]),
        "x_ohm_per_km": float(chosen_row["x_ohm_per_km"]),
        "c_nf_per_km": float(chosen_row["c_nf_per_km"]),
    }
    return chosen_name, catalog_row, over_capacity


def _diversity_factors(config: dict[str, Any]) -> dict[str, float]:
    """Resolve per-level diversity factors from the config (with defaults).

    Args:
        config: Synthetic-network configuration mapping.

    Returns:
        Mapping from level name to diversity factor, mirroring the transformer
        sizing convention (``loads.diversity_factor_{lv,mv,hv}``).
    """
    loads = config.get("loads", {})
    return {
        "LV": float(loads.get("diversity_factor_lv", _DEFAULT_DIVERSITY["LV"])),
        "MV": float(loads.get("diversity_factor_mv", _DEFAULT_DIVERSITY["MV"])),
        "HV": float(loads.get("diversity_factor_hv", _DEFAULT_DIVERSITY["HV"])),
    }


def size_lines_load_aware(net: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Rewrite each on-tree line's conductor from its downstream coincident load.

    This is an **in-place** post-pass intended to run on the builder's network
    during generation, before any cache is written. For every line that lies on
    the radial tree rooted at the ext_grid bus it computes the coincident
    downstream demand, derives the design current, snaps to a pandapower
    standard line type via :func:`select_line_std_type`, and copies the chosen
    ``std_type`` plus ``max_i_ka`` / ``r_ohm_per_km`` / ``x_ohm_per_km`` /
    ``c_nf_per_km`` onto the line row. Lines not on the rooted tree keep their
    current values.

    Args:
        net: A pandapower network. Mutated in place (line table only).
        config: Synthetic-network configuration mapping. Reads
            ``loads.diversity_factor_{lv,mv,hv}`` and
            ``lines.sizing.utilization_margin`` (default ``0.8``).

    Returns:
        A per-line sizing summary list in ``net.line`` index order, one dict per
        on-tree line with keys ``idx``, ``level``, ``downstream_load_mw``,
        ``i_design_ka``, ``chosen_std_type``, ``max_i_ka`` and ``over_capacity``.
        Float fields are rounded to 6 decimals to stay below the 1e-6 regression
        noise floor.
    """
    diversity = _diversity_factors(config)
    utilization_margin = float(
        config.get("lines", {})
        .get("sizing", {})
        .get("utilization_margin", _DEFAULT_UTILIZATION_MARGIN)
    )

    load_by_bus: dict[int, float] = net.load.groupby("bus")["p_mw"].sum().to_dict()
    graph = _build_bus_graph(net)
    root = int(net.ext_grid["bus"].iloc[0])
    parent, subtree_load, _ = _root_and_accumulate(graph, root, load_by_bus)

    bus_vn = net.bus["vn_kv"].to_dict()
    summary: list[dict[str, Any]] = []
    for line_idx, row in net.line.iterrows():
        from_bus, to_bus = int(row["from_bus"]), int(row["to_bus"])
        if parent.get(to_bus) == from_bus:
            child = to_bus
        elif parent.get(from_bus) == to_bus:
            child = from_bus
        else:
            continue

        vn_kv = float(bus_vn[from_bus])
        level = _classify_level(vn_kv)
        s_noncoincident = float(subtree_load[child])
        s_down = s_noncoincident / diversity[level]
        i_design_ka = s_down / (math.sqrt(3.0) * vn_kv) if vn_kv > 0 else 0.0

        std_type, catalog_row, over_capacity = select_line_std_type(
            net,
            level=level,
            i_design_ka=i_design_ka,
            utilization_margin=utilization_margin,
        )

        net.line.at[line_idx, "std_type"] = std_type
        net.line.at[line_idx, "max_i_ka"] = catalog_row["max_i_ka"]
        net.line.at[line_idx, "r_ohm_per_km"] = catalog_row["r_ohm_per_km"]
        net.line.at[line_idx, "x_ohm_per_km"] = catalog_row["x_ohm_per_km"]
        net.line.at[line_idx, "c_nf_per_km"] = catalog_row["c_nf_per_km"]

        summary.append(
            {
                "idx": int(line_idx),
                "level": level,
                "downstream_load_mw": round(s_down, _SUMMARY_FLOAT_DECIMALS),
                "i_design_ka": round(i_design_ka, _SUMMARY_FLOAT_DECIMALS),
                "chosen_std_type": std_type,
                "max_i_ka": round(catalog_row["max_i_ka"], _SUMMARY_FLOAT_DECIMALS),
                "over_capacity": bool(over_capacity),
            }
        )
    return summary


__all__ = ["select_line_std_type", "size_lines_load_aware"]

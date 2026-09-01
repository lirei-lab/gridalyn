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

where ``S_down`` is the *full, non-coincident* downstream subtree demand — the
sum of the per-building loads the power flow actually injects — and
``V_line_kv`` is the line's ``from_bus`` nominal voltage. The line is then
snapped to the first pandapower standard line type of the matching voltage
family whose ``max_i_ka >= I_design / utilization_margin``; the chosen catalog
row's ``r/x/c/max_i_ka`` are copied verbatim onto the line so the network stays
physically consistent (impedances are never hand-invented).

**The utilization margin RESERVES HEADROOM.** ``utilization_margin`` (default
``0.8``) is the target ratio of design current to conductor rating, so the
required rating is ``I_design / utilization_margin`` (>= 1.25x design at 0.8): a
line carrying its design load then sits at <= 80% of its chosen ampacity. This
matches the transformer-sizing precedent in ``gridalyn/twin/core/graph.py``
(``required capacity = coincident_peak / capacity_utilization_factor``). An
earlier formula used ``I_design * utilization_margin``, which inverted the
margin — it snapped to a conductor *below* the design current and drove the
twin into thermal overload (LV max ~184%, MV ~135%, min bus voltage ~0.597 pu).
That inverted-margin formula is corrected here.

**Why full (non-coincident) load, not a diversified value.** The synthetic
generator assigns each building its FULL per-building load and the power flow
injects those loads in full (no coincidence/diversity reduction is applied at
simulation time). Sizing conductors for a diversity-reduced (coincident)
demand therefore undersizes every line by ~the diversity factor (~5x at LV) and
drives the simulated network into massive thermal overload (LV lines >400%, MV
>180%). This module SUPERSEDES the earlier "divide by the per-level
diversity_factor" approach: design current is matched to the load the power
flow imposes, so the regenerated twin is no longer overloaded.

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
    catalog/dict ordering. The first entry whose ``max_i_ka`` is at least the
    required rating ``i_design_ka / utilization_margin`` is chosen — the margin
    RESERVES HEADROOM (a line at design load sits at <= ``utilization_margin``
    of its chosen ampacity). When the required current exceeds the largest
    entry, the largest is returned with ``over_capacity`` set so the shortfall
    is surfaced rather than silently clipped (parallel feeders are out of
    scope).

    .. note::
        An earlier formula used ``i_design_ka * utilization_margin``, which
        inverted the margin (snapped *below* design current) and overloaded the
        twin. This is the corrected, headroom-reserving form.

    Args:
        net: A pandapower network (read only; used to read the std-type catalog).
        level: Voltage level family, ``"LV"`` / ``"MV"`` / ``"HV"``
            (case-insensitive).
        i_design_ka: Design current in kA.
        utilization_margin: Target design-current-to-rating ratio in ``(0, 1]``;
            the required rating is ``i_design_ka / utilization_margin`` (e.g.
            ``0.8`` reserves 20% headroom). Values ``<= 0`` are treated as
            no-margin (required rating == ``i_design_ka``).

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
            f"no {family!r} line catalog entry in pandapower available_std_types; "
            f"available voltage families: {available}"
        )

    # Deterministic order: (max_i_ka, std_type name). std_type name is the index.
    ordered = sorted(
        subset.iterrows(),
        key=lambda item: (float(item[1]["max_i_ka"]), str(item[0])),
    )
    # Margin reserves headroom: required rating >= i_design / margin (>= design).
    # margin <= 0 is treated as no-margin (required rating == i_design).
    threshold = (
        i_design_ka / utilization_margin if utilization_margin > 0 else i_design_ka
    )

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


def size_lines_load_aware(net: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Rewrite each on-tree line's conductor from its full downstream load.

    This is an **in-place** post-pass intended to run on the builder's network
    during generation, before any cache is written. For every line that lies on
    the radial tree rooted at the ext_grid bus it computes the FULL
    (non-coincident) downstream subtree demand — the load the power flow actually
    injects — derives the design current, snaps to a pandapower standard line
    type via :func:`select_line_std_type`, and copies the chosen ``std_type``
    plus ``max_i_ka`` / ``r_ohm_per_km`` / ``x_ohm_per_km`` / ``c_nf_per_km``
    onto the line row. Lines not on the rooted tree keep their current values.

    No diversity/coincidence reduction is applied: the generator assigns each
    building its full load and the power flow injects it in full, so sizing for
    a diversified demand would undersize conductors by ~the diversity factor and
    overload the simulated network.

    Args:
        net: A pandapower network. Mutated in place (line table only).
        config: Synthetic-network configuration mapping. Reads
            ``lines.sizing.utilization_margin`` (default ``0.8``). The margin
            reserves headroom: each line is snapped to a rating
            ``>= i_design / margin`` so it sits at <= ``margin`` of ampacity at
            design load (corrects an earlier inverted ``* margin`` formula).

    Returns:
        A per-line sizing summary list in ``net.line`` index order, one dict per
        on-tree line with keys ``idx``, ``level``, ``downstream_load_mw``,
        ``i_design_ka``, ``chosen_std_type``, ``max_i_ka`` and ``over_capacity``.
        ``downstream_load_mw`` is the FULL non-coincident subtree load. Float
        fields are rounded to 6 decimals to stay below the 1e-6 regression noise
        floor.
    """
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
        # Full (non-coincident) downstream load — what the power flow injects.
        s_noncoincident = float(subtree_load[child])
        i_design_ka = s_noncoincident / (math.sqrt(3.0) * vn_kv) if vn_kv > 0 else 0.0

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
                "downstream_load_mw": round(s_noncoincident, _SUMMARY_FLOAT_DECIMALS),
                "i_design_ka": round(i_design_ka, _SUMMARY_FLOAT_DECIMALS),
                "chosen_std_type": std_type,
                "max_i_ka": round(catalog_row["max_i_ka"], _SUMMARY_FLOAT_DECIMALS),
                "over_capacity": bool(over_capacity),
            }
        )
    return summary


__all__ = ["select_line_std_type", "size_lines_load_aware"]

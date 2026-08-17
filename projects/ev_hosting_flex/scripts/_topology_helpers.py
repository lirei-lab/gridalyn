"""Flagship-specific feeder-selection + annual-envelope topology helpers.

Plan 20-03 re-homed these out of the deleted ``_topology.py``: the generic
radial-feeder analytics (thermal ratings, downstream map, subtree sizing,
radiality assertion) now resolve from the SDK
``gridalyn.simulation.analytics.topology``; the helpers below are study-local
because they encode ev_hosting_flex's own calibration (``TARGET_HOMES``,
``FEEDER_ID``, the seasonal envelope constants) and have no SDK equivalent.

GUARD-02: operates ONLY on an already-loaded ``net`` object (attribute-bag of
pandas DataFrames). No ``import pandapower`` / ``geopandas`` / ``lightsim2grid``
at module scope; ``networkx`` and ``numpy`` are graph/numeric helpers.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import networkx as nx
import numpy as np

from projects.ev_hosting_flex.scripts.config import (
    CALENDAR_HOURS,
    CALENDAR_START_WEEKDAY,
    DAILY_PATTERN,
    FEEDER_ID,
    GRID_CONFIG,
    SUMMER_TROUGH_FACTOR,
    TARGET_HOMES,
    TRANSFORMER_UTILIZATION_MARGIN,
    WEEKLY_PATTERN,
    WINTER_PEAK_FACTOR,
)

# Annual-envelope factor arrays built ONCE for the inlined factor helpers below
# (Phase 15 RETIRE-02: severed from the retired annual-profiles module — the
# three deterministic, RNG-free factor functions are inlined here).
_DAILY = np.asarray(DAILY_PATTERN, dtype="float64")
_WEEKLY = np.asarray(WEEKLY_PATTERN, dtype="float64")
_HOURS_PER_DAY = 24  # CALENDAR_HOURS / 24 == 365 (non-leap).

# Re-pointing tolerance (D-03): the selected MV/LV transformer's downstream home
# count must land within this many homes of TARGET_HOMES, else the twin lacks a
# representative small LV unit and selection fails loudly (Pitfall 4).
_TARGET_HOMES_TOLERANCE = 2

# MV/LV distribution-transformer voltage signature (kV) used for feeder ranking.
# Derived from the project grid config (single source of truth) so a nominal-
# voltage change (e.g. the 2026-07-06 Québec 240 V secondary) cannot drift it.
_MV_LV_VOLTAGE = (
    float(GRID_CONFIG["buses"]["mv"]["voltage_kv"]),
    float(GRID_CONFIG["buses"]["lv"]["voltage_kv"]),
)


def _winter_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 seasonal multiplier per hour, winter-peaked.

    Inlined verbatim from the retired annual-profiles ``winter_factor`` (Phase 15
    RETIRE-02): a deterministic cosine over the year interpolating between
    ``SUMMER_TROUGH_FACTOR`` (mid-year) and ``WINTER_PEAK_FACTOR`` (year ends).
    RNG-free; byte-identical to the pre-severance envelope so
    ``annual_peak_base_factor`` (and the topology cache it sizes) is unchanged.

    Args:
        hour_of_year: Integer hour-of-year array (0 .. CALENDAR_HOURS-1).

    Returns:
        A float64 array of seasonal multipliers aligned to ``hour_of_year``.
    """
    day_of_year = np.asarray(hour_of_year, dtype="float64") // _HOURS_PER_DAY
    n_days = CALENDAR_HOURS // _HOURS_PER_DAY
    season = np.cos(2.0 * np.pi * day_of_year / float(n_days))
    midpoint = (WINTER_PEAK_FACTOR + SUMMER_TROUGH_FACTOR) / 2.0
    amplitude = (WINTER_PEAK_FACTOR - SUMMER_TROUGH_FACTOR) / 2.0
    return (midpoint + amplitude * season).astype("float64")


def _daily_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 daily-shape coefficient per hour.

    Inlined verbatim from the retired annual-profiles ``daily_factor`` (Phase 15
    RETIRE-02): indexes ``DAILY_PATTERN`` by ``hour_of_year % 24``. RNG-free.

    Args:
        hour_of_year: Integer hour-of-year array.

    Returns:
        A float64 array of daily-shape coefficients aligned to ``hour_of_year``.
    """
    hod = np.asarray(hour_of_year) % 24
    return _DAILY[hod]


def _weekly_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 weekly-shape coefficient per hour.

    Inlined verbatim from the retired annual-profiles ``weekly_factor`` (Phase 15
    RETIRE-02): weekday = ``((hour_of_year // 24) + CALENDAR_START_WEEKDAY) % 7``
    (Mon=0), indexing ``WEEKLY_PATTERN``. RNG-free.

    Args:
        hour_of_year: Integer hour-of-year array.

    Returns:
        A float64 array of weekly-shape coefficients aligned to ``hour_of_year``.
    """
    weekday = ((np.asarray(hour_of_year) // 24) + CALENDAR_START_WEEKDAY) % 7
    return _WEEKLY[weekday]


def annual_peak_base_factor() -> float:
    """Return the annual winter-peak base-envelope multiplier (float64).

    The maximum over the 8760h of ``winter(h) * daily(h) * weekly(h)`` — the
    multiplier that turns a per-bus nameplate sum into the annual winter-peak
    downstream base demand. Deterministic, no RNG (~1.76 for the pinned
    winter-peaked envelope).

    Returns:
        The float64 maximum hour-of-year envelope multiplier (``> 1.0``).
    """
    hours = np.arange(CALENDAR_HOURS)
    return float(
        np.max(_winter_factor(hours) * _daily_factor(hours) * _weekly_factor(hours))
    )


def size_feeder_transformer_kw(
    downstream_nameplate_kw: float,
    *,
    peak_factor: float,
    utilization_margin: float = TRANSFORMER_UTILIZATION_MARGIN,
) -> float:
    """Return the load-aware feeder-transformer kW rating, rounded UP.

    ``rating = ceil((downstream_nameplate_kw * peak_factor) / utilization_margin)``
    as float64. The annual winter-peak downstream base demand
    (``downstream_nameplate_kw * peak_factor``) divided by ``utilization_margin``
    reserves headroom so that at 0 EVs the binding feeder element sits at or below
    the margin (~80%, the D-08 calibration target). Rounds UP to the next whole
    kVA so the transformer is never undersized.

    Args:
        downstream_nameplate_kw: Per-bus nameplate-load sum of the feeder subtree
            in kW (the static nameplate, NOT the annual peak). Must be ``> 0``.
        peak_factor: The annual winter-peak envelope multiplier from
            :func:`annual_peak_base_factor` (``> 0``).
        utilization_margin: Headroom margin in ``(0, 1]`` (default
            ``TRANSFORMER_UTILIZATION_MARGIN``); the sized loading target at peak.

    Returns:
        The float64 feeder-transformer kW rating (rounded up to whole kVA).

    Raises:
        ValueError: If ``downstream_nameplate_kw <= 0`` or ``utilization_margin``
            is not in ``(0, 1]``.
    """
    if downstream_nameplate_kw <= 0.0:
        raise ValueError(
            "ev_hosting_flex feeder-transformer sizing received a non-positive "
            f"downstream_nameplate_kw ({downstream_nameplate_kw}); the feeder "
            "subtree must carry a positive nameplate load to be sized. "
            "Remediation: verify the selected feeder transformer's downstream "
            "buses carry load in node_nameplate_kw.json (re-run "
            "prepare_topology_cache.py if the cache is stale)."
        )
    if not 0.0 < utilization_margin <= 1.0:
        raise ValueError(
            "ev_hosting_flex feeder-transformer sizing received "
            f"utilization_margin={utilization_margin}, which is outside (0, 1]. "
            "Remediation: set TRANSFORMER_UTILIZATION_MARGIN in config.py to a "
            "headroom fraction in (0, 1] (the line precedent uses 0.8)."
        )
    required = (float(downstream_nameplate_kw) * float(peak_factor)) / float(
        utilization_margin
    )
    return float(math.ceil(required))


def _network_graph(net: Any) -> nx.Graph:
    """Build the undirected line+transformer connectivity graph (integer buses)."""
    graph = nx.Graph()
    graph.add_nodes_from(net.bus.index.tolist())
    for a, b in net.line[["from_bus", "to_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    for a, b in net.trafo[["hv_bus", "lv_bus"]].itertuples(index=False):
        graph.add_edge(int(a), int(b))
    return graph


def select_feeder(
    net: Any,
    downstream_map: Mapping[str, frozenset[int]],
    config: Mapping[str, Any] | None = None,
) -> int:
    """Deterministically select the study feeder's MV/LV transformer index.

    Honors a ``config["feeder_id"]`` (or module ``FEEDER_ID``) override; otherwise
    ranks the MV/LV (25→0.4 kV) distribution transformers by how close their
    downstream HOME count is to :data:`TARGET_HOMES` and picks the closest, with a
    deterministic ``(distance, idx)`` tie-break (Option C, D-01/D-03).

    This re-points the study from the Phase-9 max-downstream-load aggregated feeder
    to a representative small HQ residential LV transformer (~``TARGET_HOMES``
    homes). The ranking keys off the downstream home count (NOT a hardcoded index)
    so it stays robust to twin regeneration. After selection a runtime guard
    asserts the chosen transformer's home count is within
    ``_TARGET_HOMES_TOLERANCE`` of ``TARGET_HOMES`` — a twin lacking a small
    near-target LV unit trips HERE (Pitfall 4), not silently downstream.

    Args:
        net: Loaded pandapower-style net.
        downstream_map: Output of the SDK ``downstream_bus_map`` (or the former
            ``build_downstream_map``).
        config: Optional mapping; ``feeder_id`` (if not ``None``) overrides the
            ranking and is returned verbatim.

    Returns:
        The selected transformer integer index.

    Raises:
        ValueError: If no MV/LV (25/0.4 kV) transformer exists, or the closest
            candidate's downstream home count is farther than
            ``_TARGET_HOMES_TOLERANCE`` from ``TARGET_HOMES``.
    """
    override = config.get("feeder_id") if config else None
    if override is None:
        override = FEEDER_ID
    if override is not None:
        return int(override)

    # Per-bus building (home) count — the re-pointing ranks on this, not load.
    homes_by_bus = net.load.groupby("bus").size()
    vn = net.bus["vn_kv"]
    # candidate = (distance_to_target, idx, home_count)
    candidates: list[tuple[int, int, int]] = []
    for idx, row in net.trafo.iterrows():
        signature = (float(vn.loc[int(row.hv_bus)]), float(vn.loc[int(row.lv_bus)]))
        if signature != _MV_LV_VOLTAGE:
            continue
        downstream = downstream_map[f"transformer:{int(idx)}"]
        home_count = int(homes_by_bus.reindex(list(downstream)).fillna(0).sum())
        distance = abs(home_count - int(TARGET_HOMES))
        candidates.append((distance, int(idx), home_count))

    if not candidates:
        raise ValueError(
            "ev_hosting_flex feeder selection found no MV/LV "
            f"({_MV_LV_VOLTAGE[0]:g}/{_MV_LV_VOLTAGE[1]:g} kV) "
            "distribution transformer in the net. Remediation: verify the topology "
            "cache was built from the expected radial twin, or set FEEDER_ID in "
            "config.py to the intended transformer index."
        )

    # Deterministic: closest-to-TARGET_HOMES, then smallest transformer index.
    candidates.sort(key=lambda item: (item[0], item[1]))
    distance, selected_idx, home_count = candidates[0]

    if distance > _TARGET_HOMES_TOLERANCE:
        raise ValueError(
            "ev_hosting_flex feeder selection found no MV/LV "
            f"({_MV_LV_VOLTAGE[0]:g}/{_MV_LV_VOLTAGE[1]:g} kV) "
            f"transformer within {_TARGET_HOMES_TOLERANCE} homes of "
            f"TARGET_HOMES={int(TARGET_HOMES)}: the closest is transformer "
            f"{selected_idx} with {home_count} downstream home(s) (distance "
            f"{distance}). The re-calibration requires a representative small LV "
            "transformer (~6 homes) as the unit of congestion (D-01/D-03). "
            "Remediation: add a small-transformer sizing knob to "
            "inputs/synthetic_network_config.json (or set FEEDER_ID in config.py to "
            "a chosen near-target candidate) before re-running "
            "prepare_topology_cache.py --force-rebuild."
        )
    return selected_idx

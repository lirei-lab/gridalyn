"""Feeder geometry every stage needs, in one place instead of eleven.

``size_network_to_load`` lived in ``pipeline/validate_powerflow.py`` and was
imported by ten other stages -- it was the only thing they took from that
module, so a stage was serving as a library and the import graph disagreed with
the declared DAG (bd qgr.5). Eleven stages also repeated the same preamble
before calling it: unpickle the net, read the feeder index, load the TMY,
find the design day. This module is the home for both.

Nothing here reads a report or writes an artifact; it is geometry derived from
the topology cache and the pinned TMY, which is why every stage can share it.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    day_mean_temps,
    design_day_base_per_home,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import standard_kva_for_load
from projects.ev_hosting_flex.scripts.config import (
    DTYPE,
    LV_LINE_UTIL_TARGET,
    LV_LINE_VDROP_BUDGET_PU,
    POWER_FACTOR,
    ROUND_DECIMALS,
    SEED,
    SUBSTATION_EMERGENCY_FACTOR,
    SUBSTATION_MVA_LADDER,
    SUBSTATION_N1_CONTINGENCY_TARGET,
    SUBSTATION_N_TRANSFORMERS,
    TRANSFORMER_KVA,
)

# ``config.py`` reads its values out of ``project.yaml`` and so types them all
# as ``object``; every consumer then pays for it at each use site. Binding them
# once here, with the type the study declares, keeps the uses readable and adds
# nothing at run time -- ``cast`` is erased. SUBSTATION_MVA_LADDER stays as
# imported because it is iterated, not arithmetic.
_DTYPE: type = cast(type, DTYPE)
_ROUND_DECIMALS: int = cast(int, ROUND_DECIMALS)
_SUBSTATION_N_TRANSFORMERS: int = cast(int, SUBSTATION_N_TRANSFORMERS)
_SUBSTATION_N1_CONTINGENCY_TARGET: float = cast(float, SUBSTATION_N1_CONTINGENCY_TARGET)
_SUBSTATION_EMERGENCY_FACTOR: float = cast(float, SUBSTATION_EMERGENCY_FACTOR)
_POWER_FACTOR: float = cast(float, POWER_FACTOR)
_TRANSFORMER_KVA: float = cast(float, TRANSFORMER_KVA)
_LV_LINE_UTIL_TARGET: float = cast(float, LV_LINE_UTIL_TARGET)
_LV_LINE_VDROP_BUDGET_PU: float = cast(float, LV_LINE_VDROP_BUDGET_PU)
_SEED: int = cast(int, SEED)


def configure_substation_n1(
    net: Any,
    homes_by_bus: Any,
    base_by_size: dict[int, np.ndarray],
    size_by_loadbus: dict[int, int],
    pf: float,
) -> dict[str, Any]:
    """Reconfigure the substation into an HQ-realistic N-1 transformer bank.

    Ties the existing substation transformers' MV (25 kV) buses onto a common
    bus (a near-zero-impedance coupler — the normal closed-tie operating state),
    adds transformers until the bank has ``_SUBSTATION_N_TRANSFORMERS`` units, and
    sizes every unit to the smallest ``SUBSTATION_MVA_LADDER`` rung whose usable
    MW ``× (N−1) × _SUBSTATION_N1_CONTINGENCY_TARGET`` covers the total area
    design-cold load — so on a single-unit contingency the ``N−1`` remaining
    units carry the full load at ≈ the N-1 contingency-loading target (~120 %,
    well within the ``_SUBSTATION_EMERGENCY_FACTOR`` capability). For N = 2 that is
    the standard HQ two-identical-parallel-unit redundant substation. Diversity
    is ~0 at design cold, so the area load is the hourly max of the summed
    per-home base of every home. Mutates the net in place.

    Returns:
        Dict with the per-unit MVA, unit count, total area load, and the N-1 firm
        capacity at the normal and emergency ratings (MW).
    """
    import pandapower as pp

    # Total area design-cold load (coincident; MV diversity ~0 at design cold).
    day_profile = np.zeros(24, dtype=_DTYPE)
    for bus, size in size_by_loadbus.items():
        day_profile = day_profile + int(homes_by_bus.loc[bus]) * base_by_size[size]
    total_load_mw = float(day_profile.max()) / 1000.0
    total_load_mva = total_load_mw / float(pf)

    n = int(_SUBSTATION_N_TRANSFORMERS)
    per_unit_min_mva = total_load_mva / (
        max(n - 1, 1) * float(_SUBSTATION_N1_CONTINGENCY_TARGET)
    )
    mva = next(
        (m for m in SUBSTATION_MVA_LADDER if m >= per_unit_min_mva),
        SUBSTATION_MVA_LADDER[-1],
    )

    sub_idx = list(net.trafo.index[net.trafo["vn_lv_kv"] >= 1.0])
    mv_buses = [int(net.trafo.at[i, "lv_bus"]) for i in sub_idx]
    # Tie the MV LV-side buses onto a common node with closed bus-bus switches
    # (the normal closed-tie operating state) — a zero-impedance fuse, unlike a
    # near-zero line which ill-conditions the power flow.
    for other in mv_buses[1:]:
        pp.create_switch(net, bus=mv_buses[0], element=other, et="b", closed=True)
    # Add transformers (copied from the first) until the bank has N units.
    template = net.trafo.loc[sub_idx[0]]
    while len(sub_idx) < n:
        new_idx = pp.create_transformer_from_parameters(
            net,
            hv_bus=int(template.hv_bus),
            lv_bus=mv_buses[0],
            sn_mva=mva,
            vn_hv_kv=float(template.vn_hv_kv),
            vn_lv_kv=float(template.vn_lv_kv),
            vk_percent=float(template.vk_percent),
            vkr_percent=float(template.vkr_percent),
            pfe_kw=float(template.pfe_kw),
            i0_percent=float(template.i0_percent),
            shift_degree=float(template.shift_degree),
        )
        sub_idx.append(int(new_idx))
    for i in sub_idx:
        net.trafo.at[i, "sn_mva"] = mva
    # The synthetic template carries a tap-dependency flag with no lookup table;
    # the parallel N-1 bank uses fixed taps, so disable it to keep runpp clean.
    if "tap_dependency_table" in net.trafo.columns:
        net.trafo["tap_dependency_table"] = False

    usable_mw = mva * float(pf)
    return {
        "n_transformers": n,
        "mva_per_transformer": float(mva),
        "total_area_load_mw": round(total_load_mw, _ROUND_DECIMALS),
        "normal_loading_percent": round(
            total_load_mw / (n * usable_mw) * 100.0, _ROUND_DECIMALS
        ),
        "firm_capacity_normal_mw": round((n - 1) * usable_mw, _ROUND_DECIMALS),
        "firm_capacity_emergency_mw": round(
            (n - 1) * usable_mw * float(_SUBSTATION_EMERGENCY_FACTOR), _ROUND_DECIMALS
        ),
    }


def size_network_to_load(
    net: Any,
    script: ProjectScript,
    temp_hourly: Any,
    design_day_idx: int,
    feeder_idx: int,
) -> dict[str, Any]:
    """Size the LV transformers AND secondary conductors to their design load.

    HQ-style sizing (2026-07-07): each LV transformer's downstream homes carry
    the SDK per-home design-cold base of THEIR cluster's home count; the
    transformer takes the smallest standard kVA covering that aggregate load,
    and each LV line is upsized so its design-cold current sits at
    ``_LV_LINE_UTIL_TARGET`` of the (re-sized) conductor ampacity — a thicker
    conductor raises ampacity AND lowers impedance, recovering both the thermal
    margin and the LV voltage (the network verification found the SDK
    load_aware LV lines undersized for the winter peak). Mutates
    ``net.trafo.sn_mva`` and the LV ``net.line`` impedance/ampacity in place
    (physical AC). The GOVERNED study feeder transformer is pinned at
    ``_TRANSFORMER_KVA``.

    Args:
        net: Loaded pandapower net (mutated in place).
        script: The project workspace handle (cache JSON reads).
        temp_hourly: Committed annual TMY series.
        design_day_idx: Day-of-year index of the coldest design day.
        feeder_idx: Study feeder transformer index (kept at _TRANSFORMER_KVA).

    Returns:
        Dict with the per-home design-day base per size, the size→bus map, the
        assigned kVA per size, and the LV-line upsizing count.
    """
    downstream_map = script.read_json("outputs/cache/downstream_bus_map.json")
    homes_by_bus = net.load.groupby("bus").size()
    lv_trafos = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]

    size_by_trafo: dict[int, int] = {}
    size_by_loadbus: dict[int, int] = {}
    for idx in lv_trafos:
        downstream = [int(b) for b in downstream_map.get(f"transformer:{int(idx)}", [])]
        n = int(homes_by_bus.reindex(downstream).fillna(0).sum())
        size_by_trafo[int(idx)] = n
        for bus in downstream:
            if bus in homes_by_bus.index:
                size_by_loadbus[bus] = n

    sizes = sorted({n for n in size_by_trafo.values() if n > 0})
    base_by_size = {
        n: design_day_base_per_home(temp_hourly, n, _SEED, design_day_idx)
        for n in sizes
    }
    kva_by_size = {
        n: standard_kva_for_load(float(n) * float(base_by_size[n].max())) for n in sizes
    }
    for idx in lv_trafos:
        n = size_by_trafo[int(idx)]
        if int(idx) == int(feeder_idx) or n == 0:
            kva = float(_TRANSFORMER_KVA)
        else:
            kva = kva_by_size[n]
        net.trafo.at[idx, "sn_mva"] = kva / 1000.0

    # ── LV secondary conductors sized to design-cold current + voltage drop ─
    # Each LV line's design current follows from the homes downstream of it
    # (all on one transformer -> one cluster size). Real LV design sizes for
    # BOTH thermal ampacity AND voltage drop; the binding scale is the max.
    # A thicker conductor (scale s) raises ampacity xs and lowers impedance /s,
    # so both the thermal margin and the per-line voltage drop improve by s.
    pf = float(_POWER_FACTOR)
    sinphi = float(np.sqrt(1.0 - pf * pf))
    n_lines_upsized = 0
    vn_by_bus = net.bus["vn_kv"]
    for line_idx in net.line.index:
        from_bus = int(net.line.at[line_idx, "from_bus"])
        if float(vn_by_bus.loc[from_bus]) >= 1.0:  # LV lines only
            continue
        downstream = downstream_map.get(f"line:{int(line_idx)}", [])
        down_buses = [int(b) for b in downstream if int(b) in homes_by_bus.index]
        if not down_buses:
            continue
        n_down_homes = int(homes_by_bus.reindex(down_buses).fillna(0).sum())
        cluster_size = size_by_loadbus[down_buses[0]]
        per_home_peak = float(base_by_size[cluster_size].max())
        design_load_mw = n_down_homes * per_home_peak / 1000.0
        vn_kv = float(vn_by_bus.loc[from_bus])
        design_i_ka = design_load_mw / (np.sqrt(3.0) * vn_kv * pf)
        r = float(net.line.at[line_idx, "r_ohm_per_km"])
        x = float(net.line.at[line_idx, "x_ohm_per_km"])
        length_km = float(net.line.at[line_idx, "length_km"])
        current_i_ka = float(net.line.at[line_idx, "max_i_ka"])
        thermal_scale = design_i_ka / (float(_LV_LINE_UTIL_TARGET) * current_i_ka)
        vdrop_pu = (
            np.sqrt(3.0) * design_i_ka * (r * pf + x * sinphi) * length_km / vn_kv
        )
        voltage_scale = vdrop_pu / float(_LV_LINE_VDROP_BUDGET_PU)
        scale = max(1.0, thermal_scale, voltage_scale)
        if scale > 1.0:
            net.line.at[line_idx, "max_i_ka"] = current_i_ka * scale
            net.line.at[line_idx, "r_ohm_per_km"] = r / scale
            net.line.at[line_idx, "x_ohm_per_km"] = x / scale
            n_lines_upsized += 1

    substation = configure_substation_n1(
        net, homes_by_bus, base_by_size, size_by_loadbus, pf
    )

    return {
        "base_by_size": base_by_size,
        "size_by_loadbus": size_by_loadbus,
        "kva_by_size": kva_by_size,
        "size_by_trafo": size_by_trafo,
        "n_lv_lines_upsized": n_lines_upsized,
        "substation": substation,
    }


@dataclass(frozen=True)
class SizedFeeder:
    """The sized network and the weather window every consuming stage derives.

    Attributes:
        net: The pandapower net, sized in place by ``size_network_to_load``.
        feeder_idx: Index of the study's governed feeder transformer.
        temp: The annual TMY temperature series.
        hod0: Hour-of-day of the series' first sample.
        tday: Per-day mean temperatures.
        design_day: Index of the coldest day, the sizing basis.
        sizing: The full ``size_network_to_load`` result.
    """

    net: Any
    feeder_idx: int
    temp: Any
    hod0: int
    tday: Any
    design_day: int
    sizing: dict[str, Any]

    @property
    def size_by_trafo(self) -> dict[int, int]:
        """Return homes served, per transformer index."""
        return self.sizing["size_by_trafo"]

    @property
    def lv_transformers(self) -> Any:
        """Return the index of LV (secondary < 1 kV) transformers."""
        return self.net.trafo.index[self.net.trafo["vn_lv_kv"] < 1.0]

    @property
    def homes_by_trafo(self) -> dict[int, int]:
        """Return homes served by each LV transformer."""
        return {int(t): int(self.size_by_trafo[int(t)]) for t in self.lv_transformers}

    @property
    def rating_by_trafo(self) -> dict[int, float]:
        """Return each LV transformer's kW rating at the study power factor."""
        pf = float(_POWER_FACTOR)
        return {
            int(t): float(self.net.trafo.at[int(t), "sn_mva"]) * 1000.0 * pf
            for t in self.lv_transformers
        }

    @property
    def sizes(self) -> list[int]:
        """Return the distinct home counts across the LV fleet."""
        return sorted(set(self.homes_by_trafo.values()))

    def rating_by_size(self) -> dict[int, float]:
        """Return one kW rating per home count.

        Raises:
            ValueError: If transformers with the same home count carry
                different ratings, which the per-size mappings assume they do
                not.
        """
        homes = self.homes_by_trafo
        ratings = self.rating_by_trafo
        out: dict[int, float] = {}
        for size in self.sizes:
            group = {ratings[t] for t in homes if homes[t] == size}
            if len(group) != 1:
                raise ValueError(
                    f"transformers with {size} homes have non-uniform ratings "
                    f"{group}; the per-size congestion mapping assumes one "
                    "rating per size."
                )
            out[size] = group.pop()
        return out


def load_sized_feeder(script: ProjectScript) -> SizedFeeder:
    """Return the sized net and weather window, as eleven stages derive it.

    The preamble each of them repeated verbatim: unpickle the cached net, read
    the governed feeder's index, load the pinned TMY, take the coldest day as
    the sizing basis, and size the network to it.

    Args:
        script: The project workspace handle.

    Returns:
        The :class:`SizedFeeder`. ``net`` is sized in place, so callers that
        mutate it further see their own changes and no one else's.
    """
    with open(script.cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        script.read_json("outputs/cache/feeder_selection.json")[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    tday = day_mean_temps(temp)
    design_day = int(np.argmin(tday))
    return SizedFeeder(
        net=net,
        feeder_idx=feeder_idx,
        temp=temp,
        hod0=int(tmy_hour_of_day(temp)),
        tday=tday,
        design_day=design_day,
        sizing=size_network_to_load(net, script, temp, design_day, feeder_idx),
    )

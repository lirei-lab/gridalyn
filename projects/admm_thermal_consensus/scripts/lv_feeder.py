"""Synthetic LV residential feeder with a real MV/LV distribution transformer.

Eighty literal all-electric homes hang off one radial low-voltage feeder fed by a
single MV/LV transformer. The home aggregate (kW) is injected directly at the LV
load buses --- there is no artificial scale factor --- and the transformer thermal
loading is the binding constraint, the classic residential winter-peak limit.

Both ``build_network`` and ``validate_powerflow`` build the feeder through these
helpers so the topology is identical everywhere.
"""

from __future__ import annotations

import math

import numpy as np

from projects.admm_thermal_consensus.scripts import config as C


def home_counts() -> list[int]:
    """Distribute N_AGENTS homes across the LV load buses as evenly as possible."""
    base = C.N_AGENTS // C.N_LV_SECTIONS
    rem = C.N_AGENTS % C.N_LV_SECTIONS
    return [base + (1 if i < rem else 0) for i in range(C.N_LV_SECTIONS)]


def bus_fractions() -> list[float]:
    """Per-load-bus share of the total home population (sums to 1)."""
    counts = home_counts()
    total = float(sum(counts))
    return [c / total for c in counts]


def build_lv_feeder():
    """Build the LV residential feeder and return ``(net, load_bus_indices)``."""
    import pandapower as pp

    net = pp.create_empty_network(name="lv_residential")
    mv = pp.create_bus(net, vn_kv=C.MV_KV, name="MV")
    pp.create_ext_grid(net, mv, vm_pu=1.0, name="grid")
    lv = pp.create_bus(net, vn_kv=C.LV_KV, name="LV_busbar")
    pp.create_transformer_from_parameters(
        net,
        hv_bus=mv,
        lv_bus=lv,
        sn_mva=C.TRANSFORMER_KVA / 1000.0,
        vn_hv_kv=C.MV_KV,
        vn_lv_kv=C.LV_KV,
        vkr_percent=1.0,
        vk_percent=4.0,
        pfe_kw=0.6,
        i0_percent=0.2,
        name="MV/LV distribution transformer",
    )
    # several parallel radial feeders leave the LV busbar (a real 400 kVA unit
    # has multiple LV ways) so no single cable carries the whole transformer load
    load_buses = []
    seg = 0
    for f in range(C.N_LV_FEEDERS):
        chain = [lv]
        for _ in range(C.BUSES_PER_FEEDER):
            b = pp.create_bus(net, vn_kv=C.LV_KV, name=f"LV_f{f}_{len(chain)}")
            pp.create_line_from_parameters(
                net,
                from_bus=chain[-1],
                to_bus=b,
                length_km=C.LV_SECTION_KM,
                r_ohm_per_km=C.LV_R_OHM_KM,
                x_ohm_per_km=C.LV_X_OHM_KM,
                c_nf_per_km=0.0,
                max_i_ka=C.LV_MAX_I_KA,
                name=f"LV_seg_{seg}",
            )
            chain.append(b)
            load_buses.append(b)
            seg += 1
    for i, b in enumerate(load_buses):
        pp.create_load(net, bus=b, p_mw=0.0, q_mvar=0.0, name=f"cluster_{i}")
    return net, load_buses


def inject_total(net, load_buses, total_kw: float) -> None:
    """Spread an aggregate home demand (kW) across LV load buses by population."""
    tan_phi = math.tan(math.acos(C.POWER_FACTOR))
    fracs = bus_fractions()
    for i, b in enumerate(load_buses):
        p_mw = total_kw * fracs[i] / 1000.0
        mask = net.load.bus == b
        net.load.loc[mask, "p_mw"] = p_mw
        net.load.loc[mask, "q_mvar"] = p_mw * tan_phi


def solve_metrics(net) -> tuple[float, float]:
    """Run AC power flow; return ``(min_lv_voltage_pu, max_transformer_loading_pct)``.

    Solves through the registered pandapower-native backend rather than calling
    ``runpp`` here, so the engine reaches ``provenance.powerflow_backend``. That
    backend's declared settings are ``algorithm="nr", init="auto"`` -- exactly
    the keywords this site used to pass -- so no solved value moves.
    """
    from gridalyn.simulation.backends.contract import PANDAPOWER_NATIVE_BACKEND_ID
    from gridalyn.simulation.backends.registry import resolve_powerflow_backend

    resolve_powerflow_backend(PANDAPOWER_NATIVE_BACKEND_ID).solve(net)
    lv_mask = net.bus.vn_kv < 1.0
    vmin = float(net.res_bus.vm_pu[lv_mask].min())
    loading = float(net.res_trafo.loading_percent.max())
    return vmin, loading


def build_peak_curve(n_points: int, peak_lo_kw: float, peak_hi_kw: float):
    """Precompute (peak_kw -> min LV voltage, transformer loading) over a grid.

    Worst-of-day transformer loading is a monotone function of the daily peak
    (the transformer sees the whole aggregate regardless of spatial placement),
    so a handful of solves suffice; the curve is interpolated for the Monte-Carlo
    and method-comparison stages.
    """
    net, load_buses = build_lv_feeder()
    peaks = np.linspace(peak_lo_kw, peak_hi_kw, n_points)
    vmins = np.zeros_like(peaks)
    loadings = np.zeros_like(peaks)
    for k, pk in enumerate(peaks):
        inject_total(net, load_buses, float(pk))
        vmins[k], loadings[k] = solve_metrics(net)
    return peaks, vmins, loadings

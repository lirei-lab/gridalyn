"""Local (NON-governed) calibration probe for the realistic residential base.

Sweeps R_STUDY_B / DHW_ELEMENT_KW / DHW_DAILY_L_MEAN / BG_SCALE on the governed
6-home feeder and reports peak, energy, and the heat/DHW/bg split vs the targets:
coincident cold-day 15-min peak (p99 daily-peak) 11-12 kW, annual energy
25-30 MWh, split ~60/15/25 %, evening/morning diurnal peaks. NOT part of the
pipeline; run by hand to fix the final config knobs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from projects.ev_hosting_flex.scripts import config as cfg  # noqa: E402
from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    dhw_tank_annual,
    load_annual_tmy,
)

RES = cfg.ANNUAL_RES_MINUTES
SPD = 24 * 60 // RES
KWH = RES / 60.0
NH = 6


def evaluate(R: float, element: float, daily: float, bg_scale: float) -> dict:
    """Peak/energy/split for one knob set on the 6-home feeder."""
    cfg.DHW_ELEMENT_KW = element
    cfg.DHW_DAILY_L_MEAN = daily
    from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings

    temp = load_annual_tmy()
    b = make_buildings(NH, seed=cfg.SEED)
    for x in b:
        x.R = R
        x.p_heat_max = cfg.P_HEAT_QUEBEC
    r = simulate_buildings(
        b, temp.resample("1min").interpolate(), burnin_hours=6, random_seed=cfg.SEED
    )
    heat = sum(r[u]["p_heat_kw"] for u in r).resample(f"{RES}min").mean().to_numpy()
    cool = sum(r[u]["p_cool_kw"] for u in r).resample(f"{RES}min").mean().to_numpy()
    bg = (
        bg_scale * sum(r[u]["p_bg_kw"] for u in r)
    ).resample(f"{RES}min").mean().to_numpy()
    n = 365 * SPD
    heat = np.pad(heat, (0, max(0, n - len(heat))), "edge")[:n]
    cool = np.pad(cool, (0, max(0, n - len(cool))), "edge")[:n]
    bg = np.pad(bg, (0, max(0, n - len(bg))), "edge")[:n]
    dhw = dhw_tank_annual(
        np.random.default_rng(cfg.SEED + cfg.DHW_SEED_SALT), NH, temp, res_minutes=RES
    )
    dhw = np.pad(dhw, (0, max(0, n - len(dhw))), "edge")[:n]
    ph = (heat + cool + bg + dhw) / NH
    dpk = ph.reshape(365, SPD).max(axis=1)
    return {
        "MWh": ph.sum() * KWH / 1000,
        "peak": float(ph.max()),
        "p99": float(np.percentile(dpk, 99)),
        "split": (
            heat.sum() * KWH / 1000 / NH,
            dhw.sum() * KWH / 1000 / NH,
            bg.sum() * KWH / 1000 / NH,
        ),
    }


def main() -> None:
    """Sweep the knobs and print the target table."""
    print("Targets: energy 25-30 MWh, p99 daily-peak 11-12 kW, split ~60/15/25 %")
    grid = [
        (7.5, 4.5, 180, 0.6),
        (8.0, 4.5, 180, 0.6),
        (8.0, 4.5, 160, 0.55),
        (8.5, 4.5, 170, 0.55),
        (8.0, 4.0, 160, 0.6),
    ]
    for R, el, d, bg in grid:
        m = evaluate(R, el, d, bg)
        s = m["split"]
        print(
            f"R{R} el{el} d{d} bg{bg}: {m['MWh']:.1f} MWh  peak {m['peak']:.1f}  "
            f"p99 {m['p99']:.1f}  split {s[0]:.0f}/{s[1]:.0f}/{s[2]:.0f}"
        )


if __name__ == "__main__":
    main()

"""Diagnostic: decompose the SDK building load (heating vs background) and show
the hourly feeder shape — is per-home load too low, and where's the peak?

Not a pytest test (no ``test_*`` functions) -- a standalone diagnostic script
that imports ``projects.ev_hosting_flex.scripts.config``, so it must run as a
module from the repo root, not as a bare file:

    uv run python -m tests.diagnose_feeder_load_decomposition
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
from gridalyn.assets.datagen.data.weather import select_peak_load_day
from projects.ev_hosting_flex.scripts.config import (
    SEED,
    TMY_INPUT_PATH,
    TRANSFORMER_KVA,
)

PF = 0.95
RATING_KW = TRANSFORMER_KVA * PF
N_HOMES = 7
K = 20


def load_tmy() -> pd.DataFrame:
    df = pd.read_csv(TMY_INPUT_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp")


def main() -> None:
    cold = select_peak_load_day(load_tmy())
    idx = cold.index
    heat_h = np.zeros((K, 24))
    bg_h = np.zeros((K, 24))
    tot_h = np.zeros((K, 24))
    heat_peak = []
    bg_peak = []
    tot_peak = []
    for r in range(K):
        blds = make_buildings(N_HOMES, seed=SEED + r)
        res = simulate_buildings(
            blds, cold["temp_air"], burnin_hours=6, random_seed=SEED + r
        )
        ph = np.zeros(len(idx))
        pb = np.zeros(len(idx))
        pt = np.zeros(len(idx))
        for uid in res:
            ph += res[uid]["p_heat_kw"].to_numpy(float)
            pb += res[uid]["p_bg_kw"].to_numpy(float)
            pt += res[uid]["p_total_kw"].to_numpy(float)
        # per-home peaks (feeder peak / N for a coincident read)
        heat_peak.append(ph.max() / N_HOMES)
        bg_peak.append(pb.max() / N_HOMES)
        tot_peak.append(pt.max() / N_HOMES)
        heat_h[r] = pd.Series(ph, index=idx).resample("1h").mean().to_numpy()[:24]
        bg_h[r] = pd.Series(pb, index=idx).resample("1h").mean().to_numpy()[:24]
        tot_h[r] = pd.Series(pt, index=idx).resample("1h").mean().to_numpy()[:24]
    hours = (
        pd.Series(np.zeros(len(idx)), index=idx).resample("1h").mean().index.hour[:24]
    )

    print(f"rating={RATING_KW:.1f} kW, {N_HOMES} homes, K={K}\n")
    print("PER-HOME COINCIDENT PEAK (feeder peak / N_homes):")
    print(f"  heating : {np.mean(heat_peak):.2f} kW/home")
    print(f"  background: {np.mean(bg_peak):.2f} kW/home")
    print(f"  TOTAL   : {np.mean(tot_peak):.2f} kW/home   (Quebec target 10-15)\n")
    tot_mean = tot_h.mean(axis=0)
    heat_mean = heat_h.mean(axis=0)
    bg_mean = bg_h.mean(axis=0)
    peak_hour = int(hours[np.argmax(tot_mean)])
    peak_kw = tot_mean.max()
    peak_pct = peak_kw / RATING_KW * 100
    print(
        f"feeder peak hour = {peak_hour}:00  (peak {peak_kw:.1f} kW = {peak_pct:.0f}% rating)\n"
    )
    print("hour |  heat   bg   total  (kW, feeder, mean over K)")
    for h in range(24):
        bar = "#" * int(tot_mean[h] / 2)
        print(
            f" {hours[h]:2d}  | {heat_mean[h]:5.1f} {bg_mean[h]:4.1f} {tot_mean[h]:6.1f}  {bar}"
        )


if __name__ == "__main__":
    main()

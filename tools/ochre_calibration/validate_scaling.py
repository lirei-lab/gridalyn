"""Validate that a simulated fleet scales to feeder size without collapsing.

The failure this guards against is not one implausible dwelling. It is a fleet
whose members are too alike: replicate 23 dwellings across a 3,000-home feeder
and every copy peaks in the same quarter hour, so the feeder behaves like one
enormous house and the aggregate scales linearly with no smoothing at all.

Four checks, each answering a distinct question:

``coincidence``
    Coincidence factor ``peak(sum) / sum(peaks)`` against pool size. The
    literature the study already cites (LBNL/Hong via CALIBRATION.md) puts
    resistance-heating districts near **0.85**; a fleet reporting far below
    that is more diverse than the physics, and one reporting ~1.0 has no
    diversity at all.

``convergence``
    Whether the curve has flattened by the pool's own size. If per-home peak is
    still falling at the last point, the pool is too small to state a limit and
    any feeder built from it inherits an unconverged number.

``replication``
    What happens when the pool is resampled *with replacement* up to feeder
    size. Identical copies add no smoothing, so this measures the ceiling that
    replication imposes -- and compares it against resampling with a per-copy
    time jitter, which is what a defensible scale-up has to do instead.

``feeder``
    The implied feeder peak for a stated dwelling count, next to the aggregate
    the study considers plausible. This is where a 3x per-dwelling error stops
    being academic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KWH_PER_INTERVAL_TO_KW = 4.0  # 15-minute intervals


def load_totals(results: Path) -> pd.DataFrame:
    """Return a (timestep x dwelling) frame of total electric power in kW."""
    payload = json.loads(results.read_text(encoding="utf-8"))
    minutes = int(payload["resolution_minutes"])
    columns: dict[str, pd.Series] = {}
    for record in payload["dwellings"]:
        if record["status"] != "ok":
            continue
        frame = pd.read_csv(record["timeseries"], low_memory=False).iloc[1:]
        index = pd.to_datetime(frame[frame.columns[0]])
        wanted = [
            c
            for c in frame.columns
            if c.startswith("End Use: Electricity:") and "Fans/Pumps" not in c
        ]
        values = frame[wanted].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        series = values.sum(axis=1) / (minutes / 60.0)
        series.index = index
        columns[Path(record["archetype"]).stem] = series
    return pd.DataFrame(columns)


def coincidence(
    totals: pd.DataFrame, sizes: list[int], draws: int, seed: int
) -> list[dict]:
    """Return coincidence factor and per-home peak against pool size."""
    rng = np.random.default_rng(seed)
    matrix = totals.to_numpy()
    peaks = matrix.max(axis=0)
    rows = []
    for size in sizes:
        if size > matrix.shape[1]:
            continue
        cfs, per_home = [], []
        for _ in range(draws):
            pick = rng.choice(matrix.shape[1], size=size, replace=False)
            pooled = matrix[:, pick].sum(axis=1)
            cfs.append(pooled.max() / peaks[pick].sum())
            per_home.append(pooled.max() / size)
        rows.append(
            {
                "homes": size,
                "coincidence_factor": round(float(np.median(cfs)), 4),
                "peak_kw_per_home": round(float(np.median(per_home)), 3),
            }
        )
    return rows


def replicate(
    totals: pd.DataFrame, homes: int, seed: int, jitter_steps: int
) -> dict[str, float]:
    """Resample the pool with replacement up to ``homes`` and report the peak.

    ``jitter_steps`` rolls each drawn copy by a random number of timesteps.
    Zero jitter is the naive scale-up: every copy of a dwelling peaks in the
    same interval as its original.
    """
    rng = np.random.default_rng(seed)
    matrix = totals.to_numpy()
    steps, pool = matrix.shape
    pick = rng.integers(0, pool, size=homes)
    if jitter_steps <= 0:
        pooled = matrix[:, pick].sum(axis=1)
    else:
        shifts = rng.integers(-jitter_steps, jitter_steps + 1, size=homes)
        pooled = np.zeros(steps)
        for column, shift in zip(pick, shifts, strict=True):
            pooled += np.roll(matrix[:, column], shift)
    peaks = matrix.max(axis=0)[pick]
    return {
        "homes": homes,
        "jitter_steps": jitter_steps,
        "feeder_peak_mw": round(float(pooled.max()) / 1000.0, 3),
        "peak_kw_per_home": round(float(pooled.max()) / homes, 3),
        "coincidence_factor": round(float(pooled.max() / peaks.sum()), 4),
    }


def main(argv: list[str] | None = None) -> int:
    """Run every scaling check and print a single JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    parser.add_argument("--results", default="fleet_results.json")
    parser.add_argument("--feeder-homes", type=int, default=3235)
    parser.add_argument("--draws", type=int, default=300)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    totals = load_totals(workdir / args.results)
    pool = totals.shape[1]

    # Pairwise correlation over the coldest week: near 1.0 means clones.
    daily = totals.resample("D").mean().mean(axis=1)
    end = daily.rolling(7).mean().idxmax()
    window = totals.loc[end - pd.Timedelta(days=6) : end + pd.Timedelta(days=1)]
    corr = window.corr().to_numpy()
    off_diagonal = corr[~np.eye(pool, dtype=bool)]

    sizes = [n for n in (1, 2, 3, 6, 12, 18, 24, 32) if n <= pool]
    curve = coincidence(totals, sizes, args.draws, args.seed)

    # Is the curve still falling at the pool's edge?
    tail = [r["peak_kw_per_home"] for r in curve[-3:]]
    marginal = (tail[-1] / tail[0] - 1.0) * 100.0 if len(tail) >= 2 else float("nan")

    scale = [
        replicate(totals, args.feeder_homes, args.seed, jitter)
        for jitter in (0, 2, 8, 24)
    ]

    report = {
        "pool_dwellings": pool,
        "pairwise_correlation": {
            "median": round(float(np.median(off_diagonal)), 3),
            "p90": round(float(np.quantile(off_diagonal, 0.90)), 3),
            "max": round(float(off_diagonal.max()), 3),
        },
        "coincidence_curve": curve,
        "convergence": {
            "last_three_sizes": [r["homes"] for r in curve[-3:]],
            "marginal_change_pct": round(marginal, 2),
        },
        "feeder_scale_up": scale,
        "reference": {
            "literature_coincidence_factor": 0.85,
            "gridalyn_dwelling_heat_kw_at_minus25": 6.0,
            "gridalyn_dwelling_annual_mwh": [20, 22],
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

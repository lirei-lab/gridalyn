"""Plot the simulated Quebec fleet: individual dwellings, aggregate, diversity.

Three figures, each answering a different question about the fleet:

``fleet_individual``
    Do dwellings differ from one another? Individual 15-minute traces over a
    cold winter window, plus the fleet mean. If the stochastic schedules were
    seeded identically this figure shows near-parallel curves.

``fleet_aggregate``
    What does the feeder see? The fleet total, decomposed by end use, over the
    same window.

``fleet_diversity``
    How much does coincidence fall as homes are pooled? Peak kW per home
    against the number of homes sharing a transformer, bootstrapped over random
    subsets. This is the axis ``tests/test_building_diversity_vs_hq.py`` pins
    the RC generator against, so it is the one that makes the fleet comparable
    to the measured Hydro-Quebec set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

KBTU_TO_KWH = 0.293071


def _echo(message: str) -> None:
    """Print progress to stderr."""
    print(message, file=sys.stderr, flush=True)


def load_dwelling(path: Path, minutes: int) -> pd.DataFrame:
    """Return one dwelling's electric end uses in kW on a datetime index."""
    frame = pd.read_csv(path, low_memory=False)
    # Row 0 of an OS-HPXML timeseries CSV carries units, not data. Read the
    # unit before dropping it: this build emits kWh per interval, but the same
    # writer emits kBtu under other settings and silently scaling one as the
    # other is a 3.4x error that would look plausible on a plot.
    unit_row = frame.iloc[0].astype(str)
    if unit_row.str.contains("kBtu|kWh", case=False, na=False).any():
        unit = "kBtu" if unit_row.str.contains("kBtu", case=False).any() else "kWh"
        frame = frame.iloc[1:].reset_index(drop=True)
    else:
        unit = "kWh"
    to_kwh = KBTU_TO_KWH if unit == "kBtu" else 1.0
    time_col = frame.columns[0]
    index = pd.to_datetime(frame[time_col], errors="coerce")
    wanted = [
        c
        for c in frame.columns
        if c.startswith("End Use: Electricity:") and "Fans/Pumps" not in c
    ]
    values = frame[wanted].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    # energy per interval -> average kW over that interval
    power = values * to_kwh / (minutes / 60.0)
    power.columns = [
        c.replace("End Use: Electricity: ", "").split(" (")[0] for c in wanted
    ]
    power.index = index
    return power.loc[:, power.sum() > 0]


def cold_window(total: pd.Series, days: int) -> tuple[Any, Any]:
    """Return the start/end of the coldest ``days``-long window by mean load."""
    daily = total.resample("D").mean()
    window = daily.rolling(days).mean()
    end = window.idxmax()
    start = end - pd.Timedelta(days=days - 1)
    return start, end + pd.Timedelta(days=1)


def figure_individual(
    frames: dict[str, pd.DataFrame], lo: Any, hi: Any, out: Path
) -> None:
    """Plot individual dwelling totals over the window, with the fleet mean."""
    fig, axis = plt.subplots(figsize=(13, 5.2))
    totals = {}
    for name, frame in frames.items():
        series = frame.sum(axis=1).loc[lo:hi]
        totals[name] = series
        axis.plot(series.index, series.to_numpy(), lw=0.7, alpha=0.55)
    mean = pd.DataFrame(totals).mean(axis=1)
    axis.plot(mean.index, mean.to_numpy(), lw=2.4, color="black", label="fleet mean")
    axis.set_ylabel("dwelling electric power (kW)")
    axis.set_title(
        f"{len(frames)} Québec all-electric dwellings — individual 15-min traces, "
        "coldest week"
    )
    axis.legend(loc="upper left")
    axis.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def figure_aggregate(
    frames: dict[str, pd.DataFrame], lo: Any, hi: Any, out: Path
) -> None:
    """Plot the fleet total decomposed by end use."""
    stack = None
    for frame in frames.values():
        piece = frame.loc[lo:hi]
        stack = piece if stack is None else stack.add(piece, fill_value=0.0)
    assert stack is not None
    order = stack.sum().sort_values(ascending=False).index
    fig, axis = plt.subplots(figsize=(13, 5.2))
    axis.stackplot(
        stack.index,
        *[stack[c].to_numpy() for c in order],
        labels=list(order),
        alpha=0.9,
    )
    axis.set_ylabel("fleet electric power (kW)")
    axis.set_title(
        f"Fleet aggregate ({len(frames)} dwellings) by end use — coldest week"
    )
    axis.legend(loc="upper left", ncol=3, fontsize=9)
    axis.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def diversity_curve(
    totals: pd.DataFrame, sizes: list[int], draws: int, seed: int
) -> pd.DataFrame:
    """Return peak kW per home against homes pooled, over random subsets."""
    rng = np.random.default_rng(seed)
    columns = list(totals.columns)
    rows = []
    for size in sizes:
        if size > len(columns):
            continue
        peaks = []
        for _ in range(draws):
            pick = rng.choice(len(columns), size=size, replace=False)
            pooled = totals.iloc[:, pick].sum(axis=1)
            peaks.append(pooled.max() / size)
        rows.append(
            {
                "homes": size,
                "p50": float(np.median(peaks)),
                "p10": float(np.quantile(peaks, 0.10)),
                "p90": float(np.quantile(peaks, 0.90)),
            }
        )
    return pd.DataFrame(rows)


def figure_diversity(curve: pd.DataFrame, out: Path) -> None:
    """Plot the diversity curve with its inter-decile band."""
    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    axis.fill_between(curve["homes"], curve["p10"], curve["p90"], alpha=0.25)
    axis.plot(curve["homes"], curve["p50"], marker="o", lw=2)
    axis.set_xlabel("homes sharing the transformer")
    axis.set_ylabel("peak kW per home")
    axis.set_title("Diversity: coincident peak per home falls as homes are pooled")
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    """Load the fleet results and write the three figures plus a summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    results = json.loads((workdir / "fleet_results.json").read_text(encoding="utf-8"))
    minutes = int(results["resolution_minutes"])

    frames: dict[str, pd.DataFrame] = {}
    for record in results["dwellings"]:
        if record["status"] != "ok":
            continue
        name = Path(record["archetype"]).stem
        frames[name] = load_dwelling(Path(record["timeseries"]), minutes)
    if not frames:
        _echo("no successful dwellings to plot")
        return 1
    _echo(f"loaded {len(frames)} dwellings, {minutes}-minute resolution")

    totals = pd.DataFrame({name: f.sum(axis=1) for name, f in frames.items()})
    lo, hi = cold_window(totals.mean(axis=1), args.days)
    _echo(f"coldest {args.days}-day window: {lo.date()} .. {hi.date()}")

    figures = workdir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    figure_individual(frames, lo, hi, figures / "fleet_individual.png")
    figure_aggregate(frames, lo, hi, figures / "fleet_aggregate.png")
    sizes = [n for n in (1, 2, 3, 6, 12, 18, 24) if n <= len(frames)]
    curve = diversity_curve(totals, sizes, args.draws, args.seed)
    figure_diversity(curve, figures / "fleet_diversity.png")

    per_home_peak = {name: float(series.max()) for name, series in totals.items()}
    summary = {
        "dwellings": len(frames),
        "resolution_minutes": minutes,
        "window": [str(lo), str(hi)],
        "annual_kwh": {
            name: round(float(series.sum()) * minutes / 60.0)
            for name, series in totals.items()
        },
        "individual_peak_kw": {k: round(v, 2) for k, v in per_home_peak.items()},
        "diversity_curve": curve.to_dict(orient="records"),
        "end_uses": sorted({c for f in frames.values() for c in f.columns}),
    }
    (workdir / "fleet_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"figures": str(figures), "dwellings": len(frames)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

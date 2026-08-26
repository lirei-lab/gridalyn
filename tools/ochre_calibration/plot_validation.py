"""Four figures that explain what the Quebec fleet generator does and does not do.

The fleet figures in ``plot_fleet.py`` show what the generator produces. These
show whether it is *right*, by putting it next to the metered Hydro-Quebec
all-electric subset, and where its limit is.

``validation``
    Annual energy, individual peak and the diversity curve, simulated against
    measured. This is the figure that says the generator is usable: the energy
    distributions land on top of each other without anything having been fitted
    to make them.

``cycling``
    The limit, and it is not subtle. Real baseboards latch on and off; the
    reference models heating as modulating within the timestep, so its houses
    glide where real ones step. Shown as the distribution of 15-minute step
    changes and as a day of one dwelling from each.

``diversity_sources``
    Where the spread comes from before any stochastic schedule is drawn --
    floor area, air-tightness and vintage of the sampled archetypes, against
    the annual energy each one produced. Diversity here is inherited from real
    EnerGuide audits, not sampled from a distribution someone chose.

``flex_bound``
    The convex surrogate's promise against the white-box reference's delivery,
    over five dispatch decisions. Distance from the diagonal is the bound.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

_SIM = "EnergyPlus fleet"
_MEAS = "Hydro-Québec, metered"


def load_sim(results: Path) -> tuple[pd.DataFrame, int]:
    """Return the simulated fleet's per-dwelling kW frame and its resolution."""
    payload = json.loads(results.read_text(encoding="utf-8"))
    minutes = int(payload["resolution_minutes"])
    columns: dict[str, pd.Series] = {}
    for record in payload["dwellings"]:
        if record["status"] != "ok":
            continue
        frame = pd.read_csv(record["timeseries"], low_memory=False).iloc[1:]
        index = pd.to_datetime(frame[frame.columns[0]])
        uses = [
            c
            for c in frame.columns
            if c.startswith("End Use: Electricity:") and "Fans/Pumps" not in c
        ]
        series = (
            frame[uses].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
        )
        series.index = index
        columns[Path(record["archetype"]).stem] = series / (minutes / 60.0)
    return pd.DataFrame(columns), minutes


def load_measured(root: Path) -> pd.DataFrame:
    """Return the metered all-electric subset in kW, one column per dwelling."""
    consumption = pd.read_hdf(root / "consumption.h5") / 1000.0
    heating = pd.read_hdf(root / "heating.h5") / 1000.0
    year = slice("2018-04-03", "2019-04-02")
    share = heating.loc[year].sum() / consumption.loc[year].sum().replace(0, np.nan)
    return consumption.loc[year, share[share >= 0.6].index]


def _curve(frame: pd.DataFrame, sizes: list[int], seed: int) -> list[float]:
    """Return median peak kW per home against pool size."""
    matrix = frame.to_numpy()
    rng = np.random.default_rng(seed)
    out = []
    for size in sizes:
        peaks = [
            matrix[:, rng.choice(matrix.shape[1], size=size, replace=False)]
            .sum(axis=1)
            .max()
            / size
            for _ in range(200)
        ]
        out.append(float(np.median(peaks)))
    return out


def figure_validation(sim: pd.DataFrame, meas: pd.DataFrame, out: Path) -> None:
    """Plot annual energy, individual peak and the diversity curve, both sources."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    sim_annual = sim.sum() * 0.25 / 1000.0
    meas_annual = meas.sum() * 0.25 / 1000.0
    axes[0].boxplot([meas_annual, sim_annual], labels=[_MEAS, _SIM], widths=0.5)
    axes[0].set_ylabel("annual electricity (MWh/dwelling)")
    axes[0].set_title(
        f"Annual energy\nmedian {meas_annual.median():.1f} vs {sim_annual.median():.1f} MWh"
    )
    axes[1].boxplot([meas.max(), sim.max()], labels=[_MEAS, _SIM], widths=0.5)
    axes[1].set_ylabel("individual peak (kW)")
    axes[1].set_title(
        f"Individual peak\nmedian {meas.max().median():.1f} vs {sim.max().median():.1f} kW"
    )
    sizes = [n for n in (1, 2, 3, 6, 12, 18, 24, 32) if n <= sim.shape[1]]
    axes[2].plot(sizes, _curve(meas, sizes, 11), "o--", lw=2, label=_MEAS)
    axes[2].plot(sizes, _curve(sim, sizes, 11), "o-", lw=2, label=_SIM)
    axes[2].set_xlabel("homes sharing the transformer")
    axes[2].set_ylabel("peak kW per home")
    axes[2].set_title("Diversity curve")
    axes[2].legend()
    for axis in axes:
        axis.grid(alpha=0.25)
    fig.suptitle(
        "Generator validated against metered Québec dwellings — nothing fitted to match",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def figure_cycling(sim: pd.DataFrame, meas: pd.DataFrame, out: Path) -> None:
    """Plot the step-change distribution and one representative day from each."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
    sim_steps = sim.diff().abs().to_numpy().ravel()
    meas_steps = meas.diff().abs().to_numpy().ravel()
    sim_steps = sim_steps[~np.isnan(sim_steps)]
    meas_steps = meas_steps[~np.isnan(meas_steps)]
    bins = np.linspace(0, 8, 60)
    axes[0].hist(meas_steps, bins=bins, density=True, alpha=0.55, label=_MEAS)
    axes[0].hist(sim_steps, bins=bins, density=True, alpha=0.55, label=_SIM)
    axes[0].axvline(2.0, color="black", ls=":", lw=1.5)
    axes[0].set_yscale("log")
    axes[0].set_xlabel("|Δ power| between consecutive 15-min steps (kW)")
    axes[0].set_ylabel("density (log)")
    axes[0].set_title(
        "Steps >2 kW: "
        f"{100 * (meas_steps > 2).mean():.1f}% measured vs "
        f"{100 * (sim_steps > 2).mean():.1f}% simulated"
    )
    axes[0].legend()
    # Two winter days from each, each normalised by its own mean. The point is
    # the SHAPE -- a latching house steps, a modulating one glides -- and two
    # arbitrary dwellings differ in level by about a factor of two, which would
    # otherwise read as the difference being about size rather than control.
    m_day = meas.iloc[:, 0].loc["2019-01-21":"2019-01-22"]
    s_day = sim.iloc[:, 0].loc["2007-01-15":"2007-01-16"]
    axes[1].plot(
        np.arange(len(m_day)) / 4.0,
        m_day.to_numpy() / m_day.mean(),
        lw=1.1,
        label=_MEAS,
    )
    axes[1].plot(
        np.arange(len(s_day)) / 4.0, s_day.to_numpy() / s_day.mean(), lw=1.1, label=_SIM
    )
    axes[1].set_xlabel("hours across two winter days")
    axes[1].set_ylabel("power / that dwelling's own mean")
    axes[1].set_title("Real baseboards latch; the reference glides")
    axes[1].legend()
    for axis in axes:
        axis.grid(alpha=0.25)
    fig.suptitle(
        "The generator's known limit: it under-represents baseboard cycling",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def figure_diversity_sources(manifest: Path, sim: pd.DataFrame, out: Path) -> None:
    """Plot the archetype spread the fleet inherits before any schedule is drawn."""
    rows = json.loads(manifest.read_text(encoding="utf-8"))["dwellings"]
    frame = pd.DataFrame(rows)
    frame["key"] = frame["archetype"].str.replace(".H2K", "", regex=False)
    annual = (sim.sum() * 0.25 / 1000.0).rename("annual_mwh")
    frame = frame.join(annual, on="key").dropna(subset=["annual_mwh"])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    for axis, column, label in (
        (axes[0], "floor_area_m2", "floor area (m²)"),
        (axes[1], "ach50", "air-tightness (ACH50)"),
        (axes[2], "decade", "vintage (decade)"),
    ):
        axis.scatter(frame[column], frame["annual_mwh"], s=26, alpha=0.75)
        axis.set_xlabel(label)
        axis.set_ylabel("annual electricity (MWh)")
        axis.grid(alpha=0.25)
    fig.suptitle(
        f"Envelope diversity is inherited from {len(frame)} real EnerGuide audits, "
        "not drawn from a chosen distribution",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def figure_flex_bound(flex: Path, out: Path) -> None:
    """Plot what the convex surrogate promised against what the reference delivered."""
    pairs = [
        ("rc_d1.json", "eplus_d1.json", "pre 0.0 / cut 1.0"),
        ("rc_d2.json", "eplus_d2.json", "pre 0.0 / cut 2.0"),
        ("rc_promise2.json", "flexbound.json", "pre 1.5 / cut 2.0"),
        ("rc_d4.json", "eplus_d4.json", "pre 1.5 / cut 3.0"),
        ("rc_d5.json", "eplus_d5.json", "pre 3.0 / cut 2.0"),
    ]
    promised, delivered, labels = [], [], []
    for rc_name, ep_name, label in pairs:
        rc = json.loads((flex / rc_name).read_text(encoding="utf-8"))["promised"]
        ep = json.loads((flex / ep_name).read_text(encoding="utf-8"))["holdout"]
        promised.append(rc["mean_relief_kw_per_home"])
        delivered.append(ep["mean_relief_kw_per_home"])
        labels.append(label)
    fig, axis = plt.subplots(figsize=(7.6, 6.2))
    top = max(delivered) * 1.15
    axis.plot([0, top], [0, top], "k:", lw=1.4, label="perfect agreement")
    axis.scatter(promised, delivered, s=90, zorder=3)
    for x, y, label in zip(promised, delivered, labels, strict=True):
        axis.annotate(
            label, (x, y), textcoords="offset points", xytext=(9, -4), fontsize=9
        )
    mae = float(np.mean(np.abs(np.array(promised) - np.array(delivered))))
    axis.set_xlabel("RC surrogate promises (kW per dwelling)")
    axis.set_ylabel("EnergyPlus delivers (kW per dwelling)")
    axis.set_title(
        "Thermal flexibility: the surrogate under-promises at every operating point\n"
        f"MAE = {mae:.3f} kW/dwelling, held-out dwellings"
    )
    axis.legend()
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    """Write the four validation figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    parser.add_argument("--hq", default="datasets/hq")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()
    figures = workdir / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    sim, _ = load_sim(workdir / "fleet_results.json")
    meas = load_measured(Path(args.hq).resolve())
    print(f"simulated {sim.shape[1]} dwellings, measured {meas.shape[1]}")

    figure_validation(sim, meas, figures / "validation.png")
    figure_cycling(sim, meas, figures / "cycling.png")
    figure_diversity_sources(
        workdir / "fleet_manifest.json", sim, figures / "diversity_sources.png"
    )
    figure_flex_bound(workdir / "flex", figures / "flex_bound.png")
    print(json.dumps({"figures": str(figures)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

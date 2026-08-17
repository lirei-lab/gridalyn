"""Stage: validate thermal comfort by propagating schedules through the RC model.

The coordinated heating schedule is fed through each home's first-order RC thermal
response to obtain the indoor-temperature excursion from the thermostat baseline.
We compare the comfort-aware coordination (penalizing modelled temperature) with a
naive flatten (no temperature penalty) to show that the comfort-aware variant
holds the worst-case excursion near the configured band while still clearing the
feeder overload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gridalyn.projects.scripting import project_script  # configures headless Agg
from projects.admm_thermal_consensus.scripts import comfort
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts.admm.consensus import solve_sharing_admm


def _stats(dt: np.ndarray) -> dict[str, float]:
    return {
        "median_peak_dT_c": float(np.median(dt)),
        "mean_peak_dT_c": float(dt.mean()),
        "worst_peak_dT_c": float(dt.max()),
        "frac_homes_over_band": float((dt > C.COMFORT_BAND_C).mean()),
    }


def main() -> None:
    script = project_script()
    import matplotlib.pyplot as plt

    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    bg = pd.read_parquet(C.DATA_DIR / "agents_background.parquet").to_numpy()
    bg_total = bg.sum(axis=0)

    base_kwargs = dict(
        heating=heat,
        background=bg,
        alpha=C.DEFERRABILITY_ALPHA,
        rho=C.ADMM_RHO,
        lam=C.ADMM_LAMBDA,
        mu=C.ADMM_MU,
        relax=C.ADMM_RELAX,
        max_iters=C.ADMM_MAX_ITERS,
        tol=C.ADMM_TOL,
    )
    prox = comfort.prox_inverse()
    x_comfort = solve_sharing_admm(**base_kwargs, comfort_prox_inverse=prox).x
    x_naive = solve_sharing_admm(**base_kwargs).x  # no temperature penalty

    dt_comfort = comfort.temperature_excursion(x_comfort, heat)
    dt_naive = comfort.temperature_excursion(x_naive, heat)
    peak_comfort = float((x_comfort.sum(axis=0) + bg_total).max())
    peak_naive = float((x_naive.sum(axis=0) + bg_total).max())

    results = {
        "comfort_gamma": C.COMFORT_GAMMA,
        "comfort_band_c": C.COMFORT_BAND_C,
        "comfort_aware": {**_stats(dt_comfort), "ideal_peak_kw": peak_comfort},
        "naive_flatten": {**_stats(dt_naive), "ideal_peak_kw": peak_naive},
        "per_home_peak_dT_c": {
            "comfort_aware": dt_comfort.tolist(),
            "naive_flatten": dt_naive.tolist(),
        },
    }
    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    res_path = script.write_json("outputs/json/comfort_validation.json", results)

    # figure: sorted per-home worst indoor-temperature excursion
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(
        np.sort(dt_naive)[::-1],
        "o-",
        color="tab:red",
        label=f"Naive flatten (worst {dt_naive.max():.2f} C)",
    )
    ax.plot(
        np.sort(dt_comfort)[::-1],
        "s-",
        color="tab:blue",
        label=f"Comfort-aware (worst {dt_comfort.max():.2f} C)",
    )
    ax.axhline(
        C.COMFORT_BAND_C,
        ls="--",
        color="black",
        alpha=0.6,
        label=f"{C.COMFORT_BAND_C:.0f} C comfort band",
    )
    ax.axhline(0.4, ls=":", color="gray", alpha=0.6, label="0.4 C thermostat deadband")
    ax.set_xlabel("Home (sorted by excursion)")
    ax.set_ylabel("Worst indoor-temperature excursion [C]")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig_paths = [
        C.FIGURES_DIR / "fig_comfort.png",
        C.FIGURES_DIR / "fig_comfort.pdf",
    ]
    for p in fig_paths:
        fig.savefig(p, bbox_inches="tight", dpi=200)
    plt.close(fig)
    pd.DataFrame(
        {
            "home": np.arange(C.N_AGENTS),
            "naive_dT_c": dt_naive,
            "comfort_dT_c": dt_comfort,
        }
    ).to_csv(C.FIGURES_DIR / "comfort_excursion.csv", index=False)

    script.write_report(
        "comfort_report",
        artifacts=[res_path, *[script.file_reference(p) for p in fig_paths]],
        summary={
            "comfort_gamma": C.COMFORT_GAMMA,
            "comfort_aware_worst_dT_c": results["comfort_aware"]["worst_peak_dT_c"],
            "comfort_aware_median_dT_c": results["comfort_aware"]["median_peak_dT_c"],
            "naive_worst_dT_c": results["naive_flatten"]["worst_peak_dT_c"],
            "comfort_aware_ideal_peak_kw": peak_comfort,
        },
    )
    print(
        f"comfort_validation: comfort-aware worst dT {dt_comfort.max():.2f} C "
        f"(naive {dt_naive.max():.2f} C); ideal peak {peak_comfort:.1f} kW"
    )


if __name__ == "__main__":
    main()

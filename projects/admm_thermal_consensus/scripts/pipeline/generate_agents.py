"""Stage: synthesize cold-day per-agent heating and background profiles."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.assets.datagen.core import GridLoadFacade
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    script = project_script()
    window = select_cold_day(
        download_tmy(source=C.WEATHER_SOURCE), duration_hours=C.DURATION_HOURS
    )
    temperature = window["temp_air"]
    heat_kw, bg_kw = GridLoadFacade.generate_loads(
        generator_type=C.GENERATOR,
        df_weather=temperature,
        n_houses=C.N_AGENTS,
        resolution_minutes=C.RESOLUTION_MINUTES,
        seed=C.SEED,
    )
    # GridLoadFacade returns (T, N); store agents as rows (N, T)
    heat = np.asarray(heat_kw).T[:, : C.N_STEPS]
    bg = np.asarray(bg_kw).T[:, : C.N_STEPS]
    temp = (
        temperature.resample(f"{C.RESOLUTION_MINUTES}min").mean().to_numpy()[: C.N_STEPS]
    )

    cols = [f"t{j:03d}" for j in range(C.N_STEPS)]
    idx = [f"agent_{i:03d}" for i in range(C.N_AGENTS)]
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    heat_path = C.DATA_DIR / "agents_heating.parquet"
    bg_path = C.DATA_DIR / "agents_background.parquet"
    pd.DataFrame(heat, index=idx, columns=cols).to_parquet(heat_path)
    pd.DataFrame(bg, index=idx, columns=cols).to_parquet(bg_path)

    levels = heat.mean(axis=1)
    params = {
        "n_agents": C.N_AGENTS,
        "n_steps": C.N_STEPS,
        "resolution_minutes": C.RESOLUTION_MINUTES,
        "temperature_c": temp.tolist(),
        "agent_levels_kw": levels.tolist(),
        "total_heating_kwh": float(heat.sum() * C.STEP_HOURS),
        "uncoordinated_peak_kw": float((heat.sum(axis=0) + bg.sum(axis=0)).max()),
    }
    params_path = C.JSON_DIR / "agent_params.json"
    params_path.write_text(json.dumps(params, indent=2), encoding="utf-8")

    script.write_report(
        "agents_report",
        artifacts=[
            script.file_reference(heat_path),
            script.file_reference(bg_path),
            script.file_reference(params_path),
        ],
        summary={
            "n_agents": C.N_AGENTS,
            "n_steps": C.N_STEPS,
            "min_temperature_c": float(temp.min()),
            "uncoordinated_peak_kw": params["uncoordinated_peak_kw"],
            "total_heating_kwh": params["total_heating_kwh"],
        },
    )
    print(f"generate_agents: {C.N_AGENTS} agents, peak {params['uncoordinated_peak_kw']:.1f} kW")


if __name__ == "__main__":
    main()

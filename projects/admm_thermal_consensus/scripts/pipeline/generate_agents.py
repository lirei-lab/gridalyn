"""Stage: synthesize cold-day per-agent heating and background profiles."""

from __future__ import annotations

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    script = project_script()
    window = select_cold_day(
        download_tmy(source=C.WEATHER_SOURCE), duration_hours=C.DURATION_HOURS
    )
    temperature = window["temp_air"]
    # The SDK agent is driven directly rather than through GridLoadFacade: the
    # facade takes no calibration overrides and integrates at the output
    # resolution, while the Québec operating point needs the envelope/capacity
    # overrides and a 1-min integration (latching thermostats resolved at
    # 15 min would smear their cycling into the very average they should break).
    from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
    from gridalyn.assets.datagen.agents.dhw import make_dhw_tank_fleet

    minutely = temperature.resample("1min").interpolate()
    buildings = make_buildings(C.N_AGENTS, seed=C.SEED)
    for building in buildings:
        building.R = C.R_STUDY_B
        building.p_heat_max = C.P_HEAT_QUEBEC
    results = simulate_buildings(
        buildings, minutely, random_seed=C.SEED, control=C.HEATING_CONTROL
    )
    step = f"{C.RESOLUTION_MINUTES}min"
    heat = np.column_stack(
        [results[u]["p_heat_kw"].resample(step).mean().to_numpy() for u in results]
    ).T[:, : C.N_STEPS]
    # The electric water-heater tank is NOT dispatchable here -- the coordinator
    # schedules space heating only -- so it rides with the uncontrollable
    # background, which is where its ~4.5 kW recovery peaks actually land.
    background = np.column_stack(
        [
            C.BG_SCALE * results[u]["p_bg_kw"].resample(step).mean().to_numpy()
            for u in results
        ]
    ).T[:, : C.N_STEPS]
    dhw = np.column_stack(
        [
            make_dhw_tank_fleet(
                np.random.default_rng(C.SEED + C.DHW_SEED_SALT + 1000 * i),
                1,
                temperature,
                res_minutes=C.RESOLUTION_MINUTES,
            )
            for i in range(C.N_AGENTS)
        ]
    ).T[:, : C.N_STEPS]
    bg = background + dhw[:, : background.shape[1]]
    temp = (
        temperature.resample(f"{C.RESOLUTION_MINUTES}min")
        .mean()
        .to_numpy()[: C.N_STEPS]
    )

    cols = [f"t{j:03d}" for j in range(C.N_STEPS)]
    idx = [f"agent_{i:03d}" for i in range(C.N_AGENTS)]
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    heat_path = C.DATA_DIR / "agents_heating.parquet"
    bg_path = C.DATA_DIR / "agents_background.parquet"
    pd.DataFrame(heat, index=idx, columns=cols).to_parquet(heat_path)
    pd.DataFrame(bg, index=idx, columns=cols).to_parquet(bg_path)

    # per-home RC thermal parameters (same seed -> same buildings as the loads),
    # exported so the coordinator can penalize indoor-temperature excursion and
    # the comfort-validation stage can replay the thermal response.
    from gridalyn.assets.datagen.agents.fleet import make_buildings

    buildings = make_buildings(C.N_AGENTS, seed=C.SEED)
    resistance = [float(b.R) for b in buildings]
    capacitance = [float(b.C) for b in buildings]

    levels = heat.mean(axis=1)
    params = {
        "n_agents": C.N_AGENTS,
        "n_steps": C.N_STEPS,
        "resolution_minutes": C.RESOLUTION_MINUTES,
        "temperature_c": temp.tolist(),
        "agent_levels_kw": levels.tolist(),
        "thermal_resistance_c_per_kw": resistance,
        "thermal_capacitance_kwh_per_c": capacitance,
        "total_heating_kwh": float(heat.sum() * C.STEP_HOURS),
        "uncoordinated_peak_kw": float((heat.sum(axis=0) + bg.sum(axis=0)).max()),
    }
    params_path = script.write_json("outputs/json/agent_params.json", params)

    script.write_report(
        "agents_report",
        artifacts=[
            script.file_reference(heat_path),
            script.file_reference(bg_path),
            params_path,
        ],
        summary={
            "n_agents": C.N_AGENTS,
            "n_steps": C.N_STEPS,
            "min_temperature_c": float(temp.min()),
            "uncoordinated_peak_kw": params["uncoordinated_peak_kw"],
            "total_heating_kwh": params["total_heating_kwh"],
        },
    )
    print(
        f"generate_agents: {C.N_AGENTS} agents, peak {params['uncoordinated_peak_kw']:.1f} kW"
    )


if __name__ == "__main__":
    main()

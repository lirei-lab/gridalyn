from pathlib import Path

import numpy as np
import pandas as pd


def _write_mc_inputs(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "run_0": [1.0, 2.0, 3.0],
            "run_1": [2.0, 4.0, 6.0],
        }
    ).to_parquet(data_dir / "substation_baseline_mc.parquet", index=False)
    pd.DataFrame(
        {
            "run_0": [0.1, 0.2, 0.3],
            "run_1": [0.2, 0.3, 0.4],
        }
    ).to_parquet(data_dir / "substation_ev_capability_mc.parquet", index=False)
    pd.DataFrame(
        {
            "run_0": [10.0, 11.0, 12.0],
            "run_1": [13.0, 14.0, 15.0],
        }
    ).to_parquet(data_dir / "substation_powerflow_mc.parquet", index=False)


def test_core_timeseries_readers_use_explicit_data_dir(tmp_path):
    from gridalyn.io.timeseries import (
        get_baseline_building_load,
        get_baseline_building_load_all,
        get_ev_capability_load_all,
        get_powerflow_ext_grid_load_all,
    )

    _write_mc_inputs(tmp_path)

    np.testing.assert_allclose(
        get_baseline_building_load(data_dir=tmp_path),
        np.array([1500.0, 3000.0, 4500.0]),
    )
    np.testing.assert_allclose(
        get_baseline_building_load(percentile=0, data_dir=tmp_path),
        np.array([1000.0, 2000.0, 3000.0]),
    )
    np.testing.assert_allclose(
        get_baseline_building_load_all(data_dir=tmp_path),
        np.array([[1000.0, 2000.0, 3000.0], [2000.0, 4000.0, 6000.0]]),
    )
    np.testing.assert_allclose(
        get_ev_capability_load_all(data_dir=tmp_path),
        np.array([[100.0, 200.0, 300.0], [200.0, 300.0, 400.0]]),
    )
    np.testing.assert_allclose(
        get_powerflow_ext_grid_load_all(data_dir=tmp_path),
        np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]]),
    )


def test_project_data_api_delegates_to_core_reader():
    from gridalyn.io.timeseries import get_baseline_building_load_all as core_reader
    from projects.flexibility_cls.scripts import data_api as project_data_api

    assert project_data_api.get_baseline_building_load_all.__wrapped__ is core_reader


import numpy as np

from gridalyn.assets.modeling.transformers import TransformerThermalModel
from projects.flexibility_cls.scripts import config as ev_project_config


def test_core_thermal_forecast_builds_dynamic_limit_from_ambient_trace():
    from gridalyn.assets.modeling.thermal import (
        THERMAL_LIMIT_MODEL,
        build_thermal_forecast_from_ambient,
        thermal_forecast_metadata,
    )

    ambient_c = np.array([-22.0, -10.0, 0.0])
    forecast = build_thermal_forecast_from_ambient(
        ambient_c,
        resolution_minutes=15,
        s_rated_kva=15_000.0,
        theta_max=110.0,
        start_time="2026-01-01 00:00:00",
    )
    reference = TransformerThermalModel(s_rated_kva=15_000.0, theta_max=110.0)

    assert forecast.resolution_minutes == 15
    assert forecast.start_time == "2026-01-01 00:00:00"
    np.testing.assert_allclose(
        forecast.p_limit_kw,
        [reference.max_load_for_temp(float(temp_c)) for temp_c in ambient_c],
    )

    metadata = thermal_forecast_metadata(forecast, peak_idx=1, peak_label="test")
    assert metadata["thermal_model"] == THERMAL_LIMIT_MODEL
    assert metadata["thermal_forecast_resolution_minutes"] == 15
    assert metadata["test_ambient_at_peak_c"] == -10.0


def test_ev_capacity_thermal_forecast_uses_project_parameters():
    from gridalyn.assets.datagen import build_thermal_forecast as core_build
    from projects.flexibility_cls.scripts.thermal_forecast import (
        build_thermal_forecast as project_build,
    )

    project_forecast = project_build(4)
    core_forecast = core_build(
        4,
        resolution_minutes=ev_project_config.RES_MINUTES,
        s_rated_kva=ev_project_config.S_RATED_KVA,
        theta_max=ev_project_config.THETA_MAX,
    )

    assert project_forecast.resolution_minutes == ev_project_config.RES_MINUTES
    np.testing.assert_allclose(project_forecast.ambient_c, core_forecast.ambient_c)
    np.testing.assert_allclose(project_forecast.p_limit_kw, core_forecast.p_limit_kw)

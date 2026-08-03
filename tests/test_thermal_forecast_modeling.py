import numpy as np

from gridalyn.assets.modeling.transformers import TransformerThermalModel


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

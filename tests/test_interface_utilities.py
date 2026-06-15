from __future__ import annotations

import pandas as pd
import pytest

from gridalyn.interfaces.reporting import dispatch_timeseries_metrics
from gridalyn.interfaces.viz import format_hour_label, save_figure_pair


def test_dispatch_timeseries_metrics_summarizes_energy_and_limits() -> None:
    frame = pd.DataFrame(
        {
            "t_hours": [0.0, 0.5, 1.0],
            "p_soft_cls_mw": [1.0, 2.0, 3.0],
            "p_hard_cls_mw": [0.0, 1.0, 0.0],
            "p_rebound_mw": [0.5, 0.0, 0.5],
            "p_limit_trace_mw": [19.0, 20.0, 18.5],
        }
    )

    metrics = dispatch_timeseries_metrics(frame)

    assert metrics["n_timesteps"] == 3
    assert metrics["resolution_hours"] == pytest.approx(0.5)
    assert metrics["soft_cls_mwh"] == pytest.approx(3.0)
    assert metrics["hard_cls_mwh"] == pytest.approx(0.5)
    assert metrics["rebound_mwh"] == pytest.approx(0.5)
    assert metrics["dynamic_limit_min_mw"] == pytest.approx(18.5)
    assert metrics["dynamic_limit_max_mw"] == pytest.approx(20.0)


def test_matplotlib_helpers_format_time_and_save_pair(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    assert format_hour_label(0.0) == "00:00"
    assert format_hour_label(23.75) == "23:45"
    assert format_hour_label(24.0) == "00:00"
    assert format_hour_label(1.999) == "02:00"

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    paths = save_figure_pair(fig, tmp_path / "demo.png")
    plt.close(fig)

    assert paths["png"].exists()
    assert paths["pdf"].exists()

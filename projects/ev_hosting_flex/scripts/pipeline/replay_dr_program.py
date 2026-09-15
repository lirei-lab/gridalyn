"""Replay the curtailment mechanism as dr_program conversations (bd 4ky.10).

The additive scientific consumer of the flexint epic. It reads the artifacts
``apply_curtailment_contracts`` reads, replays the day-ahead call, the real-time
backstop and its fair rotation through ``gridalyn.operations.interaction`` at
every level of the declared adoption grid, and writes a message log, an
interaction report and a summary. It changes no file another stage writes and no
number the study pins; the mechanism and its conventions are documented in
:mod:`projects.ev_hosting_flex.scripts._dr_replay`.

What it found on the governed artifacts, and why it reports a grid rather than one
figure: at the study's verified ~1 EV per dwelling this feeder does not congest,
so there is nothing to notify. Congestion first appears at 1.5 EVs per home, and
inside the <= ~2 EV/dwelling band the calibration adopted most windows arrive
without a day-ahead call. A single "pre-notified share" measured on the 16-EV
pool (2.67 EVs per home) would describe an adoption the study itself does not
defend.
"""

from __future__ import annotations

import argparse
from typing import Any

import numpy as np

from gridalyn.operations.interaction import (
    MessageBus,
    write_interaction_report,
    write_message_log,
)
from gridalyn.projects.scripting import ProjectScript, project_script
from projects.ev_hosting_flex.scripts._annual import feeder_rating, load_annual_tmy
from projects.ev_hosting_flex.scripts._dr_replay import (
    DAY_AHEAD_NOTICE_MINUTES,
    HEADLINE_FORECAST_SIGMA,
    _config_int,
    replay_adoption_point,
    resolve_adoption_points,
)
from projects.ev_hosting_flex.scripts._report import emit_stage_report
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    CONGESTION_EV_PER_HOME_GRID,
    DTYPE,
    FC_SIGMAS,
)
from projects.ev_hosting_flex.scripts.pipeline.generate_annual_mc import (
    feeder_home_count,
)

#: The study's float dtype and step width, typed once (see
#: :func:`projects.ev_hosting_flex.scripts._dr_replay._config_int`).
_DTYPE = np.dtype(str(DTYPE))
_RES_MINUTES = _config_int("annualResMinutes", ANNUAL_RES_MINUTES)

# SEAL-01: the BLAS thread cap lives in projects/ev_hosting_flex/scripts/__init__.py
# (imported before this stage under `{python} -m`).

LOG_RELATIVE = "outputs/operations/dr_replay_message_log.parquet"
JSON_RELATIVE = "outputs/json/dr_replay.json"
INTERACTION_REPORT_ID = "dr_replay_interaction_report"
REPORT_ID = "dr_replay_report"
PROGRAM_PREFIX = "ev_hosting_flex"


def _level_key(evs_per_home: float) -> str:
    """Return the summary-key spelling of an adoption level, e.g. ``1.5``."""
    return f"{evs_per_home:g}"


def derive_dr_replay(script: ProjectScript) -> dict[str, Any]:
    """Replay the mechanism across the declared grid and persist what it exchanged.

    Args:
        script: The project workspace handle.

    Returns:
        Dict with ``artifact_paths``, the report ``summary`` and the ``inputs``
        provenance records.

    Raises:
        ValueError: The headline forecast is not among the study's forecast bases,
            or replaying the log disagrees with the conversations the run kept.
    """
    if HEADLINE_FORECAST_SIGMA not in FC_SIGMAS:
        raise ValueError(
            f"replay_dr_program reads the sigma={HEADLINE_FORECAST_SIGMA} forecast, "
            f"but fcSigmas declares {list(FC_SIGMAS)}; add it or change "
            "HEADLINE_FORECAST_SIGMA"
        )
    data_dir = script.data_dir
    base = np.load(data_dir / "base_annual.npy").astype(_DTYPE)[0]
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(_DTYPE)
    forecast = np.load(
        data_dir / f"fc_base_sigma_{HEADLINE_FORECAST_SIGMA:.1f}.npy"
    ).astype(_DTYPE)
    cap, series = feeder_rating(load_annual_tmy())
    limit = (
        np.full(base.shape, cap, dtype=_DTYPE)
        if series is None
        else np.asarray(series, dtype=_DTYPE)
    )
    homes = feeder_home_count(script)
    pool_size = int(pool.shape[0])
    points = resolve_adoption_points(CONGESTION_EV_PER_HOME_GRID, homes, pool_size)

    channel = script.channel_model()
    bus = MessageBus(channel=channel)
    replayed: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        if not point["representable"]:
            replayed.append(
                {
                    **point,
                    "reason": (
                        f"{point['ev_count']} EVs exceed the {pool_size}-EV fleet "
                        "the annual chain generates; not truncated"
                    ),
                }
            )
            continue
        replayed.append(
            replay_adoption_point(
                bus,
                point_index=index,
                evs_per_home=point["evs_per_home"],
                ev_count=point["ev_count"],
                base=base,
                pool=pool,
                limit=limit,
                forecast=forecast,
                res_minutes=_RES_MINUTES,
                program_prefix=PROGRAM_PREFIX,
            )
        )
    epoch_minutes = int(base.shape[0]) * _RES_MINUTES
    until = float(len(points) * epoch_minutes)
    bus.run_until(until)

    log_path = script.path(LOG_RELATIVE)
    write_message_log(log_path, bus.log)
    interaction_path = script.reports_dir / f"{INTERACTION_REPORT_ID}.json"
    interaction = write_interaction_report(
        interaction_path,
        log=bus.log,
        book=bus.conversations,
        log_path=log_path,
        metadata=script.report_metadata(INTERACTION_REPORT_ID),
        until=until,
        channel=channel.descriptor,
        root=script.root,
    )
    errors = list(interaction["validation"]["errors"])
    if errors:
        raise ValueError(
            "replay_dr_program: replaying the message log disagrees with the "
            f"conversations the run kept: {'; '.join(errors)}"
        )

    content = [
        point
        for point in replayed
        if point["representable"] and point["conversation_count"] > 0
    ]
    payload = {
        "mechanism": "dayahead_notice_realtime_backstop_fair_rotation",
        "protocol": "dr_program",
        "adoption_grid_evs_per_home": [float(x) for x in CONGESTION_EV_PER_HOME_GRID],
        "feeder_home_count": homes,
        "ev_pool_size": pool_size,
        "forecast_sigma_c": HEADLINE_FORECAST_SIGMA,
        "day_ahead_notice_minutes": DAY_AHEAD_NOTICE_MINUTES,
        "epoch_minutes": epoch_minutes,
        "channel_model_id": channel.descriptor.channel_model_id,
        "first_adoption_with_curtailment_evs_per_home": (
            content[0]["evs_per_home"] if content else None
        ),
        "points": replayed,
    }
    json_ref = script.write_json(JSON_RELATIVE, payload)

    interaction_summary = interaction["summary"]
    summary: dict[str, Any] = {
        "feeder_home_count": homes,
        "ev_pool_size": pool_size,
        "first_adoption_with_curtailment_evs_per_home": payload[
            "first_adoption_with_curtailment_evs_per_home"
        ],
        "conversation_count": interaction_summary["conversation_count"],
        "message_count": interaction_summary["message_count"],
        "open_conversation_count": interaction_summary["open_conversation_count"],
        "not_representable_evs_per_home": [
            point["evs_per_home"] for point in replayed if not point["representable"]
        ],
    }
    for point in replayed:
        if not point["representable"]:
            continue
        key = _level_key(point["evs_per_home"])
        summary[f"curtailment_windows_at_{key}_ev_per_home"] = point[
            "curtailment_window_count"
        ]
        summary[f"notified_windows_at_{key}_ev_per_home"] = point[
            "notified_window_count"
        ]
        summary[f"conversations_at_{key}_ev_per_home"] = point["conversation_count"]
    return {
        "artifact_paths": [
            json_ref,
            script.file_reference(log_path),
            script.file_reference(interaction_path),
        ],
        "summary": summary,
        "inputs": [
            {
                "name": "channel_model",
                "type": "channel_model",
                **channel.descriptor.as_dict(),
            },
            {
                "name": "congestionEvPerHomeGrid",
                "type": "adoption_grid",
                "values": [float(x) for x in CONGESTION_EV_PER_HOME_GRID],
            },
        ],
    }


def run_stage() -> dict[str, Any]:
    """Run the replay and write its platform report.

    Returns:
        The written report payload.
    """
    script = project_script()
    derived = derive_dr_replay(script)
    return emit_stage_report(script, REPORT_ID, derived, inputs=derived["inputs"])


def main() -> None:
    """CLI entry point for the demand-response replay stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Replayed the curtailment mechanism through dr_program: "
        f"{summary.get('conversation_count')} conversations, "
        f"{summary.get('message_count')} messages; first curtailment at "
        f"{summary.get('first_adoption_with_curtailment_evs_per_home')} EVs/home; "
        f"not representable: {summary.get('not_representable_evs_per_home')}"
    )


if __name__ == "__main__":
    main()

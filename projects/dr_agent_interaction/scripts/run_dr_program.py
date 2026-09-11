"""Run one winter day of the study's demand-response program through dr_program."""

from __future__ import annotations

from typing import Any

import pandas as pd
from program_day import (
    ProgramDay,
    conversation_id,
    simulate_program_day,
    summarize_program_day,
)

from gridalyn.operations.interaction import write_interaction_report, write_message_log
from gridalyn.projects.scripting import project_script


def _conversation_table(day: ProgramDay) -> pd.DataFrame:
    book = day.bus.conversations
    rows: list[dict[str, Any]] = []
    for event in day.program.events:
        for index in range(day.program.participant_count):
            key = conversation_id(event, index)
            rows.append(
                {
                    "conversation_id": key,
                    "event_id": event.event_id,
                    "home": index,
                    "state": book[key].state if key in book else "never_notified",
                    "opted_out_by_home": key in day.opted_out,
                    "reported": key in day.reported,
                }
            )
    return pd.DataFrame(rows)


def _timeseries_table(day: ProgramDay) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "minute": day.minutes,
            "t_out_c": day.t_out_c,
            "baseline_kw": day.baseline_kw.sum(axis=1),
            "program_kw": day.actual_kw.sum(axis=1),
            "min_indoor_c": day.indoor_c.min(axis=1),
        }
    )


def main() -> int:
    script = project_script()
    program = script.load_demand_response_program()
    channel = script.channel_model()
    day = simulate_program_day(
        program=program, channel=channel, seed=script.simulation_seed("agents")
    )

    log_path = script.operations_dir / "dr_message_log.parquet"
    conversations_path = script.operations_dir / "dr_conversations.csv"
    timeseries_path = script.data_dir / "dr_program_timeseries.csv"
    interaction_path = script.reports_dir / "dr_interaction_report.json"
    write_message_log(log_path, day.bus.log)
    _conversation_table(day).to_csv(conversations_path, index=False)
    _timeseries_table(day).to_csv(timeseries_path, index=False)
    interaction = write_interaction_report(
        interaction_path,
        log=day.bus.log,
        book=day.bus.conversations,
        log_path=log_path,
        metadata=script.report_metadata("dr_interaction_report"),
        until=day.bus.scheduler.now,
        channel=channel.descriptor,
        root=script.root,
    )

    errors = list(interaction["validation"]["errors"])
    script.write_report(
        "dr_program_report",
        inputs=[
            {
                "name": "drProgram",
                "type": "demand_response_program",
                **dict(script.input("drProgram")),
            },
            {
                "name": "channel_model",
                "type": "channel_model",
                **channel.descriptor.as_dict(),
            },
            {
                "name": "appliance_background",
                "type": "generated_load_profile",
                "model": day.background_model,
                "seed_stream": "agents",
            },
        ],
        artifacts=[
            script.file_reference(log_path),
            script.file_reference(conversations_path),
            script.file_reference(timeseries_path),
            script.file_reference(interaction_path),
        ],
        summary=summarize_program_day(day),
        validation={"valid": not errors, "errors": errors, "warnings": []},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

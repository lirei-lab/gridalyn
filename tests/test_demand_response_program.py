"""A demand-response program: its validation, its payloads and its project loader.

``DemandResponseProgram`` is what a study declares under ``spec.inputs.drProgram``
and what the ``dr_program`` protocol's messages are built from. These gates
pin the three things a program must refuse or guarantee:

* an event whose window cannot happen, and a program whose events overlap,
  are located errors;
* payloads carry OpenADR 3.1.0 field names verbatim, the simulated-time window
  as ``flexint:`` fields, and a reported reduction rounded to 0.1 kWh -- the
  rounding keeps a report's message id, and so its draw on a lossy channel,
  stable across machines;
* the loader reads times of day, refuses unsupported keys and malformed times,
  and names the path of whatever it refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gridalyn.operations.interaction.dr_program import (
    ACTIVE_FROM_FIELD,
    ACTIVE_UNTIL_FIELD,
)
from gridalyn.operations.interaction.program import (
    CAPACITY_LIMIT_PAYLOAD,
    DemandResponseEvent,
    DemandResponseProgram,
    build_cancellation_payload,
    build_event_payload,
    build_opt_out_payload,
    build_report_payload,
    measure_reported_kwh,
)
from gridalyn.projects.loader import load_project
from gridalyn.projects.model_inputs import load_demand_response_program

STUDY = Path(__file__).resolve().parents[1] / "projects" / "dr_agent_interaction"


def _event(**changes):
    fields = {
        "event_id": "evt",
        "notify_at": 0.0,
        "start": 60.0,
        "end": 120.0,
        "capacity_limit_kw": 4.0,
    }
    return DemandResponseEvent(**{**fields, **changes})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"notify_at": 90.0}, "notified no later than it starts"),
        ({"end": 60.0}, "end after it starts"),
        ({"capacity_limit_kw": -1.0}, "non-negative kW"),
        ({"cancel_at": 120.0}, "between its notification and its end"),
        ({"start": float("nan")}, "finite simulated minute"),
    ],
)
def test_an_event_whose_window_cannot_happen_is_refused(changes, message):
    with pytest.raises(ValueError, match=message) as caught:
        _event(**changes)
    assert "event 'evt'" in str(caught.value)


def test_a_program_refuses_no_events_duplicates_overlaps_and_no_participants():
    with pytest.raises(ValueError, match="declares no event"):
        DemandResponseProgram("p", 1, ())
    with pytest.raises(ValueError, match="event ids twice: evt"):
        DemandResponseProgram("p", 1, (_event(), _event(start=200.0, end=260.0)))
    with pytest.raises(ValueError, match="'evt' and 'late' overlap"):
        DemandResponseProgram(
            "p", 1, (_event(), _event(event_id="late", start=100.0, end=160.0))
        )
    with pytest.raises(ValueError, match="at least one participant"):
        DemandResponseProgram("p", 0, (_event(),))
    program = DemandResponseProgram("p", 2, (_event(),))
    assert program.event("evt").duration_minutes == 60.0
    with pytest.raises(KeyError, match="no event 'other' \\(events: evt\\)"):
        program.event("other")


def test_payloads_use_openadr_names_and_the_simulated_window():
    program = DemandResponseProgram("winter", 3, (_event(),))
    payload = build_event_payload(program, program.events[0])
    assert payload["programID"] == "winter"
    assert payload["eventName"] == "evt"
    assert payload["duration"] == "PT60M"
    assert payload["intervals"][0]["payloads"][0] == {
        "type": CAPACITY_LIMIT_PAYLOAD,
        "values": [4.0],
    }
    assert (payload[ACTIVE_FROM_FIELD], payload[ACTIVE_UNTIL_FIELD]) == (60.0, 120.0)
    assert build_cancellation_payload(program.events[0]) == {"eventID": "evt"}
    assert build_opt_out_payload(program.events[0], "customer:1") == {
        "eventID": "evt",
        "clientName": "customer:1",
    }


def test_a_report_rounds_to_a_tenth_of_a_kwh_and_measures_back():
    event = _event()
    exact = build_report_payload(
        event=event,
        client_id="ven:1",
        client_name="customer:1",
        resource_name="home-1",
        delivered_kwh=3.14159,
    )
    near = build_report_payload(
        event=event,
        client_id="ven:1",
        client_name="customer:1",
        resource_name="home-1",
        delivered_kwh=3.14159 + 1e-12,
    )
    assert exact == near
    assert measure_reported_kwh(exact) == pytest.approx(3.1)
    assert {"clientID", "eventID", "clientName", "resources"} <= set(exact)


def test_the_study_program_loads_its_times_of_day_as_minutes():
    program = load_demand_response_program(STUDY)
    assert program.program_id == "winter-peak-program"
    assert program.participant_count == 20
    assert program.opt_out_below_indoor_c == 19.0
    midday = program.event("evt-midday-cancelled")
    assert (midday.notify_at, midday.start, midday.end, midday.cancel_at) == (
        600.0,
        780.0,
        900.0,
        720.0,
    )


def _declaring(**changes):
    project = load_project(STUDY / "project.yaml")
    program = project.raw["spec"]["inputs"]["drProgram"]
    program.update(changes)
    return project


def test_the_loader_refuses_unsupported_keys_and_malformed_times():
    with pytest.raises(ValueError, match="unsupported keys: homes \\(supported:"):
        load_demand_response_program(_declaring(homes=20))
    bad_time = _declaring()
    bad_time.raw["spec"]["inputs"]["drProgram"]["events"][0]["start"] = "25:00"
    with pytest.raises(ValueError, match=r"events\[0\]\.start must lie within one day"):
        load_demand_response_program(bad_time)
    sloppy = _declaring()
    sloppy.raw["spec"]["inputs"]["drProgram"]["events"][0]["notifyAt"] = "6:5"
    with pytest.raises(ValueError, match="must be a time of day 'HH:MM'"):
        load_demand_response_program(sloppy)
    end_of_day = _declaring()
    end_of_day.raw["spec"]["inputs"]["drProgram"]["events"][2]["end"] = "24:00"
    assert load_demand_response_program(end_of_day).events[2].end == 1440.0


def test_the_loader_locates_an_inconsistent_event_and_a_missing_input():
    inconsistent = _declaring()
    inconsistent.raw["spec"]["inputs"]["drProgram"]["events"][1]["cancelAt"] = "16:00"
    with pytest.raises(ValueError) as caught:
        load_demand_response_program(inconsistent)
    assert "spec.inputs.drProgram.events[1]" in str(caught.value)
    assert "between its notification and its end" in str(caught.value)
    with pytest.raises(ValueError, match="spec.inputs.nothing not found"):
        load_demand_response_program(STUDY, input_key="nothing")

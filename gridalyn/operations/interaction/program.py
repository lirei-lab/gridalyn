"""A demand-response program: its events, their windows, and their message payloads.

A study declares a program in ``spec.inputs.drProgram``, and
:func:`gridalyn.projects.model_inputs.load_demand_response_program` reads it
into a :class:`DemandResponseProgram`. Times are **simulated minutes** from the
start of the simulated day, the unit the ``dr_program`` protocol's deadlines use.

The ``build_*_payload`` helpers write the payloads the ``dr_program`` protocol
exchanges, with OpenADR 3.1.0 field names verbatim. Two payload *types* are
gridalyn's own, because OpenADR 3.1.0 defines its payload types in a
Definitions document and allows privately defined strings:
:data:`CAPACITY_LIMIT_PAYLOAD` (the household import cap an event orders) and
:data:`DELIVERED_REDUCTION_PAYLOAD` (the curtailment a VEN reports).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from gridalyn.operations.interaction.dr_program import (
    ACTIVE_FROM_FIELD,
    ACTIVE_UNTIL_FIELD,
)

#: Interval payload type of the household import cap an event orders, in kW.
CAPACITY_LIMIT_PAYLOAD = "flexint:IMPORT_CAPACITY_LIMIT_KW"

#: Interval payload type of the curtailment a VEN reports delivering, in kWh.
DELIVERED_REDUCTION_PAYLOAD = "flexint:DELIVERED_REDUCTION_KWH"

#: Resolution a reported reduction is rounded to, in kWh. A report's content is
#: its message id, and a lossy channel draws from that id: rounding keeps a
#: floating-point difference far below a meter's resolution from changing
#: whether the report arrives.
REPORTED_KWH_RESOLUTION = 0.1


def _finite_minute(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite simulated minute; found {value!r}")
    return number


@dataclass(frozen=True)
class DemandResponseEvent:
    """One event of a program.

    Attributes:
        event_id: Identifier, unique within its program.
        notify_at: Simulated minute the administrator sends the event.
        start: Simulated minute the event becomes active.
        end: Simulated minute the event completes; after ``start``.
        capacity_limit_kw: Import cap each participating household holds while
            the event is active.
        cancel_at: Simulated minute the administrator cancels the event, or
            ``None`` when it is not cancelled.
    """

    event_id: str
    notify_at: float
    start: float
    end: float
    capacity_limit_kw: float
    cancel_at: float | None = None

    def __post_init__(self) -> None:
        """Refuse a window that cannot happen.

        Raises:
            ValueError: Naming the event and the inconsistent fields.
        """
        label = f"event {self.event_id!r}"
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError(
                f"event_id must be a non-empty string; found {self.event_id!r}"
            )
        notify_at = _finite_minute(self.notify_at, f"{label} notify_at")
        start = _finite_minute(self.start, f"{label} start")
        end = _finite_minute(self.end, f"{label} end")
        if not notify_at <= start < end:
            raise ValueError(
                f"{label} must be notified no later than it starts and end after it "
                f"starts; found notify_at={notify_at}, start={start}, end={end}"
            )
        cap = float(self.capacity_limit_kw)
        if not math.isfinite(cap) or cap < 0.0:
            raise ValueError(
                f"{label} capacity_limit_kw must be a finite, non-negative kW value; "
                f"found {self.capacity_limit_kw!r}"
            )
        if self.cancel_at is not None:
            cancel_at = _finite_minute(self.cancel_at, f"{label} cancel_at")
            if not notify_at <= cancel_at < end:
                raise ValueError(
                    f"{label} can only be cancelled between its notification and its "
                    f"end; found cancel_at={cancel_at}, notify_at={notify_at}, "
                    f"end={end}"
                )

    @property
    def duration_minutes(self) -> float:
        """Return how long the event is active, in simulated minutes."""
        return float(self.end) - float(self.start)

    @property
    def is_cancelled(self) -> bool:
        """Return whether the administrator cancels the event."""
        return self.cancel_at is not None


@dataclass(frozen=True)
class DemandResponseProgram:
    """A program: its participants, its events and its participants' comfort limit.

    Attributes:
        program_id: OpenADR ``programID`` the events carry.
        participant_count: How many VENs the administrator sends each event to.
        events: The program's events; windows do not overlap.
        opt_out_below_indoor_c: Indoor temperature below which a participant
            opts out of an active event, or ``None`` when nobody opts out.
    """

    program_id: str
    participant_count: int
    events: tuple[DemandResponseEvent, ...]
    opt_out_below_indoor_c: float | None = None

    def __post_init__(self) -> None:
        """Refuse an empty program, duplicate event ids or overlapping windows.

        Raises:
            ValueError: Naming the program and what is inconsistent.
        """
        label = f"program {self.program_id!r}"
        if not isinstance(self.program_id, str) or not self.program_id:
            raise ValueError(
                f"program_id must be a non-empty string; found {self.program_id!r}"
            )
        if isinstance(self.participant_count, bool) or int(self.participant_count) < 1:
            raise ValueError(
                f"{label} needs at least one participant; found "
                f"{self.participant_count!r}"
            )
        if not self.events:
            raise ValueError(f"{label} declares no event")
        ids = [event.event_id for event in self.events]
        duplicated = sorted({event_id for event_id in ids if ids.count(event_id) > 1})
        if duplicated:
            raise ValueError(
                f"{label} declares event ids twice: {', '.join(duplicated)}"
            )
        ordered = sorted(self.events, key=lambda event: event.start)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start < earlier.end:
                raise ValueError(
                    f"{label}: events {earlier.event_id!r} and {later.event_id!r} "
                    "overlap; a household holds one cap at a time"
                )

    def event(self, event_id: str) -> DemandResponseEvent:
        """Return the event with this id.

        Raises:
            KeyError: No such event; the message lists the program's events.
        """
        for event in self.events:
            if event.event_id == event_id:
                return event
        known = ", ".join(event.event_id for event in self.events)
        raise KeyError(
            f"program {self.program_id!r} has no event {event_id!r} (events: {known})"
        )


def build_event_payload(
    program: DemandResponseProgram, event: DemandResponseEvent
) -> dict[str, Any]:
    """Build the OpenADR 3.1.0 ``event`` payload the administrator sends."""
    return {
        "programID": program.program_id,
        "eventName": event.event_id,
        "duration": f"PT{event.duration_minutes:g}M",
        "intervals": [
            {
                "id": 0,
                "payloads": [
                    {
                        "type": CAPACITY_LIMIT_PAYLOAD,
                        "values": [float(event.capacity_limit_kw)],
                    }
                ],
            }
        ],
        ACTIVE_FROM_FIELD: float(event.start),
        ACTIVE_UNTIL_FIELD: float(event.end),
    }


def build_cancellation_payload(event: DemandResponseEvent) -> dict[str, Any]:
    """Build the ``flexint:EventCancellation`` payload."""
    return {"eventID": event.event_id}


def build_opt_out_payload(
    event: DemandResponseEvent, client_name: str
) -> dict[str, Any]:
    """Build the ``flexint:OptOut`` payload a VEN sends."""
    return {"eventID": event.event_id, "clientName": client_name}


def build_report_payload(
    *,
    event: DemandResponseEvent,
    client_id: str,
    client_name: str,
    resource_name: str,
    delivered_kwh: float,
) -> dict[str, Any]:
    """Build the OpenADR 3.1.0 ``report`` payload a VEN sends when an event ends.

    The delivered reduction is rounded to :data:`REPORTED_KWH_RESOLUTION`.
    """
    steps = round(float(delivered_kwh) / REPORTED_KWH_RESOLUTION)
    reported = round(steps * REPORTED_KWH_RESOLUTION, 1)
    return {
        "clientID": client_id,
        "eventID": event.event_id,
        "clientName": client_name,
        "reportName": f"{event.event_id}:{client_id}",
        "resources": [
            {
                "resourceName": resource_name,
                "intervals": [
                    {
                        "id": 0,
                        "payloads": [
                            {"type": DELIVERED_REDUCTION_PAYLOAD, "values": [reported]}
                        ],
                    }
                ],
            }
        ],
    }


def measure_reported_kwh(payload: dict[str, Any]) -> float:
    """Return the reduction a ``report`` payload states, summed over its resources."""
    total = 0.0
    for resource in payload.get("resources", []):
        for interval in resource.get("intervals", []):
            for item in interval.get("payloads", []):
                if item.get("type") == DELIVERED_REDUCTION_PAYLOAD:
                    total += sum(float(value) for value in item.get("values", []))
    return total


__all__ = [
    "CAPACITY_LIMIT_PAYLOAD",
    "DELIVERED_REDUCTION_PAYLOAD",
    "REPORTED_KWH_RESOLUTION",
    "DemandResponseEvent",
    "DemandResponseProgram",
    "build_cancellation_payload",
    "build_event_payload",
    "build_opt_out_payload",
    "build_report_payload",
    "measure_reported_kwh",
]

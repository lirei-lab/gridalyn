"""One winter day of a demand-response program, run through the ``dr_program`` protocol.

Every home is one VEN (an ``active_customer``) running a Québec-calibrated
:class:`Building` and one level-2 :class:`EVCharger`. The program administrator
(OpenADR's business logic) sends each event to every home over the channel
model the study declares, and cancels the events it cancels. While an event is
active a home holds its import cap -- heating first, the charger gets what is
left -- and opts out when its indoor temperature falls below the program's
comfort limit. When an event ends, a home that curtailed reports what it
delivered.

**Two views, deliberately.** A conversation advances on *delivered* messages:
that is what the receiver knows. A home that decides to opt out stops
curtailing at once, whether or not its opt-out arrives -- the decision is the
home's own -- so a lost opt-out leaves the administrator counting on a
curtailment that is not happening. Both views are reported.

**Counterfactual baseline.** Every home is simulated twice from the same seeds,
once with no program, so the curtailment is the difference between the two. A
real VEN would estimate it from a baseline method.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.agents import (
    L2_MID_KW,
    Building,
    EVCharger,
    make_buildings,
)
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator
from gridalyn.operations.interaction import (
    AgentRef,
    Message,
    MessageBus,
    Performative,
    build_message,
)
from gridalyn.operations.interaction.program import (
    DemandResponseEvent,
    DemandResponseProgram,
    build_cancellation_payload,
    build_event_payload,
    build_opt_out_payload,
    build_report_payload,
    measure_reported_kwh,
)

STEP_MINUTES = 5
DAY_MINUTES = 1440
BURN_IN_HOURS = 6

#: The act each dr_program message performs.
_PERFORMATIVE: dict[str, Performative] = {
    "event": "inform",
    "flexint:EventCancellation": "cancel",
    "flexint:OptOut": "refuse",
    "report": "inform",
}

ADMINISTRATOR = AgentRef(
    agent_id="bl:program-administrator",
    party_id="utility",
    role="program_administrator",
)


def home_agent(index: int) -> AgentRef:
    """Return the VEN of home ``index``."""
    return AgentRef(
        agent_id=f"ven:home-{index:02d}",
        party_id=f"customer:home-{index:02d}",
        role="active_customer",
    )


def conversation_id(event: DemandResponseEvent, index: int) -> str:
    """Return the conversation of one event with one home."""
    return f"dr_program:{event.event_id}:home-{index:02d}"


@dataclass
class Home:
    """One all-electric home: its thermal envelope and its EV charger."""

    building: Building
    charger: EVCharger

    def step(
        self, *, t_out_c: float, minute: int, background_kw: float, cap_kw: float | None
    ) -> float:
        """Advance one step and return the home's import in kW."""
        row = self.building.step(
            t_out=t_out_c,
            minute_of_day=minute % DAY_MINUTES,
            p_bg_kw=background_kw,
            p_cap_kw=cap_kw,
            dt_min=float(STEP_MINUTES),
        )
        charger_cap = None if cap_kw is None else max(0.0, cap_kw - row["p_total_kw"])
        charge = self.charger.step(
            minute=minute,
            cls_active=cap_kw is not None,
            dynamic_p_cap_kw=charger_cap,
            dt=STEP_MINUTES,
        )
        return float(row["p_total_kw"]) + float(charge["p_ev_kw"])

    @property
    def indoor_c(self) -> float:
        """Return the indoor temperature after the last step."""
        return float(self.building.T_in)


def build_homes(count: int, seed: int) -> list[Home]:
    """Build ``count`` homes, reproducibly from ``seed``."""
    buildings = make_buildings(count, seed=seed)
    return [
        Home(
            building=building,
            charger=EVCharger(
                unit_id=index,
                n_evs=1,
                charger_kw=L2_MID_KW,
                rng=np.random.default_rng([seed, index]),
            ),
        )
        for index, building in enumerate(buildings)
    ]


def load_cold_day() -> pd.Series:
    """Return the coldest synthetic winter day's outdoor temperature, per step."""
    day = select_cold_day(download_tmy(source="synthetic"))
    return day["temp_air"].resample(f"{STEP_MINUTES}min").mean()


def generate_background_kw(
    t_out: pd.Series, count: int, seed: int
) -> tuple[np.ndarray, str]:
    """Return appliance background load per step and home, and the model that drew it."""
    generator = ParametricArxGenerator(random_seed=seed)
    generator.load()
    _, background = generator.generate(temp_out_series=t_out, n_houses=count)
    return np.asarray(background, dtype=float), str(generator.model_provenance)


def _burn_in(homes: list[Home], t_out: pd.Series, background: np.ndarray) -> None:
    first = float(t_out.iloc[0])
    steps = BURN_IN_HOURS * 60 // STEP_MINUTES
    for k in range(steps):
        minute = DAY_MINUTES - (steps - k) * STEP_MINUTES
        for index, home in enumerate(homes):
            home.building.step(
                t_out=first,
                minute_of_day=minute,
                p_bg_kw=float(background[k % len(background), index]),
                dt_min=float(STEP_MINUTES),
            )


@dataclass(frozen=True)
class ProgramDay:
    """What a simulated program day produced.

    Attributes:
        program: The program that ran.
        minutes: Simulated minute of each step.
        t_out_c: Outdoor temperature per step.
        baseline_kw: Import per step and home with no program.
        actual_kw: Import per step and home under the program.
        indoor_c: Indoor temperature per step and home under the program.
        baseline_indoor_c: Indoor temperature per step and home with no program.
        opted_out: Conversations whose home decided to opt out.
        reported: Conversations whose home sent a report.
        bus: The bus the day ran on: its log and its conversations.
        background_model: Which appliance-background model drew the load.
    """

    program: DemandResponseProgram
    minutes: np.ndarray
    t_out_c: np.ndarray
    baseline_kw: np.ndarray
    actual_kw: np.ndarray
    indoor_c: np.ndarray
    baseline_indoor_c: np.ndarray
    opted_out: frozenset[str]
    reported: frozenset[str]
    bus: MessageBus
    background_model: str


class _Day:
    def __init__(
        self,
        *,
        program: DemandResponseProgram,
        channel: Any,
        seed: int,
        t_out: pd.Series,
        background: np.ndarray,
    ) -> None:
        count = program.participant_count
        self.program = program
        self.t_out = t_out
        self.background = background
        self.minutes = np.arange(len(t_out)) * STEP_MINUTES
        self.baseline_homes = build_homes(count, seed)
        self.program_homes = build_homes(count, seed)
        _burn_in(self.baseline_homes, t_out, background)
        _burn_in(self.program_homes, t_out, background)
        self.bus = MessageBus(channel=channel)
        self.agents = [home_agent(index) for index in range(count)]
        self.baseline_kw = np.zeros((len(t_out), count))
        self.actual_kw = np.zeros((len(t_out), count))
        self.indoor_c = np.zeros((len(t_out), count))
        self.baseline_indoor_c = np.zeros((len(t_out), count))
        self.opted_out: set[str] = set()
        self.reported: set[str] = set()

    def _message(
        self,
        event: DemandResponseEvent,
        index: int,
        kind: str,
        sent_at: float,
        payload: dict[str, Any],
    ) -> Message:
        from_administrator = kind in ("event", "flexint:EventCancellation")
        agent = self.agents[index]
        return build_message(
            conversation_id=conversation_id(event, index),
            protocol="dr_program",
            message_type=kind,
            performative=_PERFORMATIVE[kind],
            sender=ADMINISTRATOR if from_administrator else agent,
            receiver=agent if from_administrator else ADMINISTRATOR,
            sent_at=sent_at,
            payload=payload,
        )

    def _administrator_sends(self, minute: int) -> None:
        for event in self.program.events:
            sends = [
                ("event", event.notify_at, build_event_payload(self.program, event))
            ]
            if event.cancel_at is not None:
                sends.append(
                    (
                        "flexint:EventCancellation",
                        event.cancel_at,
                        build_cancellation_payload(event),
                    )
                )
            for kind, at, payload in sends:
                if minute <= at < minute + STEP_MINUTES:
                    for index in range(self.program.participant_count):
                        self.bus.send(self._message(event, index, kind, at, payload))

    def _state(self, event: DemandResponseEvent, index: int) -> str | None:
        key = conversation_id(event, index)
        book = self.bus.conversations
        return book[key].state if key in book else None

    def _homes_decide(self, minute: int, filled: int) -> None:
        limit = self.program.opt_out_below_indoor_c
        for event in self.program.events:
            for index, agent in enumerate(self.agents):
                key = conversation_id(event, index)
                state = self._state(event, index)
                if key in self.opted_out:
                    continue
                if (
                    state == "active"
                    and limit is not None
                    and self.program_homes[index].indoor_c < limit
                ):
                    payload = build_opt_out_payload(event, agent.party_id)
                    self.bus.send(
                        self._message(event, index, "flexint:OptOut", minute, payload)
                    )
                    self.opted_out.add(key)
                elif state == "completed" and key not in self.reported:
                    self._report(event, index, minute, filled)

    def _report(
        self, event: DemandResponseEvent, index: int, minute: int, filled: int
    ) -> None:
        agent = self.agents[index]
        window = (self.minutes[:filled] >= event.start) & (
            self.minutes[:filled] < event.end
        )
        delivered = float(
            (self.baseline_kw[:filled, index] - self.actual_kw[:filled, index])[
                window
            ].sum()
        ) * (STEP_MINUTES / 60.0)
        payload = build_report_payload(
            event=event,
            client_id=agent.agent_id,
            client_name=agent.party_id,
            resource_name=f"home-{index:02d}",
            delivered_kwh=delivered,
        )
        self.bus.send(self._message(event, index, "report", minute, payload))
        self.reported.add(conversation_id(event, index))

    def _cap(self, index: int) -> float | None:
        for event in self.program.events:
            if (
                self._state(event, index) == "active"
                and conversation_id(event, index) not in self.opted_out
            ):
                return float(event.capacity_limit_kw)
        return None

    def _physics(self, k: int, minute: int) -> None:
        t_out_c = float(self.t_out.iloc[k])
        for index in range(self.program.participant_count):
            background = float(self.background[k, index])
            self.baseline_kw[k, index] = self.baseline_homes[index].step(
                t_out_c=t_out_c, minute=minute, background_kw=background, cap_kw=None
            )
            self.baseline_indoor_c[k, index] = self.baseline_homes[index].indoor_c
            home = self.program_homes[index]
            self.actual_kw[k, index] = home.step(
                t_out_c=t_out_c,
                minute=minute,
                background_kw=background,
                cap_kw=self._cap(index),
            )
            self.indoor_c[k, index] = home.indoor_c

    def run(self, background_model: str) -> ProgramDay:
        steps = len(self.t_out)
        for k in range(steps):
            minute = k * STEP_MINUTES
            self._administrator_sends(minute)
            self.bus.run_until(float(minute))
            self._homes_decide(minute, filled=k)
            self._physics(k, minute)
        self.bus.run_until(float(DAY_MINUTES))
        self._homes_decide(DAY_MINUTES, filled=steps)
        self.bus.drain()
        return ProgramDay(
            program=self.program,
            minutes=self.minutes,
            t_out_c=self.t_out.to_numpy(dtype=float),
            baseline_kw=self.baseline_kw,
            actual_kw=self.actual_kw,
            indoor_c=self.indoor_c,
            baseline_indoor_c=self.baseline_indoor_c,
            opted_out=frozenset(self.opted_out),
            reported=frozenset(self.reported),
            bus=self.bus,
            background_model=background_model,
        )


def simulate_program_day(
    *,
    program: DemandResponseProgram,
    channel: Any,
    seed: int,
    t_out: pd.Series | None = None,
) -> ProgramDay:
    """Simulate one day of ``program`` over ``channel``.

    Args:
        program: The program the administrator runs.
        channel: The channel model every message crosses.
        seed: The ``agents`` stream: home envelopes, EV sessions and appliance
            background all draw from it.
        t_out: Outdoor temperature per step; the coldest synthetic winter day
            when omitted.

    Returns:
        The day's load, temperatures, messages and conversations.
    """
    temperature = load_cold_day() if t_out is None else t_out
    background, model = generate_background_kw(
        temperature, program.participant_count, seed
    )
    day = _Day(
        program=program,
        channel=channel,
        seed=seed,
        t_out=temperature,
        background=background,
    )
    return day.run(model)


def _window(day: ProgramDay, event: DemandResponseEvent) -> np.ndarray:
    return (day.minutes >= event.start) & (day.minutes < event.end)


def _states(day: ProgramDay) -> dict[str, dict[str, int]]:
    book = day.bus.conversations
    states: dict[str, dict[str, int]] = {}
    for event in day.program.events:
        counts = states.setdefault(event.event_id, {})
        for index in range(day.program.participant_count):
            key = conversation_id(event, index)
            state = book[key].state if key in book else "never_notified"
            counts[state] = counts.get(state, 0) + 1
    return {
        event_id: dict(sorted(counts.items())) for event_id, counts in states.items()
    }


def _energy(day: ProgramDay) -> dict[str, float]:
    step_h = STEP_MINUTES / 60.0
    ordered = delivered = 0.0
    peak_baseline = peak_program = 0.0
    for event in day.program.events:
        if event.is_cancelled:
            continue
        window = _window(day, event)
        baseline = day.baseline_kw[window]
        actual = day.actual_kw[window]
        ordered += float(np.clip(baseline - event.capacity_limit_kw, 0.0, None).sum())
        delivered += float((baseline - actual).sum())
        peak_baseline = max(peak_baseline, float(baseline.sum(axis=1).max()))
        peak_program = max(peak_program, float(actual.sum(axis=1).max()))
    return {
        "ordered_kwh": ordered * step_h,
        "delivered_kwh": delivered * step_h,
        "delivery_ratio": delivered / ordered if ordered > 0 else 0.0,
        "peak_baseline_kw": peak_baseline,
        "peak_program_kw": peak_program,
    }


def summarize_program_day(day: ProgramDay) -> dict[str, Any]:
    """Reduce a program day to the summary the study's report carries."""
    log = day.bus.log
    states = _states(day)
    live = [event for event in day.program.events if not event.is_cancelled]
    delivered_reports = [
        entry.message
        for entry in log.delivered_in_order()
        if entry.message.message_type == "report"
    ]
    events_sent = [e for e in log.entries if e.message.message_type == "event"]
    opt_outs_delivered = sum(
        1
        for entry in log.delivered_in_order()
        if entry.message.message_type == "flexint:OptOut"
    )
    completed = sum(states[event.event_id].get("completed", 0) for event in live)
    cancelled_events = [event for event in day.program.events if event.is_cancelled]
    curtailed_despite_cancellation = sum(
        states[event.event_id].get("completed", 0)
        + states[event.event_id].get("opted_out", 0)
        for event in cancelled_events
    )
    return {
        "home_count": day.program.participant_count,
        "event_count": len(day.program.events),
        "cancelled_event_count": len(cancelled_events),
        "step_minutes": STEP_MINUTES,
        "message_count": len(log),
        "delivered_message_count": log.count("delivered"),
        "lost_message_count": log.count("lost"),
        "event_notification_delivery_rate": (
            sum(1 for entry in events_sent if entry.outcome == "delivered")
            / len(events_sent)
        ),
        "response_rate": completed / (len(live) * day.program.participant_count),
        "opt_out_decision_count": len(day.opted_out),
        "opt_out_delivered_count": opt_outs_delivered,
        "curtailed_despite_cancellation_count": curtailed_despite_cancellation,
        "report_count": len(delivered_reports),
        "reported_kwh": sum(
            measure_reported_kwh(message.payload) for message in delivered_reports
        ),
        "min_outdoor_c": float(day.t_out_c.min()),
        "conversation_states": states,
        **_comfort(day, live),
        **_energy(day),
    }


def _comfort(day: ProgramDay, live: list[DemandResponseEvent]) -> dict[str, Any]:
    # Measured on this study's seeds: 3 of 20 sampled homes cannot hold the
    # setpoint on the coldest synthetic day with no program at all (heaters of
    # 3.5-3.7 kW against 4.4-6.0 kW of loss). A raw indoor minimum would report
    # their cold as the program's; these two fields keep the causes apart.
    window = np.zeros(len(day.minutes), dtype=bool)
    for event in live:
        window |= _window(day, event)
    baseline_min = day.baseline_indoor_c[window].min(axis=0)
    program_min = day.indoor_c[window].min(axis=0)
    limit = day.program.opt_out_below_indoor_c
    return {
        "homes_below_comfort_without_program_count": (
            0 if limit is None else int((baseline_min < limit).sum())
        ),
        "max_program_indoor_drop_c": float((baseline_min - program_min).max()),
    }

"""Replay the curtailment mechanism as demand-response conversations (bd 4ky.10).

``apply_curtailment_contracts`` measures the mechanism as masks and totals: which
steps the real-time backstop curtails, how much energy each EV loses, how much of
it a day-ahead forecast called. This module states the same mechanism as the
messages it implies -- an operator publishing an event, each curtailed EV's VEN
reporting what it gave up -- through ``gridalyn.operations.interaction``'s
``dr_program`` protocol, so the flagship emits a message log the semantic graph's
``agent_interaction`` capability can read.

It changes no number the study pins, by construction: it reads the artifacts the
curtailment stage reads, computes nothing that stage publishes, and writes only
its own files.

**Where it replays.** On the declared adoption grid
(``congestionEvPerHomeGrid``, EVs per home), not on the 16-EV pool. The pool is
2.67 EVs per home on this 6-home feeder, above the <= ~2 EV/dwelling band the
calibration review adopted, and at ~1 EV/dwelling the feeder does not congest --
the study's verified result. A grid point larger than the pool is reported as not
representable, never truncated to the pool.

**The per-EV backstop is a pinned restatement.** ``simulate_curtailment``
computes each EV's cut at each step and keeps only the totals. Replaying needs the
cuts, and adding a return value to the module the byte-stable annual chain imports
is a change that chain would have to be re-sealed for. :func:`replay_fair_backstop`
therefore restates its loop and records the cuts; the study's tests pin every
aggregate it returns against ``simulate_curtailment``, so the two cannot drift.

**Time.** One message bus carries the whole replay, and a bus refuses a message
sent before its current time. Adoption point ``k`` therefore occupies the minutes
``[k * year, (k + 1) * year)``; its offset is recorded with it. Inside a point, a
minute is the annual step times the step width, the same axis the study's arrays
use.

**Notice.** A curtailment window whose steps the day-ahead forecast called is
published :data:`DAY_AHEAD_NOTICE_MINUTES` before it starts; one it did not call is
published when it starts, which is the backstop acting without notice. The notice
length moves timestamps only: which windows were called is the stage's own
definition, ``(forecast + EV aggregate) > limit``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from gridalyn.operations.interaction import (
    AgentRef,
    DemandResponseEvent,
    DemandResponseProgram,
    MessageBus,
    build_event_payload,
    build_message,
    build_report_payload,
)
from projects.ev_hosting_flex.scripts.config import DTYPE, ROUND_DECIMALS


def _config_int(name: str, value: object) -> int:
    """Return a study config value that must be an integer.

    The study reads its constants from YAML, so they arrive untyped. Checking the
    type once, here, keeps every call site typed and turns a config drift into a
    located error rather than a silent coercion.

    Args:
        name: The YAML key the value was read from.
        value: The value.

    Returns:
        The value, as an ``int``.

    Raises:
        ValueError: The value is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"study config {name} must be an integer; found {type(value).__name__}"
        )
    return value


#: The study's float dtype and rounding, typed once (see :func:`_config_int`).
_DTYPE = np.dtype(str(DTYPE))
_ROUND = _config_int("roundDecimals", ROUND_DECIMALS)

#: How long before a called window the operator publishes its event.
DAY_AHEAD_NOTICE_MINUTES = 24 * 60

#: The forecast error the study quotes its notice figures at
#: (``apply_curtailment_contracts`` summarizes ``planned_percent_sigma_1.5``).
HEADLINE_FORECAST_SIGMA = 1.5

#: A cut smaller than this is floating-point noise, the backstop's own threshold.
_CUT_EPSILON_KW = 1e-9

#: The operator publishing every event: the DSO acting as OpenADR business logic.
ADMINISTRATOR = AgentRef(
    agent_id="bl:feeder-operator",
    party_id="utility",
    role="program_administrator",
)


def ev_agent(index: int) -> AgentRef:
    """Return the VEN of EV ``index``, a site that answers events itself.

    Args:
        index: Position of the EV in the study's fleet array.

    Returns:
        The agent, acting for its own customer party.
    """
    return AgentRef(
        agent_id=f"ven:ev-{index:02d}",
        party_id=f"customer:ev-{index:02d}",
        role="active_customer",
    )


def replay_fair_backstop(
    base: np.ndarray,
    demand: np.ndarray,
    limit: np.ndarray,
    *,
    res_minutes: int,
) -> dict[str, Any]:
    """Run the full-enrollment fair backstop, keeping each EV's cut at each step.

    A restatement of ``_annual.simulate_curtailment`` with every EV enrolled and
    fair rotation on, written with the same operations in the same order so its
    totals are the original's. The study's tests pin them.

    Args:
        base: ``(horizon,)`` feeder base in kW.
        demand: ``(n_evs, horizon)`` per-EV demand in kW.
        limit: ``(horizon,)`` usable rating per step in kW.
        res_minutes: Step width in minutes.

    Returns:
        ``cuts_kw`` ``(n_evs, horizon)``, plus the original's
        ``curtailed_kwh_by_ev``, ``events_by_ev``, ``curtailed_steps`` and
        ``served_ev_kw``.

    Raises:
        ValueError: The arrays disagree on the horizon.
    """
    base = np.asarray(base, dtype=_DTYPE)
    demand = np.asarray(demand, dtype=_DTYPE)
    rating_t = np.asarray(limit, dtype=_DTYPE)
    n_evs, horizon = demand.shape
    if base.shape != (horizon,) or rating_t.shape != (horizon,):
        raise ValueError(
            f"replay_fair_backstop received base {base.shape} and limit "
            f"{rating_t.shape} for a {horizon}-step demand; all three must share "
            "the annual horizon"
        )
    hours_per_step = float(res_minutes) / 60.0
    enrolled = np.ones(n_evs, dtype=bool)
    curtailed = np.zeros(n_evs, dtype=_DTYPE)
    events = np.zeros(n_evs, dtype=int)
    curtailed_steps = np.zeros(horizon, dtype=bool)
    cuts = np.zeros((n_evs, horizon), dtype=np.float64)
    free_draw = demand[~enrolled, :].sum(axis=0)
    served_ev_kw = demand.sum(axis=0).astype(_DTYPE)
    for t in range(horizon):
        cap_t = float(rating_t[t])
        headroom = cap_t - (base[t] + free_draw[t])
        active = np.where(enrolled & (demand[:, t] > 1e-9))[0]
        if active.size == 0 or demand[active, t].sum() <= max(headroom, 0.0):
            continue
        curtailed_steps[t] = True
        order = active[np.argsort(-curtailed[active], kind="stable")]
        remaining = max(0.0, headroom)
        for ev in order:
            granted = min(float(demand[ev, t]), remaining)
            remaining -= granted
            cut_kw = float(demand[ev, t]) - granted
            if cut_kw > _CUT_EPSILON_KW:
                curtailed[ev] += cut_kw * hours_per_step
                events[ev] += 1
                served_ev_kw[t] -= cut_kw
                cuts[ev, t] = cut_kw
    return {
        "cuts_kw": cuts,
        "curtailed_kwh_by_ev": curtailed,
        "events_by_ev": events,
        "curtailed_steps": curtailed_steps,
        "served_ev_kw": served_ev_kw,
    }


def group_windows(steps: np.ndarray) -> list[tuple[int, int]]:
    """Return the ``[start, end)`` step ranges of each run of consecutive steps.

    Args:
        steps: ``(horizon,)`` boolean mask.

    Returns:
        The runs, in time order; empty when no step is set.
    """
    mask = np.asarray(steps, dtype=bool).astype(np.int8)
    pad = np.zeros(1, dtype=np.int8)
    edges = np.diff(np.concatenate((pad, mask, pad)))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends, strict=True)]


def resolve_adoption_points(
    grid: Sequence[float], homes: int, pool_size: int
) -> list[dict[str, Any]]:
    """Turn a grid of EVs per home into EV counts, marking what the pool cannot hold.

    Args:
        grid: Declared adoption levels, EVs per home.
        homes: Homes downstream of the study feeder.
        pool_size: EVs the study's fleet array carries.

    Returns:
        One entry per grid level, in grid order, with its EV count and whether
        the pool is large enough to replay it.

    Raises:
        ValueError: The feeder has no homes, or a level is negative.
    """
    if homes < 1:
        raise ValueError(
            f"resolve_adoption_points needs a feeder with homes; found {homes}"
        )
    points = []
    for level in grid:
        rho = float(level)
        if rho < 0.0:
            raise ValueError(
                f"adoption level {level!r} is negative; congestionEvPerHomeGrid "
                "holds EVs per home"
            )
        ev_count = int(round(rho * homes))
        points.append(
            {
                "evs_per_home": rho,
                "ev_count": ev_count,
                "representable": ev_count <= pool_size,
            }
        )
    return points


def _notice_quality(called: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    """Restate the stage's step-level notice figures for one adoption point."""
    n_actual = max(int(actual.sum()), 1)
    n_called = max(int(called.sum()), 1)
    return {
        "planned_percent": round(
            float((called & actual).sum()) / n_actual * 100.0, _ROUND
        ),
        "surprise_percent": round(
            float((~called & actual).sum()) / n_actual * 100.0, _ROUND
        ),
        "false_alarm_percent": round(
            float((called & ~actual).sum()) / n_called * 100.0, _ROUND
        ),
    }


def replay_adoption_point(
    bus: MessageBus,
    *,
    point_index: int,
    evs_per_home: float,
    ev_count: int,
    base: np.ndarray,
    pool: np.ndarray,
    limit: np.ndarray,
    forecast: np.ndarray,
    res_minutes: int,
    program_prefix: str,
) -> dict[str, Any]:
    """Replay one adoption level through ``dr_program`` and summarize it.

    Args:
        bus: The replay's message bus; its time must not pass this point's epoch.
        point_index: Position of the level on the grid; fixes its epoch.
        evs_per_home: The level, EVs per home.
        ev_count: EVs replayed, the first ``ev_count`` rows of ``pool``.
        base: ``(horizon,)`` feeder base in kW.
        pool: ``(pool_size, horizon)`` per-EV demand in kW.
        limit: ``(horizon,)`` usable rating per step in kW.
        forecast: ``(horizon,)`` day-ahead forecast of the base in kW.
        res_minutes: Step width in minutes.
        program_prefix: Namespace of the program ids this replay publishes.

    Returns:
        The level's summary: its epoch, what the backstop curtailed, how many
        windows were called ahead, and the conversations and messages it took.
    """
    horizon = int(np.asarray(base).shape[0])
    epoch_minutes = horizon * res_minutes
    offset = point_index * epoch_minutes
    demand = np.asarray(pool, dtype=_DTYPE)[:ev_count]
    hours_per_step = float(res_minutes) / 60.0
    summary: dict[str, Any] = {
        "evs_per_home": evs_per_home,
        "ev_count": ev_count,
        "representable": True,
        "epoch_offset_minutes": offset,
    }
    if ev_count == 0:
        actual = np.zeros(horizon, dtype=bool)
        called = np.zeros(horizon, dtype=bool)
        cuts = np.zeros((0, horizon), dtype=np.float64)
    else:
        backstop = replay_fair_backstop(base, demand, limit, res_minutes=res_minutes)
        actual = backstop["curtailed_steps"]
        called = (np.asarray(forecast, dtype=_DTYPE) + demand.sum(axis=0)) > np.asarray(
            limit, dtype=_DTYPE
        )
        cuts = backstop["cuts_kw"]
    windows = group_windows(actual)
    program_id = f"{program_prefix}:{evs_per_home:g}-ev-per-home"
    events: list[tuple[DemandResponseEvent, bool, list[tuple[int, float]]]] = []
    for number, (first, stop) in enumerate(windows):
        start = float(offset + first * res_minutes)
        end = float(offset + stop * res_minutes)
        notified = bool(called[first:stop].any())
        notify_at = (
            max(start - DAY_AHEAD_NOTICE_MINUTES, float(offset)) if notified else start
        )
        window_cuts = cuts[:, first:stop]
        cut_mask = window_cuts > _CUT_EPSILON_KW
        granted = demand[:, first:stop].astype(np.float64) - window_cuts
        tightest = float(granted[cut_mask].min()) if cut_mask.any() else 0.0
        participants = [
            (int(ev), float(window_cuts[ev].sum()) * hours_per_step)
            for ev in np.flatnonzero(cut_mask.any(axis=1))
        ]
        event = DemandResponseEvent(
            event_id=f"window-{number:04d}",
            notify_at=notify_at,
            start=start,
            end=end,
            capacity_limit_kw=round(max(tightest, 0.0), 1),
        )
        events.append((event, notified, participants))

    sends: list[tuple[float, int, str, str, dict[str, Any], AgentRef, AgentRef]] = []
    if events:
        program = DemandResponseProgram(
            program_id=program_id,
            participant_count=max(ev_count, 1),
            events=tuple(event for event, _, _ in events),
        )
        for event, _, participants in events:
            payload = build_event_payload(program, event)
            for ev, delivered_kwh in participants:
                agent = ev_agent(ev)
                key = f"dr_program:{program_id}:{event.event_id}:ev-{ev:02d}"
                sends.append(
                    (event.notify_at, 0, key, "event", payload, ADMINISTRATOR, agent)
                )
                report = build_report_payload(
                    event=event,
                    client_id=agent.agent_id,
                    client_name=agent.party_id,
                    resource_name=f"ev-{ev:02d}",
                    delivered_kwh=delivered_kwh,
                )
                sends.append(
                    (event.end, 1, key, "report", report, agent, ADMINISTRATOR)
                )
    sends.sort(key=lambda send: (send[0], send[1], send[2]))
    for sent_at, _, key, kind, payload, sender, receiver in sends:
        bus.run_until(sent_at)
        bus.send(
            build_message(
                conversation_id=key,
                protocol="dr_program",
                message_type=kind,
                performative="inform",
                sender=sender,
                receiver=receiver,
                sent_at=sent_at,
                payload=payload,
            )
        )
    bus.run_until(float(offset + epoch_minutes))

    notified_windows = sum(1 for _, notified, _ in events if notified)
    conversations = sum(len(participants) for _, _, participants in events)
    notified_conversations = sum(
        len(participants) for _, notified, participants in events if notified
    )
    summary.update(
        {
            "curtailed_steps": int(actual.sum()),
            "curtailed_kwh": round(
                float(cuts.sum()) * hours_per_step if cuts.size else 0.0,
                _ROUND,
            ),
            "curtailment_window_count": len(windows),
            "notified_window_count": notified_windows,
            "backstop_window_count": len(windows) - notified_windows,
            "conversation_count": conversations,
            "notified_conversation_share": (
                round(notified_conversations / conversations, _ROUND)
                if conversations
                else None
            ),
            "curtailed_ev_count": len(
                {ev for _, _, participants in events for ev, _ in participants}
            ),
            "message_count": len(sends),
            "notice_quality": _notice_quality(called, actual),
        }
    )
    return summary

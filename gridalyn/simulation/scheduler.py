"""A deterministic discrete-event scheduler in simulated time.

Agent interaction in gridalyn is asynchronous in *simulated* time and never in
wall-clock time: there is no ``asyncio``, no thread and no process pool here,
because concurrency would make the order of events -- and therefore every
result that depends on it -- a property of the machine rather than of the
seed. Measured 2026-09-11, before this module: the repository had no event
queue at all (0 uses of ``heapq``, ``sched``, ``asyncio`` or ``threading``).

**The ordering contract.** Events pop in ascending
``(time, priority, key, sequence)``:

* ``time`` -- simulated time, in whatever unit the caller schedules in (a step
  index, hours);
* ``priority`` -- lower first among events at the same time, so a protocol can
  say "deliveries before the step that reads them";
* ``key`` -- a stable identifier such as a message id, so two events at the
  same time and priority are ordered by *what* they are, not by which was
  scheduled first;
* ``sequence`` -- insertion order, the last tie-break, so two events never
  compare equal and never compare their payloads.

Simulated time only moves forward: scheduling before :attr:`EventScheduler.now`
raises. The scheduler never inspects a payload, which is what lets
``gridalyn.operations`` build message protocols on it without this layer
knowing what a message is.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Upper bound :meth:`EventScheduler.drain` applies by default, so a handler
#: that keeps scheduling events forever fails loudly instead of hanging a run.
DEFAULT_DRAIN_LIMIT = 1_000_000


def _require_finite(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite simulated time; found {value!r}")
    return number


@dataclass(frozen=True)
class ScheduledEvent:
    """One event waiting in, or popped from, an :class:`EventScheduler`.

    Attributes:
        time: Simulated time the event fires at.
        priority: Lower fires first among events at the same time.
        key: Stable identifier that breaks remaining ties, e.g. a message id.
        sequence: Insertion order; the final tie-break.
        payload: Opaque to the scheduler.
    """

    time: float
    priority: int
    key: str
    sequence: int
    payload: Any = field(default=None, compare=False)


class EventScheduler:
    """Order events by ``(time, priority, key, sequence)`` in simulated time."""

    def __init__(self, start_time: float = 0.0) -> None:
        """Start with no event scheduled, at ``start_time``.

        Args:
            start_time: Simulated time the scheduler starts at.

        Raises:
            ValueError: ``start_time`` is not finite.
        """
        self._now = _require_finite(start_time, "start_time")
        self._queue: list[tuple[float, int, str, int, ScheduledEvent]] = []
        self._sequence = 0

    @property
    def now(self) -> float:
        """Return the simulated time of the last event popped, or the start."""
        return self._now

    def __len__(self) -> int:
        """Return how many events are still scheduled."""
        return len(self._queue)

    def schedule(
        self,
        *,
        time: float,
        key: str,
        payload: Any = None,
        priority: int = 0,
    ) -> ScheduledEvent:
        """Schedule an event.

        Args:
            time: Simulated time the event fires at; not before :attr:`now`.
            key: Stable identifier used as the third ordering key.
            payload: Anything; never inspected.
            priority: Lower fires first among events at the same time.

        Returns:
            The scheduled event.

        Raises:
            ValueError: ``time`` is not finite or lies before :attr:`now`.
        """
        fires_at = _require_finite(time, "time")
        if fires_at < self._now:
            raise ValueError(
                f"cannot schedule event {key!r} at time {fires_at}, before the "
                f"scheduler's current time {self._now}; simulated time only "
                "moves forward"
            )
        event = ScheduledEvent(
            fires_at, int(priority), str(key), self._sequence, payload
        )
        self._sequence += 1
        heapq.heappush(
            self._queue,
            (event.time, event.priority, event.key, event.sequence, event),
        )
        return event

    def peek_time(self) -> float | None:
        """Return when the next event fires, or ``None`` when none is scheduled."""
        return self._queue[0][0] if self._queue else None

    def pop(self) -> ScheduledEvent:
        """Remove and return the next event, advancing :attr:`now` to its time.

        Raises:
            IndexError: No event is scheduled.
        """
        if not self._queue:
            raise IndexError("no event is scheduled")
        event = heapq.heappop(self._queue)[-1]
        self._now = event.time
        return event

    def run_until(self, time: float, handler: Callable[[ScheduledEvent], None]) -> int:
        """Handle, in order, every event that fires at or before ``time``.

        The handler may schedule further events; those that fire at or before
        ``time`` are handled in the same call. :attr:`now` ends at ``time``.

        Args:
            time: Simulated time to advance to.
            handler: Called once per event, in scheduling order.

        Returns:
            How many events were handled.

        Raises:
            ValueError: ``time`` is not finite or lies before :attr:`now`.
        """
        until = _require_finite(time, "time")
        if until < self._now:
            raise ValueError(
                f"cannot run until time {until}, before the scheduler's current "
                f"time {self._now}"
            )
        handled = 0
        while self._queue and self._queue[0][0] <= until:
            handler(self.pop())
            handled += 1
        self._now = until
        return handled

    def drain(
        self,
        handler: Callable[[ScheduledEvent], None],
        *,
        limit: int = DEFAULT_DRAIN_LIMIT,
    ) -> int:
        """Handle every scheduled event, including those handlers schedule.

        Args:
            handler: Called once per event, in scheduling order.
            limit: Most events to handle before concluding the handlers are
                scheduling forever.

        Returns:
            How many events were handled.

        Raises:
            RuntimeError: More than ``limit`` events were handled.
        """
        handled = 0
        while self._queue:
            if handled >= limit:
                raise RuntimeError(
                    f"drained {limit} events and {len(self._queue)} remain "
                    f"scheduled (next at time {self.peek_time()}); a handler is "
                    "probably rescheduling forever -- raise limit= if the run is "
                    "genuinely this long"
                )
            handler(self.pop())
            handled += 1
        return handled


__all__ = ["DEFAULT_DRAIN_LIMIT", "EventScheduler", "ScheduledEvent"]

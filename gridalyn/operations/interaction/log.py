"""The message log: what was sent, what arrived and when, as parquet that replays.

A :class:`MessageLog` holds one entry per message *sent*, in send order, with
its outcome: ``delivered`` (with the simulated time and the global order it
arrived in), ``lost``, or ``in_flight`` when the run stopped before it arrived.

**Replay is the check.** :func:`build_conversation_book` rebuilds every
conversation from the delivered entries alone, in delivery order, re-deriving
each message id from its content and re-validating every transition. A log
that replays to the states a run reported is a faithful record of that run;
:func:`write_interaction_report` performs exactly that check on the file it
references, and reports any difference as a validation error.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import pandas as pd

from gridalyn.foundation.platform.reports import (
    ReportMetadata,
    file_reference,
    write_report,
)
from gridalyn.operations.interaction.conversations import (
    ConversationBook,
    resolve_protocol,
)
from gridalyn.operations.interaction.messages import MESSAGE_RECORD_FIELDS, Message
from gridalyn.operations.vocabulary import _parse_term
from gridalyn.simulation.channels import ChannelModelDescriptor

LogOutcome = Literal["delivered", "lost", "in_flight"]
LOG_OUTCOMES: tuple[LogOutcome, ...] = get_args(LogOutcome)

#: Columns of a message-log frame, in order.
MESSAGE_LOG_COLUMNS: tuple[str, ...] = (
    "sequence",
    *MESSAGE_RECORD_FIELDS,
    "outcome",
    "delivered_at",
    "delivery_index",
)


@dataclass(frozen=True)
class LogEntry:
    """One sent message and what became of it.

    Attributes:
        sequence: Position in send order, from 0.
        message: The message.
        outcome: ``delivered``, ``lost`` or ``in_flight``.
        delivered_at: Simulated arrival time; only for a delivered message.
        delivery_index: Position in arrival order across the whole log, from 0;
            only for a delivered message.
    """

    sequence: int
    message: Message
    outcome: LogOutcome
    delivered_at: float | None = None
    delivery_index: int | None = None

    def __post_init__(self) -> None:
        """Refuse an outcome that disagrees with the delivery fields.

        Raises:
            ValueError: The outcome is unknown, a delivered entry lacks its time
                or index or arrives before it was sent, or an undelivered entry
                carries either.
        """
        _parse_term(self.outcome, LOG_OUTCOMES, "outcome")
        label = f"log entry {self.sequence} ({self.message.message_id})"
        if self.outcome != "delivered":
            if self.delivered_at is not None or self.delivery_index is not None:
                raise ValueError(
                    f"{label} is {self.outcome} but carries a delivery time or index"
                )
            return
        if self.delivered_at is None or self.delivery_index is None:
            raise ValueError(f"{label} is delivered but lacks delivered_at or index")
        if self.delivered_at < self.message.sent_at:
            raise ValueError(
                f"{label} is delivered at {self.delivered_at}, before it was sent "
                f"at {self.message.sent_at}"
            )

    def to_record(self) -> dict[str, Any]:
        """Return the entry as one row in :data:`MESSAGE_LOG_COLUMNS`."""
        return {
            "sequence": self.sequence,
            **self.message.to_record(),
            "outcome": self.outcome,
            "delivered_at": (
                math.nan if self.delivered_at is None else self.delivered_at
            ),
            "delivery_index": (
                -1 if self.delivery_index is None else self.delivery_index
            ),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> LogEntry:
        """Rebuild an entry from a row :meth:`to_record` wrote.

        Raises:
            ValueError: The row is not a valid entry, or its message id does not
                match its content.
        """
        delivered_at = float(record["delivered_at"])
        delivery_index = int(record["delivery_index"])
        return cls(
            sequence=int(record["sequence"]),
            message=Message.from_record(record),
            outcome=_parse_term(record["outcome"], LOG_OUTCOMES, "outcome"),
            delivered_at=None if math.isnan(delivered_at) else delivered_at,
            delivery_index=None if delivery_index < 0 else delivery_index,
        )


@dataclass(frozen=True)
class MessageLog:
    """Every message a run sent, in send order.

    Attributes:
        entries: One entry per message sent.
    """

    entries: tuple[LogEntry, ...] = ()

    def __post_init__(self) -> None:
        """Refuse entries out of send order, or a broken arrival order.

        Raises:
            ValueError: Sequences are not ``0..n-1`` in order, delivery indices
                do not number the delivered entries ``0..k-1``, or arrival
                times decrease along the arrival order.
        """
        for position, entry in enumerate(self.entries):
            if entry.sequence != position:
                raise ValueError(
                    f"message log entry at position {position} has sequence "
                    f"{entry.sequence}; entries are numbered in send order from 0"
                )
        delivered = self.delivered_in_order()
        indices = [entry.delivery_index for entry in delivered]
        if indices != list(range(len(delivered))):
            raise ValueError(
                f"delivery indices must number the {len(delivered)} delivered "
                f"messages 0..{len(delivered) - 1} once each; found {indices}"
            )
        for earlier, later in zip(delivered, delivered[1:], strict=False):
            if (later.delivered_at or 0.0) < (earlier.delivered_at or 0.0):
                raise ValueError(
                    f"message {later.message.message_id} arrives at "
                    f"{later.delivered_at}, after message "
                    f"{earlier.message.message_id} in arrival order but earlier in "
                    f"time ({earlier.delivered_at})"
                )

    def __len__(self) -> int:
        """Return how many messages were sent."""
        return len(self.entries)

    def delivered_in_order(self) -> tuple[LogEntry, ...]:
        """Return the delivered entries in arrival order."""
        delivered = [entry for entry in self.entries if entry.outcome == "delivered"]
        return tuple(sorted(delivered, key=lambda entry: entry.delivery_index or 0))

    def count(self, outcome: LogOutcome) -> int:
        """Return how many entries have this outcome."""
        return sum(1 for entry in self.entries if entry.outcome == outcome)

    def to_frame(self) -> pd.DataFrame:
        """Return the log as a frame in :data:`MESSAGE_LOG_COLUMNS`."""
        frame = pd.DataFrame(
            [entry.to_record() for entry in self.entries],
            columns=list(MESSAGE_LOG_COLUMNS),
        )
        return frame.astype(
            {
                "sequence": "int64",
                "sent_at": "float64",
                "delivered_at": "float64",
                "delivery_index": "int64",
            }
        )

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> MessageLog:
        """Rebuild a log from a frame :meth:`to_frame` produced.

        Raises:
            ValueError: A column is missing, or a row is invalid; the message
                names the row.
        """
        missing = [name for name in MESSAGE_LOG_COLUMNS if name not in frame.columns]
        if missing:
            present = ", ".join(map(str, frame.columns)) or "none"
            raise ValueError(
                f"message log frame is missing column(s) {', '.join(missing)} "
                f"(present: {present})"
            )
        entries = []
        for position, row in enumerate(
            frame[list(MESSAGE_LOG_COLUMNS)].to_dict("records")
        ):
            try:
                entries.append(LogEntry.from_record(row))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"message log row {position}: {exc}") from exc
        return cls(tuple(entries))


def build_conversation_book(
    log: MessageLog, *, until: float | None = None
) -> ConversationBook:
    """Replay a log's delivered messages, in arrival order, into conversations.

    Args:
        log: The log to replay.
        until: Simulated time to advance every conversation to afterwards, so
            deadlines that passed after the last message fire; pass the time the
            run ended at.

    Returns:
        The conversations, as the run's receivers saw them.

    Raises:
        ValueError: A delivered message is refused by its conversation; the
            message is the conversation's located refusal.
    """
    book = ConversationBook()
    for entry in log.delivered_in_order():
        book.accept(entry.message, at=entry.delivered_at)
    if until is not None:
        book.advance_to(until)
    return book


def summarize_interaction(log: MessageLog, book: ConversationBook) -> dict[str, Any]:
    """Reduce a log and its conversations to a report summary.

    Returns:
        Message counts by outcome, conversation counts, how many conversations
        are still open (not in a terminal state), and the number of
        conversations in each state, per protocol.
    """
    states: dict[str, dict[str, int]] = {}
    open_count = 0
    for key in book:
        conversation = book[key]
        per_protocol = states.setdefault(conversation.protocol.protocol_id, {})
        per_protocol[conversation.state] = per_protocol.get(conversation.state, 0) + 1
        open_count += 0 if conversation.is_terminal else 1
    return {
        "message_count": len(log),
        "delivered_message_count": log.count("delivered"),
        "lost_message_count": log.count("lost"),
        "in_flight_message_count": log.count("in_flight"),
        "conversation_count": len(book),
        "open_conversation_count": open_count,
        "conversation_states": {
            protocol: dict(sorted(counts.items()))
            for protocol, counts in sorted(states.items())
        },
    }


def write_message_log(path: Path | str, log: MessageLog) -> Path:
    """Write a message log as parquet.

    Returns:
        The path written.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    log.to_frame().to_parquet(target, index=False)
    return target


def load_message_log(path: Path | str) -> MessageLog:
    """Load a message log written by :func:`write_message_log`.

    Raises:
        FileNotFoundError: No file exists at ``path``.
        ValueError: The file is not a valid message log.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"message log not found: {source}; write one with write_message_log"
        )
    return MessageLog.from_frame(pd.read_parquet(source))


def _replay_differences(
    live: ConversationBook, replayed: ConversationBook
) -> list[str]:
    errors = []
    for key in sorted(set(live) | set(replayed)):
        if key not in live or key not in replayed:
            where = "the run" if key in live else "the replayed log"
            errors.append(f"conversation {key!r} exists only in {where}")
        elif live[key].steps != replayed[key].steps:
            errors.append(
                f"conversation {key!r} ends {live[key].state!r} after "
                f"{len(live[key].steps)} step(s) in the run, but "
                f"{replayed[key].state!r} after {len(replayed[key].steps)} when the "
                "written log is replayed"
            )
    return errors


def write_interaction_report(
    path: Path | str,
    *,
    log: MessageLog,
    book: ConversationBook,
    log_path: Path | str,
    metadata: ReportMetadata,
    until: float | None = None,
    channel: ChannelModelDescriptor | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Write the governed report of an interaction run, checked by replay.

    The report references the parquet log at ``log_path``. Before writing, it
    loads that file and replays it: a file that is not the log passed, or that
    replays to different conversations than ``book``, makes the report's
    ``validation.valid`` false with one error per difference.

    ``inputs`` records each protocol the log uses (its whole state machine),
    the channel model, and ``until``.

    Args:
        path: Where to write the report JSON.
        log: The run's message log.
        book: The run's conversations.
        log_path: Where ``log`` was written with :func:`write_message_log`.
        metadata: Report identity.
        until: Simulated time the run ended at; replay advances to it.
        channel: The channel model the run used.
        root: Root that artifact paths are recorded relative to.

    Returns:
        The written report payload, as :func:`write_report` returns it.

    Raises:
        FileNotFoundError: ``log_path`` does not exist.
    """
    written = load_message_log(log_path)
    errors = []
    if written.entries != log.entries:
        errors.append(f"the log at {log_path} is not the log of this run")
    try:
        replayed = build_conversation_book(written, until=until)
        errors.extend(_replay_differences(book, replayed))
    except ValueError as exc:
        errors.append(f"the log at {log_path} does not replay: {exc}")
    in_flight = log.count("in_flight")
    warnings = (
        [f"{in_flight} message(s) were still in flight; they are logged, not replayed"]
        if in_flight
        else []
    )
    protocols = sorted({entry.message.protocol for entry in log.entries})
    return write_report(
        path,
        metadata=metadata,
        inputs=[
            *(
                {"input": "protocol", **resolve_protocol(key).as_dict()}
                for key in protocols
            ),
            {
                "input": "channel_model",
                "descriptor": channel.as_dict() if channel is not None else None,
            },
            {"input": "horizon", "until": until},
        ],
        artifacts=[file_reference(log_path, root)],
        summary=summarize_interaction(log, book),
        validation={"valid": not errors, "errors": errors, "warnings": warnings},
    )


__all__ = [
    "LOG_OUTCOMES",
    "MESSAGE_LOG_COLUMNS",
    "LogEntry",
    "LogOutcome",
    "MessageLog",
    "build_conversation_book",
    "load_message_log",
    "summarize_interaction",
    "write_interaction_report",
    "write_message_log",
]

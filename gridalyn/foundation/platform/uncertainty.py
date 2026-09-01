"""Uncertainty estimates carried alongside a report's headline numbers.

The platform's stated value is that a study's headline numbers are reported
*with their uncertainty*. A study that runs Monte Carlo already has the
distribution; without somewhere contractual to put it, the distribution is
discarded at report time and the summary carries one realization as if it were
the answer.

This module is that place. It is deliberately small and deliberately strict:
an uncertainty block that names a metric the summary does not carry, or whose
point estimate falls outside its own interval, is rejected rather than stored.
An empty block is rejected too -- the field exists to hold a number a study can
defend, not to be present.

Foundation is stdlib-only, so the quantile is computed here rather than through
numpy; the linear-interpolation convention matches ``numpy.percentile``'s
default so a study's own numbers agree with what it reports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: How an interval was arrived at. ``monte_carlo`` and ``bootstrap`` are
#: resampling methods over a study's own draws; ``empirical_quantile`` covers a
#: distribution observed rather than sampled; ``analytic`` covers a closed-form
#: bound. A study that cannot name one of these does not yet have uncertainty.
METHODS: tuple[str, ...] = (
    "monte_carlo",
    "bootstrap",
    "empirical_quantile",
    "analytic",
)

#: The minimum number of draws an interval may be claimed from. Two is not
#: enough to be useful, but it is the point below which an "interval" is not an
#: interval at all.
MIN_DRAWS = 2


def _as_number(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not a real number.

    Returning the converted value rather than a bool keeps the type narrowed
    for callers: ``bool`` is excluded because ``isinstance(True, int)`` holds
    and a flag is not a measurement.

    Args:
        value: The candidate read out of a report payload.

    Returns:
        The value as a float, or ``None`` if it is not a non-bool number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class UncertaintyEstimate:
    """One headline number reported with the interval it was drawn from.

    Attributes:
        metric: The ``summary`` key this estimate qualifies. It must exist in
            the summary, so an estimate cannot describe a number the report
            does not carry.
        method: How the interval was obtained; one of :data:`METHODS`.
        n: How many draws, realizations or samples back the interval.
        point: The headline value itself, as the summary reports it.
        low: Lower bound of the interval.
        high: Upper bound of the interval.
        level: Coverage of the interval, strictly between 0 and 1 (0.9 for a
            90% interval).
        seed: The seed the draws came from, when the study fixes one. This is
            what makes the interval reproducible rather than merely reported.
        note: Optional free text, e.g. which axis the draws vary.
    """

    metric: str
    method: str
    n: int
    point: float
    low: float
    high: float
    level: float
    seed: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form carried in a report.

        Returns:
            A mapping with the interval as a two-element list, matching the
            shape :func:`validate_uncertainty` checks.
        """
        payload: dict[str, Any] = {
            "method": self.method,
            "n": self.n,
            "point": self.point,
            "interval": [self.low, self.high],
            "level": self.level,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.note:
            payload["note"] = self.note
        return payload


def percentile(samples: Sequence[float], fraction: float) -> float:
    """Return the linear-interpolated percentile of ``samples``.

    Matches ``numpy.percentile``'s default (``linear``) convention so a study
    computing its own quantiles with numpy reports the same numbers.

    Args:
        samples: The draws, in any order. Must be non-empty.
        fraction: The quantile to take, between 0 and 1 inclusive.

    Returns:
        The interpolated quantile.

    Raises:
        ValueError: If ``samples`` is empty or ``fraction`` is out of range.
    """
    if not samples:
        raise ValueError("percentile requires at least one sample, got none")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within [0, 1], got {fraction}")
    ordered = sorted(float(value) for value in samples)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def estimate_from_samples(
    metric: str,
    samples: Sequence[float],
    *,
    level: float = 0.90,
    method: str = "monte_carlo",
    point: float | None = None,
    seed: int | None = None,
    note: str = "",
) -> UncertaintyEstimate:
    """Build an estimate from a study's own draws.

    Args:
        metric: The ``summary`` key being qualified.
        samples: The realizations the headline number was drawn from.
        level: Interval coverage, strictly between 0 and 1.
        method: How the draws were produced; one of :data:`METHODS`.
        point: The headline value. Defaults to the sample median, which is what
            a report should carry when one realization was previously reported
            as if it were the answer.
        seed: The seed the draws came from.
        note: Optional free text recording which axis the draws vary.

    Returns:
        The estimate, with the interval taken at the symmetric tails of
        ``level``.

    Raises:
        ValueError: If fewer than :data:`MIN_DRAWS` samples are given, the
            method is unknown, or the level is out of range; the message names
            the valid set.
    """
    if method not in METHODS:
        raise ValueError(
            f"unknown uncertainty method {method!r} (known: {', '.join(METHODS)})"
        )
    if len(samples) < MIN_DRAWS:
        raise ValueError(
            f"{metric}: an interval needs at least {MIN_DRAWS} draws, "
            f"got {len(samples)}"
        )
    if not 0.0 < level < 1.0:
        raise ValueError(f"{metric}: level must be within (0, 1), got {level}")
    tail = (1.0 - level) / 2.0
    low = percentile(samples, tail)
    high = percentile(samples, 1.0 - tail)
    centre = percentile(samples, 0.5) if point is None else float(point)
    # A supplied point outside its own interval is a real contradiction and is
    # reported as such by validate_uncertainty; do not silently clamp it here.
    return UncertaintyEstimate(
        metric=metric,
        method=method,
        n=len(samples),
        point=centre,
        low=low,
        high=high,
        level=level,
        seed=seed,
        note=note,
    )


def build_uncertainty(
    estimates: Sequence[UncertaintyEstimate],
) -> dict[str, dict[str, Any]]:
    """Assemble estimates into the block a report carries.

    Args:
        estimates: The estimates to serialize, one per headline metric.

    Returns:
        A mapping of metric name to its serialized estimate.

    Raises:
        ValueError: If ``estimates`` is empty, or two estimates name the same
            metric; an empty block is not a report with uncertainty.
    """
    if not estimates:
        raise ValueError(
            "build_uncertainty requires at least one estimate; omit the "
            "uncertainty block entirely rather than emitting an empty one"
        )
    block: dict[str, dict[str, Any]] = {}
    for estimate in estimates:
        if estimate.metric in block:
            raise ValueError(f"duplicate uncertainty estimate for {estimate.metric!r}")
        block[estimate.metric] = estimate.to_dict()
    return block


def _validate_interval(where: str, entry: Mapping[str, Any]) -> list[str]:
    """Check one estimate's interval and the point it is meant to contain.

    Args:
        where: The dotted location of this estimate, for the messages.
        entry: The serialized estimate.

    Returns:
        Error strings, empty when the interval and point are coherent.
    """
    interval = entry.get("interval")
    if (
        not isinstance(interval, Sequence)
        or isinstance(interval, (str, bytes))
        or len(interval) != 2
    ):
        return [f"{where}.interval must be a [low, high] pair, got {interval!r}"]
    raw_low, raw_high = interval
    low, high = _as_number(raw_low), _as_number(raw_high)
    if low is None or high is None:
        return [f"{where}.interval bounds must be numbers, got {interval!r}"]
    if not math.isfinite(low) or not math.isfinite(high):
        return [f"{where}.interval bounds must be finite, got {interval!r}"]
    if low > high:
        return [f"{where}.interval is inverted: low {low} > high {high}"]

    raw_point = entry.get("point")
    point = _as_number(raw_point)
    if point is None:
        return [f"{where}.point must be a number, got {raw_point!r}"]
    if not low <= point <= high:
        return [
            f"{where}.point {point} falls outside its own interval "
            f"[{low}, {high}] -- the headline number and the interval "
            "reported with it disagree"
        ]
    return []


def _validate_against_summary(
    metric: str, where: str, entry: Mapping[str, Any], summary: Mapping[str, Any]
) -> list[str]:
    """Check that an estimate qualifies a number the summary actually carries.

    Args:
        metric: The summary key this estimate names.
        where: The dotted location of this estimate, for the messages.
        entry: The serialized estimate.
        summary: The report's summary.

    Returns:
        Error strings, empty when the estimate matches the summary.
    """
    if metric not in summary:
        keys = ", ".join(sorted(map(str, summary))) or "none"
        return [
            f"{where} qualifies a metric the summary does not carry "
            f"(summary keys: {keys})"
        ]
    raw_carried = summary[metric]
    raw_point = entry.get("point")
    carried, point = _as_number(raw_carried), _as_number(raw_point)
    if carried is None or point is None:
        return []
    if math.isclose(carried, point, rel_tol=1e-9, abs_tol=1e-9):
        return []

    return [
        f"{where}.point {raw_point!r} disagrees with summary.{metric} "
        f"{raw_carried!r} "
        "-- the interval must qualify the number the report actually carries"
    ]


def _validate_entry(
    metric: str, entry: Any, summary: Mapping[str, Any] | None
) -> list[str]:
    """Check one serialized estimate.

    Args:
        metric: The summary key this estimate names.
        entry: The candidate estimate.
        summary: The report's summary, when available.

    Returns:
        Error strings, empty when the estimate is well-formed.
    """
    where = f"uncertainty.{metric}"
    if not isinstance(entry, Mapping):
        return [f"{where} must be an object, found {type(entry).__name__}"]

    errors: list[str] = []
    method = entry.get("method")
    if method not in METHODS:
        errors.append(f"{where}.method is {method!r} (known: {', '.join(METHODS)})")
    count = entry.get("n")
    if not isinstance(count, int) or isinstance(count, bool) or count < MIN_DRAWS:
        errors.append(f"{where}.n must be an integer >= {MIN_DRAWS}, got {count!r}")
    raw_level = entry.get("level")
    level = _as_number(raw_level)
    if level is None or not 0.0 < level < 1.0:
        errors.append(f"{where}.level must be within (0, 1), got {raw_level!r}")
    errors.extend(_validate_interval(where, entry))
    if summary is not None:
        errors.extend(_validate_against_summary(metric, where, entry, summary))
    return errors


def validate_uncertainty(
    block: Any, summary: Mapping[str, Any] | None = None
) -> list[str]:
    """Return contract errors for an uncertainty block.

    Args:
        block: The candidate uncertainty block from a report payload.
        summary: The report's summary, when available. Every metric the block
            names must be a key of it, which is what stops the block from
            describing numbers the report does not carry.

    Returns:
        A list of error strings, empty when the block is well-formed.
    """
    if not isinstance(block, Mapping):
        return [f"uncertainty must be an object, found {type(block).__name__}"]
    if not block:
        return ["uncertainty must not be empty; omit the field instead"]
    errors: list[str] = []
    for metric, entry in block.items():
        errors.extend(_validate_entry(metric, entry, summary))
    return errors

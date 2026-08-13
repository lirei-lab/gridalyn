"""At-scale operator proof of the SHIPPED measured-state ingest path.

This tool exercises :func:`gridalyn.twin.observation.read_measured_observations`
-- the shipped producer, unmodified -- against ``datasets/hq``'s real measured
time axis (35,041 15-min instants spanning 2018-04-03 to 2019-04-03) and real
entity set (1000 homes), in ONE whole-frame call, and emits a JSON evidence
record for the ``measured-state-ingest`` verification receipt.

**What this proof demonstrates.** The shipped ingest path processes a
year-at-scale tidy frame -- real measured timestamps, real measured entities,
an explicitly declared operator-written join -- into one
``NetworkObservation(provenance="measured")`` per instant with ``as_of``
stamped from the datum, within measured time and memory.

**What this proof does NOT demonstrate: real voltage data.** The HQ dataset
carries per-home electrical power (kW) and weather; it has NO voltage channel,
and ``NetworkObservation``'s only measured-mappable field is ``bus_voltage_pu``
(finding M1). Relabeling kW as voltage would fabricate data, so the voltage
VALUES here are SYNTHESIZED -- ``1.0`` plus a small deterministic variation
from ``numpy.random.default_rng(42)`` -- and the evidence output says so. This
is a mechanics-at-scale proof on real measured timestamps and entities, never
a claim of real voltage measurements. Value-level correctness is proven
separately by the CI-visible fixture tests in ``tests/test_measured_ingest.py``.

**How the time axis is read (finding M1b).** The stored index is a naive,
perfectly uniform 15-min grid with no DST fold: localizing it to
``America/Toronto`` raises ``AmbiguousTimeError`` at the 2018-11-04 repeated
hour, and choosing ``ambiguous=``/``nonexistent=`` policies would manufacture
the very offsets the receipt would then claim to have observed. The proof
therefore reads the axis with ``tz_localize("UTC")`` -- lossless and
policy-free -- and the receipt makes NO DST claim.

**The join is declared, not inferred.** HQ's 1000 anonymous ordinal columns
carry no key into the twin's bus namespace, so this script DECLARES a demo
mapping ``hq_home_{col} -> bus_{col}`` as operator-written configuration --
exactly the ``EntityJoin`` posture the shipped path requires -- and states as
much in the evidence.

Usage::

    .venv/bin/python tools/measured_ingest_proof.py                # full year
    .venv/bin/python tools/measured_ingest_proof.py --entities 5 --days 1
    .venv/bin/python tools/measured_ingest_proof.py --out proof.json
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.twin.observation import EntityJoin, read_measured_observations

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the operator-local HQ export lives. Gitignored; never ships.
DEFAULT_HQ_DIR = REPO_ROOT / "datasets" / "hq"

#: The HDF5 file carrying the real measured time axis and entity columns.
CONSUMPTION_FILE = "consumption.h5"

#: 15-min resolution: rows per calendar day on the stored uniform grid.
ROWS_PER_DAY = 96

#: A request for this many days (or more) takes the ENTIRE stored axis --
#: 365 days of 96 rows plus the closing 2019-04-03 00:00 instant (35,041).
FULL_AXIS_DAYS = 365

#: The M1 disclosure, embedded verbatim in the evidence output.
SYNTHESIS_DISCLOSURE = (
    "voltage VALUES are SYNTHESIZED (1.0 + small deterministic variation, "
    "numpy.random.default_rng(42)): datasets/hq carries per-home consumption/"
    "heating kW and weather, NO voltage channel, and NetworkObservation's "
    "measured-mappable field is bus_voltage_pu -- relabeling kW as voltage "
    "would fabricate data. This proof claims mechanics-at-scale on real "
    "measured timestamps and entities, never real voltage data."
)

#: The M1b disclosure, embedded verbatim in the evidence output.
AXIS_READING_DISCLOSURE = (
    "naive uniform grid read as UTC; no DST fold present in the data -- "
    "tz_localize('America/Toronto') raises AmbiguousTimeError and choosing "
    "offset policies would manufacture evidence, so the axis is localized "
    "with tz_localize('UTC') (lossless, policy-free) and no DST claim is made"
)

#: The join disclosure, embedded verbatim in the evidence output.
JOIN_DISCLOSURE = (
    "the entity-to-bus join is operator-declared demo configuration written "
    "by this script (EntityJoin.from_mapping, hq_home_{col} -> bus_{col}); "
    "HQ's anonymous ordinal columns carry no key into the twin's bus "
    "namespace, so nothing is inferred"
)


def _load_measured_frame(hq_dir: Path, entities: int, days: int) -> pd.DataFrame:
    """Read the real HQ time axis and entity columns from the fixed-format store.

    The store is FIXED format (key ``/consumption``), so ``columns=`` and
    ``where=`` raise ``TypeError``; a bounded request uses integer
    ``start``/``stop`` row positions and the entity subset is taken in memory
    after the read (the full read measures ~0.5 s / ~280 MB).

    Args:
        hq_dir: Directory holding the operator-local HQ export.
        entities: Number of entity columns to keep (first N as stored).
        days: Calendar days to read; ``>= FULL_AXIS_DAYS`` takes the entire
            stored axis including its closing instant.

    Returns:
        The wide kW frame with a naive uniform 15-min ``DatetimeIndex`` and
        string entity columns.

    Raises:
        FileNotFoundError: If the HQ export is absent, naming where it lives
            and that this proof is operator-only.
        ValueError: If ``entities`` or ``days`` is not a positive count.
    """
    consumption = hq_dir / CONSUMPTION_FILE
    if not consumption.exists():
        raise FileNotFoundError(
            f"{consumption}: the HQ dataset is not present. datasets/hq is "
            "gitignored operator-local data (consumption.h5, ~268 MB) and "
            "never ships; this proof is operator-only and cannot run in CI "
            "or on a fresh clone. Place the Hydro-Quebec export at "
            f"{DEFAULT_HQ_DIR / CONSUMPTION_FILE} or pass --hq-dir"
        )
    if entities < 1:
        raise ValueError(f"--entities must be a positive count, found {entities}")
    if days < 1:
        raise ValueError(f"--days must be a positive count, found {days}")
    if days >= FULL_AXIS_DAYS:
        frame = pd.read_hdf(consumption)
    else:
        frame = pd.read_hdf(consumption, start=0, stop=days * ROWS_PER_DAY)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(
            f"{consumption}: expected a DataFrame under key '/consumption', "
            f"found {type(frame).__name__}"
        )
    return frame.iloc[:, :entities]


def _build_tidy_frame(measured: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Turn the wide HQ frame into the shipped path's tidy measurement rows.

    The real axis is localized with ``tz_localize("UTC")`` per finding M1b
    (see :data:`AXIS_READING_DISCLOSURE`); the voltage values are SYNTHESIZED
    per finding M1 (see :data:`SYNTHESIS_DISCLOSURE`); the entity ids are the
    real stored column labels prefixed ``hq_home_``.

    Args:
        measured: Wide frame from :func:`_load_measured_frame`; only its axis
            and column labels are used -- its kW values are never relabeled.

    Returns:
        A ``(tidy, bus_by_entity)`` pair: the tidy
        ``(timestamp, entity_id, quantity, value)`` frame, instant-major, and
        the operator-declared demo join mapping.
    """
    axis_utc = measured.index.tz_localize("UTC")
    entity_ids = [f"hq_home_{column}" for column in measured.columns]
    bus_by_entity = {
        entity: f"bus_{column}"
        for entity, column in zip(entity_ids, measured.columns, strict=True)
    }
    n_instants = len(axis_utc)
    n_entities = len(entity_ids)
    rng = np.random.default_rng(42)
    voltages = 1.0 + rng.normal(0.0, 0.01, size=(n_instants, n_entities))
    tidy = pd.DataFrame(
        {
            "timestamp": axis_utc.repeat(n_entities),
            "entity_id": np.tile(np.array(entity_ids, dtype=object), n_instants),
            "quantity": "voltage_pu",
            "value": voltages.ravel(),
        }
    )
    return tidy, bus_by_entity


def _peak_rss_mb() -> float:
    """Return this process's peak resident set size in MiB (Linux ru_maxrss KiB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _repo_relative(path: Path) -> str:
    """Render a path relative to the repository root, for a tracked receipt.

    An absolute path in a receipt records the operator's directory layout rather
    than the evidence, and the public-surface hygiene gate rejects one that
    happens to name a removed project. Paths outside the repository keep their
    absolute form, because a relative rendering of them would be misleading.

    Args:
        path: Path to render.

    Returns:
        The repository-relative path, or ``str(path)`` when it lies outside.
    """
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _evidence(
    observations: tuple[Any, ...],
    tidy_rows: int,
    n_entities: int,
    expected_instants: int,
    elapsed_ingest: float,
    elapsed_total: float,
    source: Path,
) -> dict[str, Any]:
    """Assemble the evidence record, asserting what the receipt will claim.

    Args:
        observations: The shipped path's output, one per instant.
        tidy_rows: Row count of the tidy frame fed in the single call.
        n_entities: Declared entity count.
        expected_instants: Instant count of the real axis fed in; the shipped
            path must emit exactly one observation per instant.
        elapsed_ingest: Seconds spent inside ``read_measured_observations``.
        elapsed_total: Seconds for the whole proof (read, build, ingest).
        source: The HDF5 file the real axis and entities came from.

    Returns:
        dict[str, Any]: The JSON-serializable evidence mapping.

    Raises:
        RuntimeError: If the shipped path's output contradicts a claim the
            receipt would make (count, provenance, as_of ordering) -- a loud
            failure, never a partial receipt.
    """
    if not observations:
        raise RuntimeError(
            "the shipped path returned zero observations for a non-empty "
            "frame; refusing to emit evidence"
        )
    if len(observations) != expected_instants:
        raise RuntimeError(
            f"the shipped path emitted {len(observations)} observations, "
            f"expected one per axis instant ({expected_instants}); refusing "
            "to emit evidence"
        )
    previous = None
    for index, observation in enumerate(observations):
        current = observation.as_of
        if current is None:
            raise RuntimeError(
                f"observation {index} carries no as_of; the shipped path is "
                "not stamping from the datum"
            )
        if previous is not None and current <= previous:
            raise RuntimeError(
                f"observation {index}'s as_of ({current.isoformat()}) does "
                "not strictly increase over its predecessor "
                f"({previous.isoformat()}); the receipt claims ascending "
                "as_of order"
            )
        previous = current
    sample = observations[len(observations) // 2]
    for name, observation in (("first", observations[0]), ("sampled", sample)):
        if observation.provenance != "measured":
            raise RuntimeError(
                f"the {name} observation carries provenance "
                f"{observation.provenance!r}, expected 'measured'; the "
                "shipped path is not behaving as the receipt would claim"
            )
        if observation.as_of is None or observation.as_of.tzinfo is None:
            raise RuntimeError(
                f"the {name} observation's as_of is not a tz-aware instant; "
                "the shipped path is not stamping from the datum"
            )
    return {
        "shipped_path": (
            "gridalyn.twin.observation.ingest.read_measured_observations "
            "(one whole-frame call, no batching)"
        ),
        # Relative to the repository root: an absolute path leaks the
        # developer's directory layout into a tracked receipt, and the
        # public-surface hygiene gate rejects one that names a removed project.
        "source_file": _repo_relative(source),
        "n_instants": len(observations),
        "n_entities": n_entities,
        "n_tidy_rows": tidy_rows,
        "first_as_of_utc": observations[0].as_of.isoformat(),
        "last_as_of_utc": observations[-1].as_of.isoformat(),
        "axis_reading_disclosure": AXIS_READING_DISCLOSURE,
        "synthesis_disclosure": SYNTHESIS_DISCLOSURE,
        "join_disclosure": JOIN_DISCLOSURE,
        "elapsed_seconds_ingest": round(elapsed_ingest, 2),
        "elapsed_seconds_total": round(elapsed_total, 2),
        "peak_rss_mb": round(_peak_rss_mb(), 1),
        "sampled_observation": {
            "index": len(observations) // 2,
            "as_of_utc": sample.as_of.isoformat(),
            "provenance": sample.provenance,
            "converged": sample.converged,
            "n_bus_ids": int(sample.bus_ids.size),
            "first_bus_id": str(sample.bus_ids[0]),
            "first_voltage_pu": round(float(sample.bus_voltage_pu[0]), 6),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the at-scale proof and emit its JSON evidence.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        0 on success; a failure anywhere raises, loudly, so a partial run can
        never masquerade as evidence.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hq-dir",
        type=Path,
        default=DEFAULT_HQ_DIR,
        help="directory holding the operator-local HQ export",
    )
    parser.add_argument(
        "--entities",
        type=int,
        default=1000,
        help="number of real HQ entity columns to run through the join",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=FULL_AXIS_DAYS,
        help="calendar days of the real axis; >= 365 takes the full axis",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the evidence JSON here instead of stdout",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    measured = _load_measured_frame(args.hq_dir, args.entities, args.days)
    print(
        f"read {measured.shape[0]} instants x {measured.shape[1]} entities "
        f"from {args.hq_dir / CONSUMPTION_FILE}",
        file=sys.stderr,
        flush=True,
    )
    tidy, bus_by_entity = _build_tidy_frame(measured)
    join = EntityJoin.from_mapping(bus_by_entity)
    print(
        f"feeding {len(tidy)} tidy rows through the shipped path in one call",
        file=sys.stderr,
        flush=True,
    )
    ingest_started = time.perf_counter()
    observations = read_measured_observations(tidy, join=join)
    elapsed_ingest = time.perf_counter() - ingest_started

    evidence = _evidence(
        observations,
        tidy_rows=len(tidy),
        n_entities=measured.shape[1],
        expected_instants=measured.shape[0],
        elapsed_ingest=elapsed_ingest,
        elapsed_total=time.perf_counter() - started,
        source=args.hq_dir / CONSUMPTION_FILE,
    )
    rendered = json.dumps(evidence, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"evidence written to {args.out}", file=sys.stderr, flush=True)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

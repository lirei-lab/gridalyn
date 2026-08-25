"""OCHRE-side driver for the phase-1 feasibility gate.

This module runs **inside the simulation virtualenv** (numpy 1.26.4,
``ochre-nrel==0.9.2``) and never inside gridalyn's own environment. It must
therefore import nothing from ``gridalyn`` and nothing outside OCHRE's own
dependency closure — it is invoked as a subprocess by
``run_feasibility_gate.py``, which lives on the other side of the process
boundary and cannot share a numpy with it.

Two modes:

``simulate``
    Load an HPXML file (plus the EPW it names), run OCHRE at the requested
    resolution, and write a per-end-use time series to parquet alongside a
    JSON summary carrying the wall-clock and a content digest.

``compare``
    Load two parquet time series written by ``simulate`` and report the
    maximum relative deviation between them. This lives here rather than in
    the gate because pandas/pyarrow exist only in this virtualenv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from typing import Any

# The end-use columns the gate requires to be present and non-degenerate.
# OCHRE names them "<End Use> Electric Power (kW)"; the gate treats a run
# with no such column, or with an all-zero total, as a failed handover.
_END_USE_SUFFIX = "Electric Power (kW)"


def _digest_frame(frame: Any) -> str:
    """Return a content digest of a time-series frame.

    Parquet bytes are not a usable identity: the format records a
    ``created_by`` string and buffer padding that vary between writes of
    identical data. This digest covers the column names, the index and the
    values rounded to 1e-9, which is what "identical output" has to mean for
    a floating-point simulation.

    Args:
        frame: The OCHRE result DataFrame.

    Returns:
        A hex sha256 digest of the frame's rounded content.
    """
    # Columns are sorted first. OCHRE returns the same data in a VARYING
    # column order between runs, so hashing them in their native order made
    # two bit-identical simulations disagree and reported a false determinism
    # failure (measured 2026-08-21: all 12 columns matched with a maximum
    # absolute difference of exactly 0, only the order differed).
    ordered = frame.reindex(sorted(frame.columns, key=str), axis=1)
    payload = "|".join(map(str, ordered.columns)).encode()
    payload += ordered.index.astype("int64").values.tobytes()
    payload += ordered.round(9).values.tobytes()
    return hashlib.sha256(payload).hexdigest()


def run_simulation(args: argparse.Namespace) -> int:
    """Run one OCHRE dwelling simulation and write its artifacts.

    Args:
        args: Parsed ``simulate`` arguments.

    Returns:
        Process exit code: 0 on success, 1 if OCHRE rejected the input.
    """
    from ochre import Dwelling

    os.makedirs(args.out, exist_ok=True)
    hpxml = os.path.abspath(args.hpxml)
    schedule = os.path.abspath(args.schedule) if args.schedule else None
    if args.sample:
        hpxml, schedule = _bundled_sample()
    kwargs: dict[str, Any] = {
        "name": "dwelling",
        "hpxml_file": hpxml,
        "weather_file": os.path.abspath(args.epw),
        "start_time": dt.datetime(2018, 1, 1, 0, 0),
        "time_res": dt.timedelta(minutes=args.minutes),
        "duration": dt.timedelta(days=args.days),
        "initialization_time": dt.timedelta(days=1),
        "output_path": os.path.abspath(args.out),
        "save_results": False,
        "verbosity": 3,
        "seed": args.seed,
    }
    if schedule:
        kwargs["hpxml_schedule_file"] = schedule

    started = time.perf_counter()
    try:
        dwelling = Dwelling(**kwargs)
        frame, _metrics, _hourly = dwelling.simulate()
    except BaseException as exc:  # noqa: B036 - OCHRE raises bare AssertionError
        # An AssertionError from OCHRE's HPXML parser carries no message, so
        # the traceback's last frame is the only locating information there
        # is. Record it verbatim rather than collapsing it to "failed".
        import traceback

        detail = traceback.format_exc().strip().splitlines()
        payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback_tail": detail[-6:],
            "seconds": round(time.perf_counter() - started, 3),
        }
        _write_json(os.path.join(args.out, "summary.json"), payload)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    parquet_path = os.path.join(args.out, "timeseries.parquet")
    frame.to_parquet(parquet_path)
    end_uses = [c for c in frame.columns if c.endswith(_END_USE_SUFFIX)]
    payload = {
        "status": "ok",
        "seconds": round(elapsed, 3),
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
        "end_use_columns": end_uses,
        "non_zero_end_uses": [c for c in end_uses if float(frame[c].abs().sum()) > 0],
        "content_digest": _digest_frame(frame),
        "parquet": parquet_path,
        "ochre_version": _ochre_version(),
        "numpy_version": _numpy_version(),
    }
    _write_json(os.path.join(args.out, "summary.json"), payload)
    print(json.dumps(payload, indent=2))
    return 0


def compare_runs(args: argparse.Namespace) -> int:
    """Compare two simulation outputs and report their deviation.

    Args:
        args: Parsed ``compare`` arguments.

    Returns:
        Process exit code: always 0; the verdict is in the printed payload.
    """
    import pandas as pd

    left = pd.read_parquet(args.left)
    right = pd.read_parquet(args.right)
    aligned = list(left.columns) == list(right.columns) and left.shape == right.shape
    payload: dict[str, Any] = {
        "aligned": aligned,
        "bitwise_identical": bool(aligned and left.equals(right)),
    }
    if aligned:
        scale = left.abs().max().replace(0.0, 1.0)
        payload["max_relative_deviation"] = float(
            ((left - right).abs().max() / scale).max()
        )
        payload["left_digest"] = _digest_frame(left)
        payload["right_digest"] = _digest_frame(right)
    print(json.dumps(payload, indent=2))
    return 0


def _bundled_sample() -> tuple[str, str]:
    """Locate the ResStock dwelling OCHRE ships as its own reference input.

    The gate runs this when the real handover fails, to separate "OCHRE is
    unusable here" from "OCHRE rejects *this* HPXML" — and to get a
    wall-clock and a determinism reading even when the route is broken.

    Returns:
        A ``(hpxml_path, schedule_path)`` pair.
    """
    import ochre

    root = os.path.join(os.path.dirname(ochre.__file__), "defaults", "Input Files")
    return (
        os.path.join(root, "bldg0112631-up00.xml"),
        os.path.join(root, "bldg0112631_schedule.csv"),
    )


def _ochre_version() -> str:
    """Return the installed OCHRE version string."""
    import ochre

    return str(getattr(ochre, "__version__", "unknown"))


def _numpy_version() -> str:
    """Return the numpy version this virtualenv resolved to."""
    import numpy

    return str(numpy.__version__)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` as deterministic JSON.

    Args:
        path: Destination file path.
        payload: JSON-serialisable mapping.
    """
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    """Dispatch the driver's two modes.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    sim = sub.add_parser("simulate", help="run one OCHRE dwelling")
    sim.add_argument("--hpxml", required=True)
    sim.add_argument(
        "--sample",
        action="store_true",
        help="ignore --hpxml and run OCHRE's own bundled ResStock dwelling",
    )
    sim.add_argument("--epw", required=True)
    sim.add_argument("--out", required=True)
    sim.add_argument("--schedule", default=None)
    sim.add_argument("--days", type=int, default=2)
    sim.add_argument("--minutes", type=int, default=15)
    sim.add_argument("--seed", type=int, default=1234)

    cmp_ = sub.add_parser("compare", help="compare two time series")
    cmp_.add_argument("--left", required=True)
    cmp_.add_argument("--right", required=True)

    args = parser.parse_args(argv)
    if args.mode == "simulate":
        return run_simulation(args)
    return compare_runs(args)


if __name__ == "__main__":
    raise SystemExit(main())

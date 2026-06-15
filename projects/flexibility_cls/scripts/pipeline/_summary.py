"""Stage-boundary array summarization for the golden-master baseline.

This study-layer helper turns a numeric stage-boundary array into a
JSON-serializable summary: descriptive statistics (compared at numeric
tolerance) plus a ``content_sha256`` of the *rounded* array (an exact
tripwire). The two together let the project regression localize drift to a
single pipeline stage (D-01/D-02).

Layer note (CLAUDE.md): this lives in the study layer
(``projects/flexibility_cls/scripts/``), never in a ``gridalyn/`` SDK layer,
because imports flow strictly downward and this is study-only tooling.

Determinism / rounding policy (D-02, RESEARCH Open Questions 1-2):
    The hash is taken over ``np.round(arr, round_decimals)`` so benign
    last-bit float noise (BLAS/accumulation-order) does not flip it. The
    ``round_decimals`` floor is chosen empirically per boundary array, one
    digit coarser than the observed same-machine jitter and finer than any
    plausible real drift.

    The two Stage-00 Monte-Carlo arrays (``substation_baseline_mc`` /
    ``substation_ev_capability_mc``) are the rawest, most cross-environment
    jitter-prone outputs and are therefore pinned STATS-PRIMARY: their hash
    is emitted at a deliberately COARSER ``round_decimals`` than the
    more-aggregated downstream Stage-01/02 arrays and serves as a tripwire
    only -- the stats are the load-bearing Stage-00 assertion. The
    Stage-01/02 hashes (and the Stage-03 ``E_omega`` distribution) are the
    primary cross-environment tripwires.
"""

from __future__ import annotations

import hashlib

import numpy as np


def summarize_array(arr: np.ndarray, *, round_decimals: int) -> dict[str, object]:
    """Return descriptive stats plus a sha256 of the rounded array.

    The array is coerced to a contiguous ``float64`` layout and rounded to
    ``round_decimals`` before both the statistics and the hash are computed,
    so the ``content_sha256`` is stable across benign last-bit float noise
    (changes below the rounding floor produce an identical hash; changes at
    or above it produce a different hash).

    Args:
        arr: Stage-boundary numeric array (float-coercible). For a pandas
            object, extract ``.to_numpy()`` at the call site -- this helper
            accepts an ndarray only and never hashes a pandas object directly.
        round_decimals: Rounding precision applied before hashing, tied to
            the deterministic tolerance floor (D-02). Coarser for the
            jitter-prone Stage-00 Monte-Carlo arrays; finer for the
            more-stable downstream arrays.

    Returns:
        Mapping with ``shape`` (list[int]), ``sum``, ``mean``, ``min``,
        ``max`` (all plain ``float``), a ``quantiles`` sub-dict
        (``p5``/``p25``/``p50``/``p75``/``p95``), the ``content_sha256``
        string tripwire (exact-compared), and the echoed ``round_decimals``.
        Every numeric value is a plain Python ``float``/``int`` so
        ``json.dumps`` succeeds and the regression engine's numeric branch
        applies (no numpy scalar types leak).

    Raises:
        ValueError: If ``arr`` is empty or contains any non-finite value
            (NaN or +/-inf) -- summarizing garbage would silently produce a
            meaningless hash, and a non-finite value serializes as the
            non-standard JSON token ``NaN``/``Infinity`` that breaks the
            golden-master JSON contract (V5 input validation).
    """
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        raise ValueError("summarize_array: input array is empty")
    if not np.isfinite(a).all():
        raise ValueError(
            "summarize_array: input array contains non-finite values (NaN/inf)"
        )

    a = np.ascontiguousarray(np.round(a, round_decimals))
    # Collapse signed zero (-0.0 -> +0.0) so the content hash is sign-of-zero
    # canonical: IEEE-754 -0.0 and +0.0 are numerically equal but have
    # different byte patterns, and sub-floor jitter across a zero crossing
    # rounds to -0.0 on one machine and +0.0 on another, which would otherwise
    # flip the hash while every descriptive stat stays identical (CR-01).
    a = a + 0.0
    q = np.percentile(a, [5, 25, 50, 75, 95])
    return {
        "shape": [int(dim) for dim in a.shape],
        "sum": float(a.sum()),
        "mean": float(a.mean()),
        "min": float(a.min()),
        "max": float(a.max()),
        "quantiles": {
            "p5": float(q[0]),
            "p25": float(q[1]),
            "p50": float(q[2]),
            "p75": float(q[3]),
            "p95": float(q[4]),
        },
        "content_sha256": hashlib.sha256(a.tobytes()).hexdigest(),
        "round_decimals": int(round_decimals),
    }

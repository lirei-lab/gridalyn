"""Golden byte-stability + no-UserWarning seal test for ev_hosting_flex (SEAL-01).

This module is the run-vs-run reproducibility tripwire for the
``projects/ev_hosting_flex`` design-day Monte-Carlo study. It proves three things
about the governed numerics produced under the locked determinism contract
(``config.SEED=42`` / ``DTYPE=float64`` / ``ROUND_DECIMALS=6``):

* the design-day MC arrays (``q_real.npy`` / ``q_design.npy`` / ``ev_pool_design.npy``)
  are byte-stable across two fresh ``SEED=42`` runs of the generation stage — hashed
  over the canonical float64 array VALUES, never the ``.npy`` file bytes (Pitfall 1/4);
* the reserve/activation traces (``r_t`` / ``e_a_t`` in ``reserve_activation.parquet``)
  are value-equal after a parquet read-back (parquet *file* bytes are not asserted —
  Pitfall 4 — only the rounded float64 view via ``np.array_equal``);
* the governed building/EV generation path (``make_design_day_ensemble``) emits NO
  ``UserWarning`` at runtime, i.e. there is no silent SDK fallback substituting a
  hand-rolled base for the recalibrated SDK building agent (Pitfall 5 / T-17-01).

The ``created_at`` provenance timestamp is the only non-deterministic field in any
report; comparisons that touch report/regression stdout strip it via the reused
``_normalize_report`` / ``_CREATED_AT_RE`` from ``tests.test_operations_determinism``
(Pitfall 1) — no ``*_report.json`` is ever hashed.

If the golden array hashes DIVERGE across the two runs, that is a *pinning* defect to
fix (tighten the seed / round / BLAS thread cap), NOT a reason to re-pick a canonical
order or silently re-baseline — escalate to the user (D-01 / D-02 precedent).

The cache-dependent assertions ``skipif``-skip when the gitignored on-disk artifacts
are absent (e.g. in CI, where ``projects/*/outputs/`` is gitignored); they run locally
once the design-day MC stage has been regenerated in the main tree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Reuse the determinism primitives rather than re-authoring the normalizer
# (Pitfall 1) — these strip the wall-clock ``created_at`` from any report stdout.
from tests.test_operations_determinism import (  # noqa: F401
    _CREATED_AT_RE,
    _normalize_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _REPO_ROOT / "projects" / "ev_hosting_flex"
_DATA_DIR = _PROJECT_ROOT / "outputs" / "data"
_JSON_DIR = _PROJECT_ROOT / "outputs" / "json"

# The generation stage whose SEED=42 byte-stability we assert. Distinct from the
# flexibility_cls-hard-wired ``_VERIFY_SCRIPT`` in test_operations_determinism.
_GENERATE_STAGE = _PROJECT_ROOT / "scripts" / "pipeline" / "generate_design_day_mc.py"

_GOLDEN_ARRAYS = ("q_real.npy", "q_design.npy", "ev_pool_design.npy")
_RESERVE_PARQUET = _DATA_DIR / "reserve_activation.parquet"
_ROUND_DECIMALS = 6

# The headline scalar metrics (the citable numbers) — compared from the data
# JSONs, never the ``*_report.json`` (which carries the non-deterministic
# ``created_at``). Keyed by source file -> {json_path_key: ...}.
_HEADLINE_JSONS = (
    "firm_hosting.json",
    "flexible_hosting.json",
    "nonwires_economics.json",
)

_cache_present = all((_DATA_DIR / name).is_file() for name in _GOLDEN_ARRAYS)
_requires_cache = pytest.mark.skipif(
    not _cache_present,
    reason=(
        "ev_hosting_flex design-day MC arrays are gitignored runtime state; "
        "regenerate the design-day MC stage in the main tree before running "
        "the golden byte-stability assertions (skips in CI)."
    ),
)


def _hash_arr(path: Path) -> str:
    """Return a sha256 over an array's canonical float64 VALUES (not file bytes).

    Hashing the canonical C-contiguous float64 byte view (with signed-zero
    normalization) makes the digest independent of ``.npy`` header/file framing
    and of any non-deterministic container metadata (Pitfall 1/4).

    Args:
        path: Path to the ``.npy`` array to fingerprint.

    Returns:
        The hex sha256 digest over ``np.ascontiguousarray(a, float64)`` bytes.
    """
    arr = np.load(path)
    canonical = np.ascontiguousarray(arr, dtype=np.float64) + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _run_generation_stage() -> None:
    """Run the design-day MC generation stage once in a fresh subprocess.

    Mirrors the ``tests/test_repro_dod.py`` subprocess pattern: an isolated
    interpreter so the BLAS thread caps and ``SEED=42`` plumbing are exercised
    exactly as the workflow runs them.

    Raises:
        AssertionError: If the stage exits non-zero.
    """
    result = subprocess.run(
        [sys.executable, str(_GENERATE_STAGE)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        "generate_design_day_mc.py failed: " f"{result.stderr or result.stdout}"
    )


def _read_reserve_values() -> dict[str, np.ndarray]:
    """Read back ``r_t`` / ``e_a_t`` as rounded float64 views from the parquet.

    Returns:
        A mapping of column name to its rounded float64 numpy array. Parquet
        *file* bytes are deliberately NOT hashed (Pitfall 4); only the read-back
        float64 values are compared via ``np.array_equal``.
    """
    frame = pd.read_parquet(_RESERVE_PARQUET)
    out: dict[str, np.ndarray] = {}
    for col in ("r_t", "e_a_t"):
        if col in frame.columns:
            values = np.asarray(frame[col].to_numpy(), dtype=np.float64)
            out[col] = np.round(values, _ROUND_DECIMALS)
    return out


def _read_headline_scalars() -> dict[str, object]:
    """Collect the headline scalar values from the data JSONs (not reports).

    Returns:
        A flat mapping of ``"<file>:<key>"`` to the scalar value for every
        top-level int/float/bool entry, deliberately skipping list/dict members
        and the timestamped ``*_report.json`` files.
    """
    scalars: dict[str, object] = {}
    for name in _HEADLINE_JSONS:
        path = _JSON_DIR / name
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        for key, value in payload.items():
            if isinstance(value, (int, float, bool)):
                scalars[f"{name}:{key}"] = value
    return scalars


@_requires_cache
def test_design_day_arrays_byte_stable_across_two_runs() -> None:
    """Q_real/Q_design/ev_pool are byte-stable across two SEED=42 generations.

    Snapshots the on-disk array VALUE hashes, re-runs the generation stage in a
    fresh subprocess, and asserts every golden array's value-hash is unchanged.
    Divergence is a pinning defect (tighten seed/round/thread cap), never a
    reason to re-pick a canonical order — escalate per D-01/D-02.
    """
    before = {name: _hash_arr(_DATA_DIR / name) for name in _GOLDEN_ARRAYS}

    _run_generation_stage()

    after = {name: _hash_arr(_DATA_DIR / name) for name in _GOLDEN_ARRAYS}
    for name in _GOLDEN_ARRAYS:
        assert before[name] == after[name], (
            f"{name} is NON-reproducible across two SEED=42 runs "
            "(array VALUE sha256 diverged) — a determinism PINNING defect "
            "(seed/round/BLAS thread cap). Do NOT re-baseline; escalate (D-01)."
        )


@_requires_cache
def test_reserve_traces_value_equal_after_parquet_readback() -> None:
    """r_t/e_a_t are value-equal after a parquet read-back (not file-byte hashed).

    Reads the reserve/activation traces back from parquet, re-runs the upstream
    generation stage, and asserts the rounded float64 views are ``np.array_equal``.
    Parquet *file* bytes carry library/version metadata and are NOT asserted
    (Pitfall 4) — only the numeric values.
    """
    if not _RESERVE_PARQUET.is_file():
        pytest.skip("reserve_activation.parquet absent — regenerate the stage")

    before = _read_reserve_values()
    assert before, "reserve_activation.parquet exposed neither r_t nor e_a_t"

    _run_generation_stage()

    after = _read_reserve_values()
    for col, values in before.items():
        assert col in after, f"{col} disappeared from reserve_activation.parquet"
        assert np.array_equal(values, after[col]), (
            f"reserve trace {col!r} diverged across runs after parquet "
            "read-back — a determinism pinning defect; escalate (D-01)."
        )


@_requires_cache
def test_headline_scalars_stable_across_two_runs() -> None:
    """Headline scalars (firm/flexible/economics JSONs) are run-vs-run stable.

    Compares the citable scalar values from the data JSONs (never the
    timestamped ``*_report.json``) before and after a fresh generation run.
    """
    before = _read_headline_scalars()
    assert before, "no headline scalar JSONs found — regenerate the stage"

    _run_generation_stage()

    after = _read_headline_scalars()
    assert before == after, (
        "headline scalars diverged across two SEED=42 runs — a pinning defect; "
        "escalate per D-01, do NOT silently re-baseline."
    )


def test_governed_generation_emits_no_userwarning() -> None:
    """The governed generation path raises (never silently warns) — no UserWarning.

    Runs ``make_design_day_ensemble`` at a small K under
    ``warnings.catch_warnings(record=True)`` and asserts no captured warning is a
    ``UserWarning`` (the no-silent-SDK-fallback guarantee — Pitfall 5 / T-17-01),
    and that the returned ``Q_real`` is float64 (the determinism dtype contract).
    """
    import warnings

    from projects.ev_hosting_flex.scripts._generators import (
        make_design_day_ensemble,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = make_design_day_ensemble(n_homes=7, k=2, seed=42)

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, (
        "governed generation path emitted a UserWarning (possible silent SDK "
        f"fallback): {[str(w.message) for w in user_warnings]}"
    )
    assert np.asarray(out["Q_real"]).dtype == np.float64

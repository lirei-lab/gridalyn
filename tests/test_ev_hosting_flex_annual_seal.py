"""Byte-stability seal for the study-B annual chain (F6 successor of the
design-day seal).

Snapshots the on-disk golden artifacts, re-runs the annual pipeline stages
3–6 in FRESH SUBPROCESSES (the workflow's own execution mode, so the BLAS
thread caps and ``SEED=42`` plumbing are exercised exactly as governed runs
do), and asserts every value-hash is unchanged. Divergence is a determinism
PINNING defect (seed/round/thread cap) — never a reason to re-baseline;
escalate per the study-B migration design doc.

LEAVES THE WORKSPACE EXACTLY AS IT FOUND IT. The chain regenerates stages
3–6 in place, and until 2026-09-04 whatever it wrote stayed: on a tree whose
artifacts predated the current code, an ordinary ``pytest -q`` replaced the
annual chain's outputs with current-code ones and left everything downstream
from the old code — a mixed set with no trace of the mixing (syntgrid-qgr.1,
found by syntgrid-66). The seal now snapshots ``outputs/{data,json,reports}``
before the chain and restores every file (bytes and mtime, ``copy2``) in a
``finally`` — pass or fail — deleting anything the chain created that was not
there before, then asserts the tree's digests are identical to the snapshot.
The property under test is unchanged: two runs of the same code must agree.

Skips when the gitignored cache/artifacts are absent (CI). Runtime is
dominated by the annual Monte-Carlo stage (measured 2026-08-06:
``generate_annual_mc.py`` 284.0 s of the 290.5 s chain — 97.8%; the other
three stages total 6.6 s; the whole test is ~287 s, over half the suite).

Slow tier (#19)
---------------
The test carries ``@pytest.mark.slow``. The DEFAULT run still executes it —
that is what proves the byte-stability property, and CI passes no marker
filter — so the tier does not weaken the seal. For fast local iteration:

* ``pytest -m "not slow"`` deselects it (shows in the deselected count), or
* ``GRIDALYN_SKIP_SLOW=1 pytest`` skips it with a visible reason in the
  suite's skip summary, which is the auditable form.

A real speedup (preference (a)) is not available from this file: the four
stages are strictly data-dependent (no parallelism), the hashing is
negligible, and the stage scripts live under ``projects/`` where the
byte-stable pipeline must not be modified.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts.config import (
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PIPELINE = _REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts" / "pipeline"
_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_JSON_DIR = PROJECT_OUTPUTS_DIR / "json"

_ANNUAL_STAGES = (
    "generate_annual_mc.py",
    "compute_congestion_annual.py",
    "apply_curtailment_contracts.py",
    "compute_curtailment_economics.py",
)
_GOLDEN_ARRAYS = ("base_annual.npy", "ev_fleet_annual.npy", "tday_mean_c.npy")
_GOLDEN_JSON = (
    "firm_hosting_annual.json",
    "curtailment_hosting.json",
    "curtailment_economics.json",
)

_READY = (PROJECT_CACHE_DIR / "pp_net_cache.pkl").is_file() and all(
    (_DATA_DIR / name).is_file() for name in _GOLDEN_ARRAYS
)
_SKIP_REASON = (
    "annual seal needs the gitignored topology cache + annual artifacts; run "
    "prepare_topology_cache.py and generate_annual_mc.py first"
)

# Explicit slow-tier opt-out. Deliberately an env var rather than only the
# ``-m "not slow"`` filter: a deselected test is invisible in the skip summary,
# while this skip surfaces with its reason (the Phase-3 skip-visibility gate
# checks that reason's specificity).
_SLOW_OPT_OUT = os.environ.get("GRIDALYN_SKIP_SLOW") == "1"
_SLOW_SKIP_REASON = (
    "GRIDALYN_SKIP_SLOW=1: the ~287 s annual byte-stability seal was "
    "deliberately skipped for fast iteration; unset the variable and re-run "
    "to prove the property before shipping"
)


def _hash_array(path: Path) -> str:
    """Return the canonical-bytes sha256 of a saved float array."""
    canonical = np.ascontiguousarray(np.load(path), dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _hash_json(path: Path) -> str:
    """Return the sha256 of a canonical (sorted-key) JSON re-serialization."""
    payload = json.loads(path.read_text())
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _run_annual_chain() -> None:
    """Re-run the annual stages 3–6 in dependency order, one subprocess each.

    Invoked as ``python -m projects.ev_hosting_flex.scripts.pipeline.<stage>``
    from the repo root (Phase 20, plan 20-02) so the ``projects.*`` imports
    resolve without the removed ``sys.path`` boilerplate — the same
    interpreter-bound module invocation the workflow's ``{python} -m`` uses.
    """
    for stage in _ANNUAL_STAGES:
        module = (
            f"projects.ev_hosting_flex.scripts.pipeline.{stage.removesuffix('.py')}"
        )
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"annual seal stage {stage} exited {result.returncode}:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


_REPORTS_DIR = PROJECT_OUTPUTS_DIR / "reports"
#: Everything the four stages can touch. Restored wholesale rather than by
#: golden name, so a stage that gains an output cannot leave it behind.
_TOUCHED_DIRS = (_DATA_DIR, _JSON_DIR, _REPORTS_DIR)


def _tree_digests() -> dict[Path, str]:
    """Return sha256 of every file under the dirs the chain can touch."""
    out: dict[Path, str] = {}
    for base in _TOUCHED_DIRS:
        if base.is_dir():
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                out[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _snapshot(into: Path) -> dict[Path, Path]:
    """Copy every file under the touched dirs into ``into``; return the map."""
    saved: dict[Path, Path] = {}
    for base in _TOUCHED_DIRS:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                target = into / path.relative_to(PROJECT_OUTPUTS_DIR)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                saved[path] = target
    return saved


def _restore(saved: dict[Path, Path]) -> None:
    """Put every snapshotted file back (bytes + mtime); drop files the chain added."""
    for base in _TOUCHED_DIRS:
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path not in saved:
                    path.unlink()
    for path, copy in saved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copy, path)


@pytest.mark.slow
@pytest.mark.skipif(_SLOW_OPT_OUT, reason=_SLOW_SKIP_REASON)
@pytest.mark.skipif(not _READY, reason=_SKIP_REASON)
def test_annual_chain_byte_stable_across_two_runs() -> None:
    """Arrays AND headline JSONs are byte-stable across two SEED=42 runs --
    and the workspace is left exactly as found."""
    before_arrays = {name: _hash_array(_DATA_DIR / name) for name in _GOLDEN_ARRAYS}
    before_json = {name: _hash_json(_JSON_DIR / name) for name in _GOLDEN_JSON}
    tree_before = _tree_digests()

    with tempfile.TemporaryDirectory() as tmp:
        saved = _snapshot(Path(tmp))
        try:
            _run_annual_chain()
            after_arrays = {
                name: _hash_array(_DATA_DIR / name) for name in _GOLDEN_ARRAYS
            }
            after_json = {name: _hash_json(_JSON_DIR / name) for name in _GOLDEN_JSON}
        finally:
            _restore(saved)

    assert _tree_digests() == tree_before, (
        "the seal left the workspace different from how it found it -- the "
        "restore is incomplete, and that is the contamination path this guard "
        "exists to close"
    )

    for name in _GOLDEN_ARRAYS:
        after = after_arrays[name]
        assert before_arrays[name] == after, (
            f"{name} is NON-reproducible across two SEED=42 runs (value sha256 "
            "diverged) — a determinism PINNING defect (seed/round/BLAS thread "
            "cap). Do NOT re-baseline; escalate."
        )
    for name in _GOLDEN_JSON:
        after = after_json[name]
        assert before_json[name] == after, (
            f"{name} headline diverged across two SEED=42 runs — a determinism "
            "PINNING defect. Do NOT re-baseline; escalate."
        )

"""Byte-stability seal for the study-B annual chain (F6 successor of the
design-day seal).

Snapshots the on-disk golden artifacts, re-runs the annual pipeline stages
3–6 in FRESH SUBPROCESSES (the workflow's own execution mode, so the BLAS
thread caps and ``SEED=42`` plumbing are exercised exactly as governed runs
do), and asserts every value-hash is unchanged. Divergence is a determinism
PINNING defect (seed/round/thread cap) — never a reason to re-baseline;
escalate per the study-B migration design doc.

Skips when the gitignored cache/artifacts are absent (CI). Runtime is
dominated by one annual SDK simulation set (~90 s).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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
    """Re-run the annual stages 3–6 in dependency order, one subprocess each."""
    for stage in _ANNUAL_STAGES:
        result = subprocess.run(
            [sys.executable, str(_PIPELINE / stage)],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"annual seal stage {stage} exited {result.returncode}:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


@pytest.mark.skipif(not _READY, reason=_SKIP_REASON)
def test_annual_chain_byte_stable_across_two_runs() -> None:
    """Arrays AND headline JSONs are byte-stable across two SEED=42 runs."""
    before_arrays = {name: _hash_array(_DATA_DIR / name) for name in _GOLDEN_ARRAYS}
    before_json = {name: _hash_json(_JSON_DIR / name) for name in _GOLDEN_JSON}

    _run_annual_chain()

    for name in _GOLDEN_ARRAYS:
        after = _hash_array(_DATA_DIR / name)
        assert before_arrays[name] == after, (
            f"{name} is NON-reproducible across two SEED=42 runs (value sha256 "
            "diverged) — a determinism PINNING defect (seed/round/BLAS thread "
            "cap). Do NOT re-baseline; escalate."
        )
    for name in _GOLDEN_JSON:
        after = _hash_json(_JSON_DIR / name)
        assert before_json[name] == after, (
            f"{name} headline diverged across two SEED=42 runs — a determinism "
            "PINNING defect. Do NOT re-baseline; escalate."
        )

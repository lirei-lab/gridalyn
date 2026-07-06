"""End-to-end stage tests for ``generate_design_day_mc.py`` (Phase 13, GEN-01).

The governed design-day MC generation seam. These tests drive the stage against
the regenerated project topology cache (skipping cleanly when the gitignored
cache is absent — CI regenerates or skips, mirroring the stochastic/twostage
cache-gated tests) and assert:

1. ``q_real.npy`` / ``q_design.npy`` / ``ev_pool_design.npy`` are emitted with the
   expected shapes + dtypes (the design-day transformer-load ensemble + forecast
   + nested-EV pool);
2. the governed report carries ``REQUIRED_REPORT_FIELDS`` + the
   ``q_real``/``q_design`` ``content_sha256`` byte-stability tripwires (GOV-02);
3. RUN-VS-RUN BYTE STABILITY — two ``derive``/``run_stage`` calls with the same
   pinned ``SEED`` produce byte-identical ``q_real`` / ``q_design`` sha256 (the
   GEN-01 / SEAL-01 byte-stability contract built early).

GUARD-02: this test touches only the JSON cache sidecars + numpy arrays; the stage
under test never ``import pandapower`` at module scope.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS
from projects.ev_hosting_flex.scripts.config import (
    DESIGN_DAY_EV_MAX,
    K_DESIGN,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    PROJECT_ROOT,
)
from projects.ev_hosting_flex.scripts.pipeline.generate_design_day_mc import (
    derive_design_day_mc,
    run_stage,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"

# The JSON cache sidecars the stage reads (GUARD-02; never pp_net_cache.pkl). The
# pp_net_cache.pkl is also listed so the skip is honest about the gitignored cache.
_STAGE_REQUIRED = [
    PROJECT_CACHE_DIR / "feeder_selection.json",
    PROJECT_CACHE_DIR / "downstream_bus_map.json",
    PROJECT_CACHE_DIR / "node_building_count.json",
    PROJECT_CACHE_DIR / "pp_net_cache.pkl",
]


def _cache_ready() -> bool:
    """True iff the stage-2 topology cache sidecars are present (gitignored)."""
    return all(p.is_file() for p in _STAGE_REQUIRED)


def _content_sha256(arr: np.ndarray) -> str:
    """Return the canonical-bytes sha256 of a float64 array (signed-zero safe)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


_SKIP_REASON = (
    "ev_hosting_flex topology cache sidecars (feeder_selection.json / "
    "downstream_bus_map.json / node_building_count.json / pp_net_cache.pkl) not "
    "present; run prepare_topology_cache.py first (the cache is gitignored)"
)


@pytest.mark.skipif(not _cache_ready(), reason=_SKIP_REASON)
def test_artifacts_emitted_with_expected_shapes(tmp_path: Path) -> None:
    """q_real/q_design/ev_pool_design exist with the expected shapes + float64."""
    derived = derive_design_day_mc(PROJECT_CACHE_DIR, tmp_path)
    summary = derived["summary"]

    q_real_path = tmp_path / "q_real.npy"
    q_design_path = tmp_path / "q_design.npy"
    ev_pool_path = tmp_path / "ev_pool_design.npy"
    assert q_real_path.is_file()
    assert q_design_path.is_file()
    assert ev_pool_path.is_file()

    q_real = np.load(q_real_path)
    q_design = np.load(q_design_path)
    ev_pool = np.load(ev_pool_path)

    n_steps = 24  # DESIGN_DAY_RES_MINUTES=60 -> 24 hourly steps
    assert q_real.shape == (K_DESIGN, n_steps)
    assert q_real.dtype == np.float64
    assert q_design.shape == (n_steps,)
    assert q_design.dtype == np.float64
    assert ev_pool.shape == (K_DESIGN, DESIGN_DAY_EV_MAX + 1, n_steps)
    assert ev_pool.dtype == np.float64

    # The option-B operating point (2026-07-06): 1990-01-19, EV-free base p50 in
    # [65, 80]% rating. The per-home physics (R_QUEBEC/P_HEAT_QUEBEC, ~8.5 kW/home
    # coincident) is unchanged; the % of the 71.25 kW rating is now a CONSEQUENCE
    # of the physically 75 kVA / 6-home twin unit (6 x [7.5, 10] kW -> [63, 84]%),
    # measured p50 ~71.6% — no longer the 7-home idx-62 [80, 90] anchor.
    assert summary["design_date"] == "1990-01-19"
    assert 65.0 <= summary["base_peak_pct_rating_p50"] <= 80.0
    # The nested-EV pool is monotonic in count (row n >= row n-1, GEN-03) + row0 == 0.
    assert np.allclose(ev_pool[:, 0, :], 0.0)
    assert np.all(np.diff(ev_pool, axis=1) >= -1e-9)


@pytest.mark.skipif(not _cache_ready(), reason=_SKIP_REASON)
def test_report_contract_and_sha256_tripwires(tmp_path: Path) -> None:
    """run_stage emits a canonical report with REQUIRED_REPORT_FIELDS + sha256."""
    cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        report = run_stage(data_dir=tmp_path)
    finally:
        os.chdir(cwd)

    # GOV-02: the report is a canonical platform report (no hand-written JSON).
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"

    summary = report["summary"]
    # The byte-stability tripwires the Phase-17 baseline will pin (GEN-01).
    assert "q_real_content_sha256" in summary
    assert "q_design_content_sha256" in summary
    assert len(summary["q_real_content_sha256"]) == 64
    # The tripwire matches the on-disk artifact bytes.
    q_real = np.load(tmp_path / "q_real.npy")
    assert summary["q_real_content_sha256"] == _content_sha256(q_real)
    # The re-baseline note is routed into validation.warnings (the recorded shift).
    warnings = report["validation"]["warnings"]
    assert any("Re-baseline" in w and "RETIRE-01" in w for w in warnings)


@pytest.mark.skipif(not _cache_ready(), reason=_SKIP_REASON)
def test_run_vs_run_byte_stability(tmp_path: Path) -> None:
    """Two same-SEED runs produce byte-identical q_real/q_design sha256 (GEN-01)."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    derived_a = derive_design_day_mc(PROJECT_CACHE_DIR, dir_a)
    derived_b = derive_design_day_mc(PROJECT_CACHE_DIR, dir_b)

    # On-disk byte identity (the SEAL-01 contract built early).
    q_real_a = np.load(dir_a / "q_real.npy")
    q_real_b = np.load(dir_b / "q_real.npy")
    q_design_a = np.load(dir_a / "q_design.npy")
    q_design_b = np.load(dir_b / "q_design.npy")
    assert _content_sha256(q_real_a) == _content_sha256(q_real_b)
    assert _content_sha256(q_design_a) == _content_sha256(q_design_b)

    # The summary tripwires agree across runs too (no RNG-order / rounding drift).
    sa = derived_a["summary"]
    sb = derived_b["summary"]
    assert sa["q_real_content_sha256"] == sb["q_real_content_sha256"]
    assert sa["q_design_content_sha256"] == sb["q_design_content_sha256"]
    assert sa["ev_pool"]["content_sha256"] == sb["ev_pool"]["content_sha256"]

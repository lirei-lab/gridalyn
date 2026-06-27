"""Design-day Monte-Carlo generation stage for ev_hosting_flex (Phase 13, GEN-01).

Stage 3 of the v1.3 generative-MC pipeline — the governed replacement for the
retired ``generate_annual_profiles`` stage. It drives the Phase-13 kernel
(``_generators.make_design_day_ensemble``) over the binding cold design day and
persists the idx-62 transformer-load ensemble as governed, byte-stable artifacts:

* ``data/q_real.npy`` — ``(K, n_steps)`` float64 building-base transformer-load
  ensemble (the EV-free design-day base; the Phase-14 firm sweep overlays the
  nested-EV pool). Rounded to ``ROUND_DECIMALS`` before write (the determinism
  contract).
* ``data/q_design.npy`` — ``(n_steps,)`` float64 day-ahead forecast of
  ``Q_real``'s predictable mean (GEN-04). Rounded before write.
* ``data/ev_pool_design.npy`` — ``(K, DESIGN_DAY_EV_MAX + 1, n_steps)`` float64
  nested cumulative MDPI EV pool the Phase-14 firm sweep consumes (monotonic in
  count, row n = the first n EVs). Rounded before write.
* ``reports/design_day_mc_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-02; never hand-written report JSON), whose summary
  carries the selected design-day date, K, n_steps, the base %rating stats, and
  the ``q_real``/``q_design``/``ev_pool`` ``content_sha256`` byte-stability
  tripwires.

**Re-baseline note (milestone re-baseline policy).** This stage supersedes the
deterministic annual degree-day base (``generate_annual_profiles`` /
``_stochastic.tmy_base`` / ``_profiles``) with the SDK building agent recalibrated
to the Québec all-electric archetype + the project-local MDPI EV sampler, framed
on the design-day-MC transformer-load ensemble. No committed regression baseline
exists yet (the 1e-6 baseline is born in Phase 17), so the headline shift breaks
nothing; it is reported with rationale in the report ``summary.divergence_note``
and ``validation.warnings`` so the verify-phase reads the deliberate supersession.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas``. This stage reads
ONLY the JSON cache sidecars (``feeder_selection.json`` / ``node_building_count``
/ ``downstream_bus_map.json``) for the feeder's downstream home count (7 on
idx-62) — never ``pp_net_cache.pkl`` — exactly as the retired annual-profiles
stage did. The kernel's SDK imports are deferred + raise-on-missing (no silent
fallback).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Pitfall 2 (SEAL-01): cap the BLAS thread pool BEFORE numpy spins it up so the
# per-realization quantile/sum reductions stay deterministic and avoid
# thread-reordering float drift below 1e-6. This MUST precede ``import numpy``
# (do NOT mirror the other stages, which set the cap AFTER the numpy import).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.ev_hosting_flex.scripts._generators import (  # noqa: E402
    make_design_day_ensemble,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DESIGN_DAY_EV_MAX,
    DESIGN_DAY_RES_MINUTES,
    DTYPE,
    K_DESIGN,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TRANSFORMER_KVA,
)

_USABLE_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)
"""Usable transformer rating in kW (71.25 = 75 kVA x 0.95 PF) — the %rating base."""

_REBASELINE_NOTE = (
    "Re-baseline (GEN-01..04, milestone re-baseline policy): the generation seam "
    "is now the design-day Monte-Carlo transformer-load ensemble Q_real (K, "
    "n_steps) + the day-ahead forecast Q_design, produced by the SDK building "
    "agent recalibrated to the Quebec all-electric archetype (R=7.0 degC/kW, "
    "p_heat_max=13.0 kW) + the project-local MDPI EV sampler over the binding "
    "1990-01-19 cold design day. It SUPERSEDES the annual 8760h degree-day base "
    "(generate_annual_profiles / _stochastic.tmy_base) and the deterministic "
    "_profiles winter/EV envelope (RETIRE-01). No committed regression baseline "
    "exists yet (the 1e-6 baseline is born in Phase 17), so the headline shift "
    "breaks nothing; the round-before-write float64 arrays + the q_real/q_design/"
    "ev_pool content_sha256 tripwires pin run-vs-run byte stability now."
)


def _load_json(path: Path) -> dict:
    """Load a required JSON cache sidecar, failing loudly if it is missing.

    Args:
        path: Path to the JSON sidecar produced by the stage-2 topology cache.

    Returns:
        The parsed JSON mapping.

    Raises:
        FileNotFoundError: If the sidecar is absent (stale/incomplete cache).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 3 (generate_design_day_mc) requires the "
            f"topology cache sidecar {path.name} at {path}, but it is missing. "
            "Remediation: re-run stage 2 (prepare_topology_cache.py) to "
            "regenerate the load-aware cache before generating the design-day MC."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _summarize_array(arr: np.ndarray) -> dict[str, object]:
    """Return deterministic sum/max/sha256 stats over a rounded float64 array.

    The ``content_sha256`` over the canonical-bytes array is the byte-stability
    tripwire for the Phase-17 regression baseline (GEN-01 / SEAL-01).

    Args:
        arr: A rounded float64 array.

    Returns:
        A mapping with ``sum``, ``max``, ``shape`` and ``content_sha256``.
    """
    canonical = np.ascontiguousarray(arr, dtype="float64")
    # Canonicalize signed zero so -0.0 and 0.0 hash identically (REPRO).
    canonical = canonical + 0.0
    digest = hashlib.sha256(canonical.tobytes()).hexdigest()
    return {
        "sum": round(float(canonical.sum()), ROUND_DECIMALS),
        "max": round(float(canonical.max()), ROUND_DECIMALS),
        "shape": list(canonical.shape),
        "content_sha256": digest,
    }


def _feeder_home_count(cache_dir: Path) -> int:
    """Return the idx-62 feeder's downstream all-electric home count from sidecars.

    Reads ONLY the JSON cache sidecars (GUARD-02; never ``pp_net_cache.pkl``): the
    feeder transformer index from ``feeder_selection.json``, its downstream bus set
    from ``downstream_bus_map.json``, and the per-bus building count from
    ``node_building_count.json``. The feeder key is read at runtime — never
    hardcoded (mirrors the retired annual stage's ``feeder_key`` handling).

    Args:
        cache_dir: Directory holding the stage-2 JSON cache sidecars.

    Returns:
        The integer downstream home count on the selected feeder subtree (7 on
        the committed idx-62 twin).

    Raises:
        ValueError: If the feeder key is absent from the downstream map (a
            stale/mismatched cache).
    """
    feeder = _load_json(cache_dir / "feeder_selection.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    building_count = _load_json(cache_dir / "node_building_count.json")

    feeder_idx = int(feeder["feeder_transformer_idx"])
    feeder_key = f"transformer:{feeder_idx}"
    if feeder_key not in downstream:
        raise ValueError(
            f"ev_hosting_flex stage 3 (generate_design_day_mc): feeder key "
            f"{feeder_key!r} from feeder_selection.json is absent from "
            "downstream_bus_map.json. Remediation: regenerate the topology cache "
            "(stage 2) so the feeder selection and downstream map come from the "
            "same net."
        )
    homes = sum(
        int(building_count[str(b)])
        for b in downstream[feeder_key]
        if str(b) in building_count
    )
    return int(homes)


def derive_design_day_mc(cache_dir: Path, data_dir: Path) -> dict[str, object]:
    """Derive + persist the design-day MC Q_real/Q_design + nested-EV pool.

    Reads the feeder home count from the topology-cache sidecars (pandapower-free,
    GUARD-02), drives ``_generators.make_design_day_ensemble`` to get
    ``Q_real (K, n_steps)``, ``Q_design (n_steps,)`` and the per-realization nested
    cumulative MDPI EV pool ``(K, DESIGN_DAY_EV_MAX + 1, n_steps)``, rounds each to
    ``ROUND_DECIMALS`` (round-before-write, the determinism contract), and persists
    them as deterministic-bytes ``.npy`` artifacts.

    Args:
        cache_dir: Directory holding the stage-2 JSON cache sidecars.
        data_dir: Directory the artifacts are written to.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict (GEN-01).
    """
    n_homes = _feeder_home_count(cache_dir)

    ensemble = make_design_day_ensemble(
        n_homes=n_homes,
        k=K_DESIGN,
        seed=SEED,
        res_minutes=DESIGN_DAY_RES_MINUTES,
        n_ev_max=DESIGN_DAY_EV_MAX,
    )

    # Round-before-write (GEN-01 determinism contract): the kernel returns
    # unrounded float64; rounding to ROUND_DECIMALS here pins the on-disk bytes so
    # two same-seed runs are byte-identical (the q_real/q_design sha256 tripwires).
    q_real = np.round(np.asarray(ensemble["Q_real"], dtype=DTYPE), ROUND_DECIMALS)
    q_design = np.round(np.asarray(ensemble["Q_design"], dtype=DTYPE), ROUND_DECIMALS)
    ev_pool = np.round(np.asarray(ensemble["ev_pool"], dtype=DTYPE), ROUND_DECIMALS)

    data_dir.mkdir(parents=True, exist_ok=True)
    q_real_path = data_dir / "q_real.npy"
    q_design_path = data_dir / "q_design.npy"
    ev_pool_path = data_dir / "ev_pool_design.npy"
    np.save(q_real_path, q_real)
    np.save(q_design_path, q_design)
    np.save(ev_pool_path, ev_pool)

    # Base %rating stats (the EV-free Q_real peak per realization, relative to the
    # 71.25 kW usable rating) — the locked operating-point evidence (~82-87%).
    peak_per_real = q_real.max(axis=1)  # (K,) per-realization design-day peak (kW)
    pct_rating = 100.0 * peak_per_real / _USABLE_RATING_KW
    base_p50 = round(float(np.percentile(pct_rating, 50)), ROUND_DECIMALS)
    base_p90 = round(float(np.percentile(pct_rating, 90)), ROUND_DECIMALS)

    n_steps = int(q_real.shape[1])
    q_real_stats = _summarize_array(q_real)
    q_design_stats = _summarize_array(q_design)

    return {
        "artifact_paths": [q_real_path, q_design_path, ev_pool_path],
        "summary": {
            "design_date": str(ensemble["design_date"]),
            "n_homes": int(n_homes),
            "k_realizations": int(K_DESIGN),
            "n_steps": n_steps,
            "res_minutes": int(DESIGN_DAY_RES_MINUTES),
            "n_ev_max": int(DESIGN_DAY_EV_MAX),
            "usable_rating_kw": round(_USABLE_RATING_KW, ROUND_DECIMALS),
            "base_peak_pct_rating_p50": base_p50,
            "base_peak_pct_rating_p90": base_p90,
            "seed": int(SEED),
            "q_real": q_real_stats,
            "q_design": q_design_stats,
            "ev_pool": _summarize_array(ev_pool),
            "q_real_content_sha256": q_real_stats["content_sha256"],
            "q_design_content_sha256": q_design_stats["content_sha256"],
            "divergence_note": _REBASELINE_NOTE,
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full design-day MC stage: derive + npy + governed report (GEN-01).

    Args:
        cache_dir: Cache directory holding the stage-2 sidecars.
        data_dir: Output data directory override (defaults to the project's).

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    effective_cache_dir = (
        script.cache_dir if cache_dir == PROJECT_CACHE_DIR else cache_dir
    )
    effective_data_dir = data_dir if data_dir is not None else script.data_dir

    derived = derive_design_day_mc(effective_cache_dir, effective_data_dir)
    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]

    return script.write_report(
        "design_day_mc_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={
            "valid": True,
            "errors": [],
            "warnings": [_REBASELINE_NOTE],
        },
    )


def main() -> None:
    """CLI entry point for the design-day MC stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Generated design-day MC + report: "
        f"design_date={summary.get('design_date')}, "
        f"n_homes={summary.get('n_homes')}, "
        f"K={summary.get('k_realizations')}, "
        f"n_steps={summary.get('n_steps')}, "
        f"base_p50%rating={summary.get('base_peak_pct_rating_p50')}, "
        f"q_real_sha256={summary.get('q_real_content_sha256', '')[:12]}"
    )


if __name__ == "__main__":
    main()

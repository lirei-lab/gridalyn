"""Study-B annual Monte-Carlo generation seam (F1 of the annual migration).

Emits the annual artifacts the study-B pipeline re-founds on (see
``docs/superpowers/specs/2026-07-06-ev-hosting-flex-study-b-annual-migration.md``):

* ``base_annual.npy`` — ``(K_ANNUAL, 8760)`` SDK-agent feeder base realizations
  at the stressed ``R_STUDY_B`` calibration (the ONLY thermal generator);
* ``fc_base_sigma_{σ}.npy`` — day-ahead forecast bases (realization 0) per
  temperature-error sigma, for the notice-quality panel;
* ``ev_fleet_annual.npy`` — the ``(POOL_MAX_ANNUAL, 8760)`` cold-coupled
  nested EV pool (prefix sweeps);
* ``tday_mean_c.npy`` — per-day mean temperatures (the cold-day classifier).

Runs ALONGSIDE the design-day seam during the migration (no retirements in F1).

GUARD-02: no module-scope pandapower/SDK-agent imports; the agent import is
deferred inside the kernel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Pitfall 2 (SEAL-01): cap the BLAS thread pool at module top, BEFORE any import
# that pulls numpy transitively, so the annual chain stays deterministic.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    N_DAYS,
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    feeder_rating,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    DTYPE,
    FC_SIGMAS,
    K_ANNUAL,
    POOL_MAX_ANNUAL,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SEED_FC_OFFSETS,
    TRANSFORMER_KVA,
)

_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def feeder_home_count(cache_dir: Path) -> int:
    """Return the study feeder's downstream home count from the topology cache.

    Args:
        cache_dir: Stage-2 topology cache directory.

    Returns:
        The number of homes downstream of the selected feeder transformer.

    Raises:
        ValueError: If the cache reports zero downstream homes.
    """
    feeder_sel = json.loads((cache_dir / "feeder_selection.json").read_text())
    feeder_idx = int(feeder_sel["feeder_transformer_idx"])
    downstream = json.loads((cache_dir / "downstream_bus_map.json").read_text())[
        f"transformer:{feeder_idx}"
    ]
    counts = json.loads((cache_dir / "node_building_count.json").read_text())
    n_homes = sum(int(counts.get(str(int(bus)), 0)) for bus in downstream)
    if n_homes <= 0:
        raise ValueError(
            f"generate_annual_mc found no homes downstream of transformer:"
            f"{feeder_idx}. Remediation: regenerate the topology cache."
        )
    return n_homes


def derive_annual_mc(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Build and persist the annual artifacts; return paths + summary.

    Args:
        cache_dir: Stage-2 topology cache directory.
        data_dir: Output data directory the ``.npy`` artifacts are written to.

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    n_homes = feeder_home_count(cache_dir)
    temp_hourly = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp_hourly)
    tday = day_mean_temps(temp_hourly)
    # The limit a load is judged against depends on that hour's ambient
    # (RATING_CONVENTION); `_RATING_KW` stays the nameplate for reporting.
    _cap, series = feeder_rating(temp_hourly)
    limit = _cap if series is None else series

    base = np.stack(
        [
            annual_base_realization(temp_hourly, n_homes, SEED + r)
            for r in range(int(K_ANNUAL))
        ]
    ).astype(DTYPE)

    # Forecast bases (realization 0): one per sigma, offsets drawn SEQUENTIALLY
    # from the single pinned rng — the study-B draw order (D-B3).
    fc_rng = np.random.default_rng(SEED_FC_OFFSETS)
    fc_paths: list[Path] = []
    fc_peaks: dict[str, float] = {}
    for sigma in FC_SIGMAS:
        offsets = fc_rng.normal(0.0, float(sigma), N_DAYS)
        fc = annual_base_realization(
            temp_hourly, n_homes, SEED, per_day_offset_c=offsets
        )
        path = data_dir / f"fc_base_sigma_{sigma:.1f}.npy"
        np.save(path, np.round(fc, ROUND_DECIMALS))
        fc_paths.append(path)
        fc_peaks[f"{sigma:.1f}"] = round(float(fc.max()), ROUND_DECIMALS)

    ev_pool = ev_fleet_annual(
        np.random.default_rng(SEED), POOL_MAX_ANNUAL, tday, hod0
    ).astype(DTYPE)

    base_path = data_dir / "base_annual.npy"
    pool_path = data_dir / "ev_fleet_annual.npy"
    tday_path = data_dir / "tday_mean_c.npy"
    np.save(base_path, np.round(base, ROUND_DECIMALS))
    np.save(pool_path, np.round(ev_pool, ROUND_DECIMALS))
    np.save(tday_path, np.round(tday, ROUND_DECIMALS))

    base0 = base[0]
    summary = {
        "n_homes": n_homes,
        "k_annual": int(K_ANNUAL),
        "pool_max": int(POOL_MAX_ANNUAL),
        "res_minutes": int(ANNUAL_RES_MINUTES),
        "n_steps": int(base0.shape[0]),
        "tmy_hour_of_day_0": hod0,
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "base_peak_kw": round(float(base0.max()), ROUND_DECIMALS),
        "base_peak_per_home_kw": round(float(base0.max()) / n_homes, ROUND_DECIMALS),
        # Peak against the NAMEPLATE — a descriptive statistic, kept so the
        # two conventions can be read side by side.
        "base_peak_pct_rating": round(
            float(base0.max()) / _RATING_KW * 100.0, ROUND_DECIMALS
        ),
        # Peak LOADING against the capability each hour actually has. With a
        # temperature-dependent rating the peak-load hour need not be the
        # peak-loading hour, so this divides per step before taking the max.
        "base_peak_pct_capability": round(
            float((base0 / limit).max()) * 100.0, ROUND_DECIMALS
        ),
        "base_floor_hours": round(
            float((base0 > limit).sum()) * _HOURS_PER_STEP, ROUND_DECIMALS
        ),
        "ev_pool_annual_kwh_mean": round(
            float(ev_pool.sum(axis=1).mean()) * _HOURS_PER_STEP, ROUND_DECIMALS
        ),
        "fc_base_peaks_kw": fc_peaks,
    }
    return {
        "artifact_paths": [base_path, pool_path, tday_path, *fc_paths],
        "summary": summary,
    }


def run_stage(*, cache_dir: Path = PROJECT_CACHE_DIR) -> dict[str, Any]:
    """Run the annual generation stage and emit the platform report.

    Args:
        cache_dir: Stage-2 topology cache directory (test override).

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    effective_cache = script.cache_dir if cache_dir == PROJECT_CACHE_DIR else cache_dir
    derived = derive_annual_mc(effective_cache, PROJECT_OUTPUTS_DIR / "data")
    return script.write_report(
        "annual_mc_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the study-B annual generation stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir)
    summary = report.get("summary", {})
    print(
        "Generated annual MC + report: "
        f"n_homes={summary.get('n_homes')}, K={summary.get('k_annual')}, "
        f"base_peak={summary.get('base_peak_kw')} kW "
        f"({summary.get('base_peak_pct_rating')}% rating, "
        f"{summary.get('base_peak_per_home_kw')} kW/home), "
        f"base_floor={summary.get('base_floor_hours')} h/yr"
    )


if __name__ == "__main__":
    main()

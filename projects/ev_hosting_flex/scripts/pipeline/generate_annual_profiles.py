"""Generate the TMY + stochastic annual 8760h profiles for ev_hosting_flex.

Stage 3 of the workflow (RECAL-03/04/11, amends PROF-01/02/03). Reads the
Phase-8/08.1 topology cache JSON sidecars (per-bus nameplate kW, per-bus building
count, the radial downstream map, the feeder selection) and the new
``_stochastic.py`` numeric kernel to emit the TMY heating-degree base + the seeded
K stochastic-EV realization stack plus a governed report:

* ``data/base_load_8760.parquet`` — ``(n_feeder_bus, 8760)`` per-bus TMY
  heating-degree base building load (the addressable-per-bus envelope the
  downstream-sum proxy aggregates, D-02/D-08) — supersedes the deterministic
  parametric winter envelope;
* ``data/ev_stack_K.npy`` — ``(K, 8760)`` per-EV-unit stochastic EV realization
  stack (charger mix, lognormal session energy, evening arrivals, plug-in
  probability), seeded from a single ``np.random.default_rng(SEED)`` so two runs
  are byte-identical (D-05/D-13). Each row is one Monte-Carlo realization's daily
  evening EV shape tiled across the year; the per-bus axis is broadcast at consume
  time (every bus carries the same per-EV-unit shape, scaled by
  ``allocate_ev_per_bus`` at sweep time);
* ``data/ev_load_unit.parquet`` — ``(n_feeder_bus, 8760)`` MEAN-over-K EV unit
  draw kept under the legacy name so the deterministic-path stages 4/5 (the kept
  ``firm_ev_count`` / ``flexible_ev_count`` curtailment curve) still read an
  addressable-per-bus EV unit; the K stack is the stochastic source of truth;
* ``reports/annual_profiles_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-02; never hand-written report JSON).

**Re-baseline note (D-08/D-14/D-15).** This stage supersedes the deterministic
parametric winter envelope (``_profiles.base_load_8760``, Phase-9 D-01) with the
TMY temperature-driven heating-degree base (D-08), and the deterministic EV unit
profile (``_profiles.ev_unit_profile``) with the calibrated stochastic EV
K-realization sampler (D-05/D-15). The re-baseline rationale is carried in both
the report ``summary.divergence_note`` and ``validation.warnings`` so the
verify-phase reads the deliberate, recorded supersession (CLAUDE.md report
contract #4); the EV-stack ``content_sha256`` is the byte-stability tripwire
(D-13).

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas``. This stage reads
ONLY the JSON cache sidecars + the committed TMY CSV (never ``pp_net_cache.pkl``),
so it stays pandapower-free; pandapower enters the study only at Phase-11 AC
validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.ev_hosting_flex.scripts._stochastic import (  # noqa: E402
    ev_realizations,
    tmy_base,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    K,
)

_REBASELINE_NOTE = (
    "Re-baseline (D-08/D-14/D-15): the base building load is now the TMY "
    "temperature-driven heating-degree model (per-home = occupancy-shaped "
    "background + max(0, T_balance - T_out) / R_therm over the committed "
    "Trois-Rivieres TMY), SUPERSEDING the deterministic parametric winter "
    "envelope (Phase-9 D-01 / _profiles.base_load_8760). The EV layer is now a "
    "calibrated stochastic K-realization sampler (charger mix, lognormal session "
    "energy, evening arrivals, plug-in probability), SUPERSEDING the deterministic "
    "evening-window EV unit (_profiles.ev_unit_profile, D-15). The Monte-Carlo is "
    "byte-stable: a single pinned np.random.default_rng(SEED) + fixed K + the "
    "EV-stack content_sha256 tripwire pin the Phase-12 1e-6 baseline (D-13)."
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
            f"ev_hosting_flex stage 3 requires the topology cache sidecar "
            f"{path.name} at {path}, but it is missing. Remediation: re-run "
            "stage 2 (prepare_topology_cache.py) to regenerate the load-aware "
            "cache before generating annual profiles."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _summarize_array(arr: np.ndarray) -> dict[str, object]:
    """Return deterministic sum/max/sha256 stats over a rounded float64 array.

    The ``content_sha256`` over the canonical-bytes array is the byte-stability
    tripwire for the Phase-12 regression baseline (D-13).

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


def derive_annual_profiles(cache_dir: Path, data_dir: Path) -> dict[str, object]:
    """Derive + persist the TMY base + the seeded K stochastic-EV stack.

    Reads the topology cache sidecars (pandapower-free), restricts to the selected
    feeder's load buses (intersection of its downstream set with the load-bus
    sidecars, A3), builds the SORTED per-bus building-count nameplate share, calls
    ``_stochastic.tmy_base`` for the addressable-per-bus heating-degree base and
    ``_stochastic.ev_realizations`` for the seeded K EV stack (single
    ``default_rng(SEED)``), rounds to ``ROUND_DECIMALS``, and writes the base
    parquet, the ``(K, 8760)`` EV stack ``.npy``, and a mean-over-K EV unit parquet
    (kept under the legacy name for the deterministic curtailment curve).

    Args:
        cache_dir: Directory holding the stage-2 JSON cache sidecars.
        data_dir: Directory the artifacts are written to.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.
    """
    nameplate_kw = _load_json(cache_dir / "node_nameplate_kw.json")
    building_count = _load_json(cache_dir / "node_building_count.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    feeder = _load_json(cache_dir / "feeder_selection.json")

    # Read the feeder key at runtime — never hardcode the transformer index (T-09-01).
    feeder_idx = int(feeder["feeder_transformer_idx"])
    feeder_key = f"transformer:{feeder_idx}"
    if feeder_key not in downstream:
        raise ValueError(
            f"ev_hosting_flex stage 3: feeder key {feeder_key!r} from "
            "feeder_selection.json is absent from downstream_bus_map.json. "
            "Remediation: regenerate the topology cache (stage 2) so the feeder "
            "selection and downstream map come from the same net."
        )

    # A3: restrict to the feeder's downstream LOAD buses (intersection with the
    # nameplate sidecar keys), in deterministic SORTED bus order.
    load_buses = {int(b) for b in nameplate_kw}
    feeder_buses = sorted(set(downstream[feeder_key]) & load_buses)
    if not feeder_buses:
        raise ValueError(
            f"ev_hosting_flex stage 3: the selected feeder {feeder_key} has no "
            "downstream load buses in node_nameplate_kw.json. Remediation: verify "
            "the load-aware topology cache was built from the expected feeder."
        )

    nameplate_arr = np.array([nameplate_kw[str(b)] for b in feeder_buses], dtype=DTYPE)
    building_arr = np.array(
        [int(building_count[str(b)]) for b in feeder_buses], dtype=np.int64
    )

    # D-08: the per-bus nameplate share for the heating-degree base is the per-bus
    # HOME COUNT (each home contributes one per_home heating-degree load), so the
    # feeder subtree base aggregates to ~n_homes * per_home (the manuscript anchor).
    nameplate_share = building_arr.astype(DTYPE)

    base = np.round(tmy_base(nameplate_share), ROUND_DECIMALS).astype("float64")

    # D-05/D-13: the seeded stochastic EV K-realization stack. A SINGLE
    # default_rng(SEED) (never the global) drawn in the pinned per-EV order. n_ev=1
    # → the per-EV unit shape; the per-bus EV count is applied at sweep time via
    # allocate_ev_per_bus, so each realization here is one per-EV-per-day shape
    # tiled across the year. n_bus=1: every bus carries the same per-EV unit shape,
    # so we persist the (K, 8760) realization stack and broadcast over buses at
    # consume time (avoids a (K, n_bus, 8760) artifact that is n_bus-fold larger).
    rng = np.random.default_rng(SEED)
    ev_stack_3d = ev_realizations(rng, int(K), n_ev=1, n_bus=1)  # (K, 1, 8760)
    ev_stack = np.round(ev_stack_3d[:, 0, :], ROUND_DECIMALS).astype(
        "float64"
    )  # (K,8760)

    # The MEAN-over-K EV unit kept under the legacy parquet name so the kept
    # deterministic curtailment curve (firm_ev_count / flexible_ev_count) still
    # reads an addressable-per-bus EV unit; the K stack is the stochastic source.
    ev_unit_mean = np.round(ev_stack.mean(axis=0), ROUND_DECIMALS).astype(
        "float64"
    )  # (8760,)
    ev_per_bus_mean = np.round(
        np.broadcast_to(ev_unit_mean, (len(feeder_buses), ev_unit_mean.shape[0])),
        ROUND_DECIMALS,
    ).astype("float64")

    data_dir.mkdir(parents=True, exist_ok=True)
    columns = [f"h{h}" for h in range(base.shape[1])]
    base_path = data_dir / "base_load_8760.parquet"
    ev_path = data_dir / "ev_load_unit.parquet"
    ev_stack_path = data_dir / "ev_stack_K.npy"
    pd.DataFrame(base, index=feeder_buses, columns=columns).astype(
        "float64"
    ).to_parquet(base_path)
    pd.DataFrame(ev_per_bus_mean, index=feeder_buses, columns=columns).astype(
        "float64"
    ).to_parquet(ev_path)
    # Persist the (K, 8760) stochastic EV stack as a deterministic-bytes .npy.
    np.save(ev_stack_path, ev_stack)

    return {
        "artifact_paths": [base_path, ev_path, ev_stack_path],
        "summary": {
            "n_feeder_bus": len(feeder_buses),
            "feeder_key": feeder_key,
            "feeder_transformer_idx": feeder_idx,
            "total_nameplate_kw": round(float(nameplate_arr.sum()), ROUND_DECIMALS),
            "total_building_count": int(building_arr.sum()),
            "downstream_home_count": int(building_arr.sum()),
            "k_realizations": int(K),
            "seed": int(SEED),
            "base_load": _summarize_array(base),
            "ev_load_unit": _summarize_array(ev_per_bus_mean),
            "ev_stack": _summarize_array(ev_stack),
            "ev_stack_content_sha256": _summarize_array(ev_stack)["content_sha256"],
            "divergence_note": _REBASELINE_NOTE,
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full annual-profiles stage: derive + parquet/npy + governed report.

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

    derived = derive_annual_profiles(effective_cache_dir, effective_data_dir)
    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]

    return script.write_report(
        "annual_profiles_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={
            "valid": True,
            "errors": [],
            "warnings": [_REBASELINE_NOTE],
        },
    )


def main() -> None:
    """CLI entry point for the annual-profiles stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Generated annual profiles + report: "
        f"feeder_key={summary.get('feeder_key')}, "
        f"n_feeder_bus={summary.get('n_feeder_bus')}, "
        f"K={summary.get('k_realizations')}, "
        f"ev_stack_sha256={summary.get('ev_stack_content_sha256', '')[:12]}"
    )


if __name__ == "__main__":
    main()

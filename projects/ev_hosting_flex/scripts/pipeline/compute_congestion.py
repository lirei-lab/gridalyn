"""Compute the design-day transformer-overload risk + firm EV hosting limit.

Stage 4 of the v1.3 generative-MC pipeline (CONG-01/02/03). Retargeted in Phase 14
from the retired annual 8760h radial **line** downstream-sum proxy to the design-day
**transformer**-overload statement over the Phase-13 Monte-Carlo ensemble. Reads ONLY
the Phase-13 ``.npy`` artifacts + the stage-2 topology-cache JSON sidecars (GUARD-02 —
never the pickled net), computes ``P(overload)`` over the ``K`` design-day realizations
at each integer EV count, pins the firm denominator (= largest EV count with
``P(loading > 1) <= FIRM_PCONG_TOLERANCE``), and emits the named artifacts plus a
governed report:

* ``data/transformer_risk.parquet`` — ``(K,)`` per-realization peak %rating at the
  firm EV count (float64, rounded) — the MC load distribution / histogram source
  (CONG-03);
* ``json/p_overload_curve.json`` — the ``P(overload)``-vs-penetration curve, rows
  ``{ev_count, ev_per_home, p_overload}`` (CONG-03 evidence);
* ``json/firm_hosting.json`` — the firm denominator: the 5 keys Phase 15/16 read
  (``firm_ev_count``, ``firm_penetration``, ``downstream_home_count``, ``feeder_key``,
  ``feeder_transformer_modeled_kw``) PLUS ``p_overload_curve`` / ``ev_sweep`` /
  ``firm_pcong_tolerance`` / ``threshold_convention`` / ``k_realizations``;
* ``reports/congestion_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-02; never hand-written report JSON), whose summary
  carries the framing-shift ``divergence_note`` (also in ``validation.warnings``).

**The unit of congestion is the MODELED small HQ LV transformer (D-01).** The rating
is the MODELED ``TRANSFORMER_KVA × POWER_FACTOR`` (71.25, decoupled from the twin's
physical nameplate, D-02), reused from ``_FEEDER_TRANSFORMER_KW`` — NOT recomputed from
the cache subtree (the producer uses the identical ``_USABLE_RATING_KW``).

``K`` is read from ``q_real.shape[0]`` (the design-day ``K_DESIGN`` = 60), NEVER from
``config.K`` (the retired annual count = 1000). ``q_design.npy`` is the Phase-15
day-ahead controller input and is NOT consumed here (the firm denominator is a
``Q_real`` statement).

Pitfall (D-13 / SEAL-01): cap BLAS threads (``OMP_NUM_THREADS=1`` recommended at the
shell) around the K-fold reduce so the byte-stability tripwire does not flicker;
``ROUND_DECIMALS=6`` pre-write rounding pins the comparator.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` / ``lightsim2grid``.
This stage is pure-numpy + pandas/JSON IO.
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

from projects.ev_hosting_flex.scripts._congestion import (  # noqa: E402
    firm_transformer_count,
    is_overloaded,
    transformer_loading,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    FIRM_PCONG_TOLERANCE,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)

# The modeled small HQ LV transformer rating in kW (D-01/D-02): TRANSFORMER_KVA at
# POWER_FACTOR. Overload keys off THIS modeled rating, reused from the producer's
# identical _USABLE_RATING_KW — never recomputed from the cache subtree size.
_FEEDER_TRANSFORMER_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)

# Non-degeneracy band on the integer firm EV count (Pitfall 2): firm must be neither
# 0 (already congested at 0 EVs — a wrong modeled rating) nor pinned at the ev_max=18
# ceiling (the sweep never crossed). firm=3 at the locked calibration sits inside.
_FIRM_EV_MIN = 1
_FIRM_EV_MAX = 9


def _load_json(path: Path) -> dict:
    """Load a required JSON cache sidecar, failing loudly if it is missing.

    Args:
        path: Path to the JSON artifact produced by an upstream stage.

    Returns:
        The parsed JSON mapping.

    Raises:
        FileNotFoundError: If the artifact is missing (stale/incomplete cache).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 4 (compute_congestion) requires {path.name} at "
            f"{path}, but it is missing. Remediation: re-run stage 2 "
            "(prepare_topology_cache.py) and stage 3 (generate_design_day_mc.py) "
            "before computing congestion."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_npy(path: Path, stage_hint: str) -> np.ndarray:
    """Load a required Phase-13 ``.npy`` artifact, failing loudly if it is missing.

    Args:
        path: Path to the ``.npy`` artifact produced by stage 3.
        stage_hint: A short description of the artifact for the error message.

    Returns:
        The loaded array as float64.

    Raises:
        FileNotFoundError: If the artifact is missing (stale/incomplete stage 3).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 4 (compute_congestion) requires the {stage_hint} "
            f"{path.name} at {path}, but it is missing. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py) so q_real.npy / ev_pool_design.npy are "
            "written to the project data dir (the gitignored cache lives only in the "
            "main tree — run without a worktree)."
        )
    return np.load(path).astype(DTYPE)


def _write_json(path: Path, payload: object) -> Path:
    """Write ``payload`` to ``path`` as deterministic, sorted-key JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _feeder_home_count(cache_dir: Path) -> tuple[str, int]:
    """Return the (feeder_key, downstream home count) from the cache sidecars.

    Reads ONLY the JSON cache sidecars (GUARD-02; never ``pp_net_cache.pkl``): the
    feeder transformer index from ``feeder_selection.json`` at runtime (never
    hardcoded), its downstream bus set from ``downstream_bus_map.json``, and the
    per-bus building count from ``node_building_count.json``. Mirrors the producer's
    ``generate_design_day_mc._feeder_home_count``.

    Args:
        cache_dir: Directory holding the stage-2 JSON cache sidecars.

    Returns:
        A tuple ``(feeder_key, downstream_home_count)`` — e.g.
        ``("transformer:62", 7)`` on the committed idx-62 twin.

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
            f"ev_hosting_flex stage 4 (compute_congestion): feeder key "
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
    return feeder_key, int(homes)


def _content_sha256(arr: np.ndarray) -> str:
    """Return the canonical-bytes sha256 of a rounded float64 array (SEAL-01)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0  # kill signed zero
    return hashlib.sha256(canonical.tobytes()).hexdigest()


_DIVERGENCE_NOTE = (
    "Framing shift (CONG-01/02/03, milestone re-baseline policy): the firm "
    "denominator is now the design-day transformer-overload statement firm = "
    "largest EV count with P(transformer loading > 1) <= FIRM_PCONG_TOLERANCE over "
    "the K design-day realizations (strict-> on loading = (Sigma building + Sigma "
    "EV) / (TRANSFORMER_KVA * POWER_FACTOR) = 71.25 kW). It SUPERSEDES the prior "
    "annual line-proxy firm (the radial downstream-sum loading proxy + the "
    "partial-coincidence EV-coincidence blend over the retired (K, n_bus, 8760) "
    "annual ensemble). No committed regression baseline exists yet (the 1e-6 "
    "baseline is born in Phase 17), so the headline shift breaks nothing; the "
    "round-before-write float64 arrays + the firm_hosting / transformer_risk "
    "content_sha256 tripwires pin run-vs-run byte stability now. If the governed "
    "ensemble lands at firm 2 or 4 (still non-degenerate) rather than the probed "
    "3, that +/-1 is the documented framing shift recorded here, NOT a trigger to "
    "re-tune the locked R_QUEBEC / P_HEAT_QUEBEC calibration."
)


def derive_congestion(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the design-day transformer firm + risk distribution.

    Loads the Phase-13 ``q_real.npy`` (EV-free transformer-load ensemble) and
    ``ev_pool_design.npy`` (nested cumulative MDPI EV pool), reads ``K`` from
    ``q_real.shape[0]`` (never ``config.K``), reads the feeder home count from the
    cache sidecars (pandapower-free, GUARD-02), runs the new transformer-overload
    kernel to pin the firm EV count (last-in-tolerance), and writes the firm-hosting
    JSON (5-key contract preserved) + the transformer risk parquet + the
    ``P(overload)`` curve JSON.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars.
        data_dir: Directory the Phase-13 ``.npy`` live in / the risk parquet is
            written to.
        json_dir: Directory the firm-hosting + curve JSON are written to.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict (CONG-01/02/03).
    """
    # ── Load the Phase-13 design-day ensemble (read K from the array) ──
    q_real = _load_npy(data_dir / "q_real.npy", "design-day Q_real ensemble")
    ev_pool = _load_npy(data_dir / "ev_pool_design.npy", "nested-EV design pool")
    # q_design.npy is the Phase-15 controller input — NOT consumed here (RESEARCH Q2).

    if q_real.ndim != 2:
        raise ValueError(
            "ev_hosting_flex stage 4: q_real.npy must be a 2-D (K, n_steps) array "
            f"but has shape {q_real.shape}. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py)."
        )
    if ev_pool.ndim != 3 or ev_pool.shape[0] != q_real.shape[0]:
        raise ValueError(
            "ev_hosting_flex stage 4: ev_pool_design.npy must be a 3-D "
            f"(K, ev_max+1, n_steps) array with K matching q_real (K={q_real.shape[0]}) "
            f"but has shape {ev_pool.shape}. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py)."
        )

    K = int(q_real.shape[0])  # 60 — NEVER config.K (=1000)
    n_steps = int(q_real.shape[1])
    ev_max = int(ev_pool.shape[1] - 1)  # 18
    rating_kw = _FEEDER_TRANSFORMER_KW  # 71.25 (pf pinned, reused from the producer)

    # ── Feeder home count (GUARD-02, JSON sidecars only) ──
    feeder_key, downstream_home_count = _feeder_home_count(cache_dir)
    if downstream_home_count <= 0:
        raise ValueError(
            "ev_hosting_flex stage 4: the selected feeder "
            f"{feeder_key} has {downstream_home_count} downstream homes. "
            "Remediation: verify the load-aware topology cache was built from the "
            "expected idx-62 feeder (stage 2)."
        )

    # ── The firm gate: largest EV count with P(overload) <= tolerance (CONG-02) ──
    result = firm_transformer_count(
        q_real, ev_pool, rating_kw, float(FIRM_PCONG_TOLERANCE), ev_max
    )
    firm_ev = int(result["firm_ev_count"])
    firm_penetration = firm_ev / downstream_home_count  # EV/home (still fractional)

    # Degenerate-firm guard re-expressed as an integer-count check (Pitfall 2): the
    # firm count must be non-degenerate (neither 0 nor pinned at the ev_max ceiling)
    # so the Phase-15/16 denominator is a real crossing. firm=3 sits inside [1, 9].
    if not (_FIRM_EV_MIN <= firm_ev <= _FIRM_EV_MAX):
        raise ValueError(
            "ev_hosting_flex stage 4: degenerate firm_ev_count="
            f"{firm_ev} for feeder {feeder_key} (must satisfy {_FIRM_EV_MIN} <= "
            f"firm_ev_count <= {_FIRM_EV_MAX}; ev_max={ev_max}). firm_ev_count==0 "
            "means the transformer is already overloaded at 0 EVs (a wrong modeled "
            f"rating); firm_ev_count pinned near ev_max={ev_max} means the sweep "
            "never crossed P(overload)=FIRM_PCONG_TOLERANCE. Remediation: verify the "
            "design-day ensemble (stage 3) reproduces the locked operating point — "
            "do NOT re-tune the locked R_QUEBEC / P_HEAT_QUEBEC calibration to force "
            "a particular firm; surface a +/-1 framing shift via the divergence_note."
        )

    # ── CONG-03 risk distribution: per-realization peak %rating at the firm count ──
    total_firm = q_real + ev_pool[:, firm_ev, :]  # (K, n_steps)
    peak_pct = 100.0 * total_firm.max(axis=1) / rating_kw  # (K,) histogram source
    peak_pct_rounded = np.round(peak_pct, ROUND_DECIMALS).astype("float64")

    data_dir.mkdir(parents=True, exist_ok=True)
    risk_path = data_dir / "transformer_risk.parquet"
    pd.DataFrame({"peak_pct_rating": peak_pct_rounded}).to_parquet(risk_path)

    # ── CONG-03 P(overload)-vs-penetration curve JSON ──
    p_curve = [float(round(v, ROUND_DECIMALS)) for v in result["p_overload_curve"]]
    curve_rows = [
        {
            "ev_count": int(n),
            "ev_per_home": float(round(n / downstream_home_count, ROUND_DECIMALS)),
            "p_overload": p_curve[n],
        }
        for n in result["ev_sweep"]
    ]
    curve_path = _write_json(json_dir / "p_overload_curve.json", curve_rows)

    # ── firm_hosting.json — PRESERVE the 5 downstream keys (Pitfall 1) ──
    firm_payload = {
        # The 5 keys Phase 15/16 read (preserve verbatim):
        "firm_ev_count": firm_ev,
        "firm_penetration": float(round(firm_penetration, ROUND_DECIMALS)),
        "downstream_home_count": int(downstream_home_count),
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
        # New transformer-framing keys (replace old p_cong / p_cong_at_firm /
        # penetration_sweep, which have NO downstream consumer):
        "p_overload_curve": p_curve,
        "ev_sweep": [int(n) for n in result["ev_sweep"]],
        "firm_pcong_tolerance": float(FIRM_PCONG_TOLERANCE),
        "threshold_convention": result["threshold_convention"],
        "k_realizations": K,
    }
    firm_path = _write_json(json_dir / "firm_hosting.json", firm_payload)

    # P(overload) at the firm count (<= tolerance by construction) for the summary.
    p_overload_at_firm = p_curve[firm_ev] if firm_ev < len(p_curve) else None
    # Base (EV-free) peak %rating stats — the locked operating-point evidence.
    base_peak_pct = 100.0 * q_real.max(axis=1) / rating_kw  # (K,)

    return {
        "artifact_paths": [risk_path, curve_path, firm_path],
        "summary": {
            "firm_ev_count": firm_ev,
            "firm_penetration": float(round(firm_penetration, ROUND_DECIMALS)),
            "downstream_home_count": int(downstream_home_count),
            "feeder_key": feeder_key,
            "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
            "firm_pcong_tolerance": float(FIRM_PCONG_TOLERANCE),
            "p_overload_at_firm": p_overload_at_firm,
            "threshold_convention": result["threshold_convention"],
            "k_realizations": K,
            "n_steps": n_steps,
            "ev_max": ev_max,
            "base_peak_pct_rating_p50": round(
                float(np.percentile(base_peak_pct, 50)), ROUND_DECIMALS
            ),
            "firm_peak_pct_rating_p50": round(
                float(np.percentile(peak_pct_rounded, 50)), ROUND_DECIMALS
            ),
            "firm_peak_pct_rating_max": round(
                float(peak_pct_rounded.max()), ROUND_DECIMALS
            ),
            # Byte-stability tripwire over the rounded risk array (SEAL-01).
            "transformer_risk_content_sha256": _content_sha256(peak_pct_rounded),
            "divergence_note": _DIVERGENCE_NOTE,
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full congestion stage: derive + parquet/JSON + governed report.

    Recommended: cap BLAS threads (``OMP_NUM_THREADS=1`` at the shell) so the K-fold
    reduce stays byte-stable across runs.

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
    json_dir = script.path("outputs/json")

    derived = derive_congestion(effective_cache_dir, effective_data_dir, json_dir)
    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]
    divergence_note = summary["divergence_note"]  # type: ignore[index]

    return script.write_report(
        "congestion_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": [divergence_note]},
    )


def main() -> None:
    """CLI entry point for the congestion stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Computed transformer congestion + report: "
        f"firm_ev_count={summary.get('firm_ev_count')}, "
        f"firm_penetration={summary.get('firm_penetration')} EV/home, "
        f"p_overload_at_firm={summary.get('p_overload_at_firm')}, "
        f"base_p50%rating={summary.get('base_peak_pct_rating_p50')}, "
        f"K={summary.get('k_realizations')}"
    )


if __name__ == "__main__":
    main()

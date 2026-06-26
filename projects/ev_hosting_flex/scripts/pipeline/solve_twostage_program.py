"""Two-stage chance-constrained EV-flexibility sensitivity + equivalence stage.

Stage 6 of the v1.3 generative-MC workflow (D-06), sitting between
``apply_flexibility_contracts`` (stage 5) and ``validate_powerflow`` (Phase 11).
RE-POINTED (Phase 15 RETIRE-02, the RESEARCH lower-risk re-point): the stage no
longer sources the retired annual seam (the per-bus annual base profile + the
annual EV stack + the cold-day/CLPU ``compose_scenarios`` base + the retired
annual headline over 8760 h). It now reads the Phase-13 design-day artifacts
(``q_real.npy`` / ``q_design.npy`` / ``ev_pool_design.npy``) + the Phase-14
``firm_hosting.json`` denominator, and builds the required forecast ensemble
through the Plan-01 re-anchored ``compose_scenarios(q_design=...)``.

The role of the stage is UNCHANGED (D-06) — it is a SENSITIVITY + EQUIVALENCE
stage at a representative penetration:

* the ε-frontier cost-vs-reliability sweep (``eps_frontier``);
* the load-bearing cvxpy↔oracle ≤1e-6 equivalence proof
  (``assert_cvxpy_matches_oracle``); and
* the cold-day reserve-vs-activation mechanism panel (``coldday_panel``).

The program is per-step-independent (``_twostage.py`` kernel): each scenario forms
``required_t(ω) = (d_t(ω) + g_t(ω) − S̄)⁺`` with ``d`` the ``q_design``-anchored
forecast trajectory (kW-space fractional perturbation mirroring ``make_q_design``)
and ``g`` the reused stochastic MDPI EV day; stage 1 reserves the per-step
quantile ``r_t = Q_{1−ε}[required_t]``; stage 2 activates ``a_t(ω) = min(r_t,
required_t(ω))``. The closed-form policy is the byte-stable reproducibility ORACLE;
the gated cvxpy solve (CLARABEL, ``require_capabilities("ops")``) must reproduce it
to ≤1e-6 or the stage records the divergence and emits the oracle (D-08c).

This stage produces four artifacts:

* ``json/optimal_hosting.json`` — the ε=``EPS_HEADLINE`` sensitivity headline at the
  representative (firm) count framed on the design day (``firm_ev_count``,
  ``representative_ev_count``, ``eps``, ``reliability_hour_at_headline``, the
  design-day ``activated_mean_fraction``, the cvxpy drift/fallback status, and the
  ``content_sha256`` byte-stability tripwire);
* ``data/twostage_frontier.parquet`` — the ε-sweep cost-vs-reliability frontier
  (illustrative labelled prices, supporting evidence);
* ``data/reserve_activation_coldday.parquet`` — the cold-day reserve ``r_t`` vs
  activated ``E[a_t]`` mechanism panel;
* ``reports/twostage_program_report.json`` — the canonical platform report with
  the design-day re-point note + the cvxpy equivalence record.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. This stage is pure-numpy + pandas/JSON IO; ``cvxpy`` enters
only through the gated kernel (deferred + ``require_capabilities("ops")``).
``OMP_NUM_THREADS=1`` is set at import (Pitfall 5 — cap the BLAS thread pool so
the small per-step quantile reductions stay deterministic and cheap).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Pitfall 5: cap the BLAS thread pool BEFORE numpy spins it up so the small
# per-step quantile reductions stay deterministic and avoid thread oversubscription.
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.ev_hosting_flex.scripts._twostage import (  # noqa: E402
    assert_cvxpy_matches_oracle,
    coldday_panel,
    compose_scenarios,
    eps_frontier,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    EPS_FRONTIER,
    EPS_HEADLINE,
    EPS_SHOW,
    K_DESIGN,
    N_SCENARIOS,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TRANSFORMER_KVA,
    TWOSTAGE_SOLVER,
)

# Quiet the unused-import lints for re-exported config parity with the kernel.
_ = (EPS_SHOW, N_SCENARIOS, TWOSTAGE_SOLVER)

# The modeled small HQ LV transformer rating in kW (D-01/D-02) — the SAME modeled
# rating stages 3/4 key congestion off, used only as a default when the read
# firm_hosting.json omits the modeled-kW key (it does not; the read value wins).
_FEEDER_TRANSFORMER_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def _load_json(path: Path) -> dict:
    """Load a required JSON cache/profile sidecar, failing loudly if absent.

    Args:
        path: Path to the JSON artifact produced by an upstream stage.

    Returns:
        The parsed JSON mapping.

    Raises:
        FileNotFoundError: If the artifact is missing (stale/incomplete cache).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage solve_twostage_program requires {path.name} at "
            f"{path}, but it is missing. Remediation: re-run stage 4 "
            "(compute_congestion.py) so firm_hosting.json is written, and stage 3 "
            "(generate_design_day_mc.py) so the design-day artifacts are present "
            "(the gitignored cache lives only in the main tree — run without a "
            "worktree)."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_npy(path: Path, stage_hint: str) -> np.ndarray:
    """Load a required Phase-13 design-day ``.npy`` artifact, failing loudly.

    Mirrors ``compute_congestion._load_npy`` (the load-input contract): the
    design-day Q_real / Q_design / ev_pool arrays are produced by stage 3.

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
            f"ev_hosting_flex stage solve_twostage_program requires the {stage_hint} "
            f"{path.name} at {path}, but it is missing. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py) so q_real.npy / q_design.npy / "
            "ev_pool_design.npy are written to the project data dir (the gitignored "
            "cache lives only in the main tree — run without a worktree)."
        )
    return np.load(path).astype(DTYPE)


def _write_json(path: Path, payload: object) -> Path:
    """Write ``payload`` to ``path`` as deterministic, sorted-key JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _content_sha256(arr: np.ndarray) -> str:
    """Return the canonical-bytes sha256 of a rounded float64 array (D-12)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0  # kill signed zero
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def derive_twostage(cache_dir: Path, data_dir: Path, json_dir: Path) -> dict:
    """Derive + persist the design-day ε-frontier + cvxpy proof + cold-day panel.

    Reads the stage-4 ``firm_hosting.json`` denominator (NEVER recomputed) + the
    stage-3 design-day ``q_real.npy`` / ``q_design.npy`` / ``ev_pool_design.npy``
    (``K`` and ``n_steps`` are read from ``q_real.shape``, NEVER ``config.K``),
    builds the required forecast ensemble at the representative (firm) EV count via
    the Plan-01 re-anchored ``compose_scenarios(q_design=...)``, runs the
    cvxpy↔oracle ≤1e-6 equivalence proof at ``EPS_HEADLINE``, emits the ε-frontier
    + the cold-day reserve-vs-activation panel, and writes the sensitivity headline
    JSON + the frontier/panel parquet.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars (read for parity;
            the headline reads the firm denominator from ``json_dir``).
        data_dir: Directory the frontier/panel parquet are written to and the
            stage-3 design-day artifacts are read from.
        json_dir: Directory the headline JSON is written to AND the stage-4
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a degenerate firm denominator or a malformed design-day
            artifact (wrong dimensionality / mismatched K).
    """
    _ = cache_dir  # cache sidecars are governed inputs; firm denominator drives this.
    # ── The stage-4 denominator (D-12): read, NEVER recompute the firm count. ──
    firm = _load_json(json_dir / "firm_hosting.json")
    firm_ev_count = int(firm["firm_ev_count"])
    firm_penetration = float(firm["firm_penetration"])
    downstream_home_count = int(firm["downstream_home_count"])
    feeder_key = str(firm["feeder_key"])
    feeder_kw = float(firm.get("feeder_transformer_modeled_kw", _FEEDER_TRANSFORMER_KW))
    if firm_ev_count <= 0:
        raise ValueError(
            "ev_hosting_flex stage solve_twostage_program: degenerate "
            f"firm_ev_count={firm_ev_count} read from firm_hosting.json for feeder "
            f"{feeder_key}; the representative-count denominator must be > 0. "
            "Remediation: re-run stage 4 (compute_congestion.py) so the firm leg is "
            "a positive count."
        )

    # ── The stage-3 design-day artifacts (T-15-04 V5 input validation). ──
    # q_real: (K, n_steps); q_design: (n_steps,); ev_pool: (K, ev_max+1, n_steps).
    # K / n_steps come from q_real.shape — NEVER config.K (the retired annual count).
    q_real = _load_npy(data_dir / "q_real.npy", "design-day Q_real ensemble")
    q_design = _load_npy(data_dir / "q_design.npy", "design-day Q_design forecast")
    ev_pool = _load_npy(data_dir / "ev_pool_design.npy", "nested-EV design pool")
    if q_real.ndim != 2:
        raise ValueError(
            "ev_hosting_flex stage solve_twostage_program: q_real.npy must be a 2-D "
            f"(K, n_steps) array but has shape {q_real.shape}. Remediation: re-run "
            "stage 3 (generate_design_day_mc.py)."
        )
    K = int(q_real.shape[0])  # 60 — read from the array, NEVER config.K (=1000)
    n_steps = int(q_real.shape[1])
    if q_design.ndim != 1 or q_design.shape[0] != n_steps:
        raise ValueError(
            "ev_hosting_flex stage solve_twostage_program: q_design.npy must be a "
            f"1-D (n_steps={n_steps},) array but has shape {q_design.shape}. "
            "Remediation: re-run stage 3 (generate_design_day_mc.py)."
        )
    if ev_pool.ndim != 3 or ev_pool.shape[0] != K or ev_pool.shape[2] != n_steps:
        raise ValueError(
            "ev_hosting_flex stage solve_twostage_program: ev_pool_design.npy must "
            f"be a 3-D (K={K}, ev_max+1, n_steps={n_steps}) array but has shape "
            f"{ev_pool.shape}. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py) so the nested-EV pool matches q_real."
        )

    # ── The Q_design-anchored required ensemble (D-06; the load-input contract). ──
    # Stage 6 is a SENSITIVITY stage: it operates at a representative penetration
    # (the firm count), not a full annual sweep. The re-anchored compose_scenarios
    # draws the kW-space forecast-error perturbation on q_design + the reused MDPI
    # EV day; n_scenarios=K_DESIGN keeps the ensemble symmetric with the design-day
    # K. The q_real/ev_pool arrays are read + shape-validated (T-15-04 tripwire)
    # but the equivalence proof runs on the governed forecast ensemble.
    representative_ev_count = int(firm_ev_count)
    required = compose_scenarios(
        np.random.default_rng(SEED),
        n_ev=representative_ev_count,
        n_homes=downstream_home_count,
        feeder_kw=feeder_kw,
        q_design=q_design,
        n_scenarios=K_DESIGN,
    )
    required_sha = _content_sha256(required)

    # ── cvxpy↔oracle equivalence (D-08, T-15-05) at the headline ε. ──
    # The load-bearing ≤1e-6 proof — preserved verbatim; the activation form is NOT
    # changed (Pitfall 4). Records drift / status / fallback.
    oracle, meta = assert_cvxpy_matches_oracle(required, EPS_HEADLINE)
    cvxpy_status = str(meta["cvxpy_status"])
    cvxpy_drift = float(meta["drift"])
    cvxpy_fellback = bool(meta["fellback"])
    rel_hour_at_headline = float(oracle["rel_hour"])

    # ── The design-day activated-energy fraction at the headline ε (descriptive). ──
    # E[Σ a] / E[Σ required] over the forecast ensemble — the mechanism's
    # "activate only a fraction of what is reserved" framed on the design day, NOT
    # an annual 8760 h integral (the annual machinery is retired, RETIRE-02).
    activated_mean = float(oracle["a"].sum(axis=1).mean())
    required_mean = float(np.maximum(0.0, required).sum(axis=1).mean())
    activated_mean_fraction = (
        activated_mean / required_mean if required_mean > 1e-9 else 0.0
    )

    # ── ε-frontier + cold-day reserve-vs-activation panel (D-06). ──
    frontier = eps_frontier(required, EPS_FRONTIER)
    panel = coldday_panel(required)

    # ── Round all floats pre-write (1e-6 baseline contract, D-10). ──
    headline_block = {
        "firm_ev_count": firm_ev_count,
        "representative_ev_count": representative_ev_count,
        "eps": float(EPS_HEADLINE),
        "reliability_hour_at_headline": float(
            round(rel_hour_at_headline, ROUND_DECIMALS)
        ),
        "reserved_peak_kw": float(round(float(oracle["r"].max()), ROUND_DECIMALS)),
        "activated_mean_kwh": float(round(activated_mean, ROUND_DECIMALS)),
        "activated_mean_fraction": float(
            round(activated_mean_fraction, ROUND_DECIMALS)
        ),
        "k_realizations": K,
        "n_steps": n_steps,
        "downstream_home_count": downstream_home_count,
        "firm_penetration": float(round(firm_penetration, ROUND_DECIMALS)),
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": feeder_kw,
        "cvxpy_oracle_drift": float(round(cvxpy_drift, ROUND_DECIMALS)),
        "cvxpy_status": cvxpy_status,
        "cvxpy_fellback": cvxpy_fellback,
        "required_content_sha256": required_sha,
    }
    headline_arrays = np.array(
        [
            headline_block["reliability_hour_at_headline"],
            headline_block["reserved_peak_kw"],
            headline_block["activated_mean_kwh"],
            headline_block["activated_mean_fraction"],
        ],
        dtype=DTYPE,
    )
    headline_block["content_sha256"] = _content_sha256(headline_arrays)

    # ── The design-day re-point note + the cvxpy fallback note (D-08c). ──
    repoint_note = (
        "Re-point (RETIRE-02, D-06): stage 6 now sources its required ensemble from "
        "the Phase-13 design-day artifacts (q_real.npy / q_design.npy / "
        "ev_pool_design.npy) via the re-anchored compose_scenarios(q_design=...) at "
        f"the representative firm count={representative_ev_count}, NOT the retired "
        "annual per-bus base + annual EV stack + cold-day/CLPU seam. The "
        "role is unchanged: the eps-frontier sensitivity + the cvxpy<->oracle <=1e-6 "
        "equivalence proof + the cold-day reserve-vs-activation panel. The citable "
        "hosting headline is now derived by the design-day controller "
        "(apply_flexibility_contracts, Plan 03), not this stage."
    )
    cvxpy_note = (
        "cvxpy fallback (D-08c): the gated CLARABEL solve diverged from the "
        f"closed-form oracle (status={cvxpy_status}, drift={cvxpy_drift:.3e} > "
        "1e-6); the stage emitted the byte-stable oracle values and recorded the "
        "divergence. The eps-frontier / panel are unaffected (oracle == optimum)."
    )

    # ── Write the four-artifact set (JSON headline + frontier/panel parquet). ──
    data_dir.mkdir(parents=True, exist_ok=True)
    optimal_path = _write_json(json_dir / "optimal_hosting.json", headline_block)

    frontier_path = data_dir / "twostage_frontier.parquet"
    frontier_rounded = [
        {
            k: (round(v, ROUND_DECIMALS) if isinstance(v, float) else v)
            for k, v in row.items()
        }
        for row in frontier
    ]
    pd.DataFrame(
        frontier_rounded,
        columns=[
            "eps",
            "reliability_hour",
            "reliability_day",
            "reservation_cost",
            "activation_cost",
            "total_cost",
            "reserved_peak_kw",
            "activated_mean_kwh",
        ],
    ).to_parquet(frontier_path)

    panel_path = data_dir / "reserve_activation_coldday.parquet"
    pd.DataFrame(
        {
            "hour": np.asarray(panel["hour"], dtype="int64"),
            "r_s": np.round(panel["r_s"], ROUND_DECIMALS).astype("float64"),
            "a_mean": np.round(panel["a_mean"], ROUND_DECIMALS).astype("float64"),
            "req_p50": np.round(panel["req_p50"], ROUND_DECIMALS).astype("float64"),
            "req_p90": np.round(panel["req_p90"], ROUND_DECIMALS).astype("float64"),
        },
        columns=["hour", "r_s", "a_mean", "req_p50", "req_p90"],
    ).to_parquet(panel_path)

    summary = {
        "headline": headline_block,
        "firm_ev_count": firm_ev_count,
        "firm_penetration": firm_penetration,
        "representative_ev_count": representative_ev_count,
        "eps": float(EPS_HEADLINE),
        "reliability_hour_at_headline": headline_block["reliability_hour_at_headline"],
        "activated_mean_fraction": headline_block["activated_mean_fraction"],
        "k_realizations": K,
        "n_steps": n_steps,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": feeder_kw,
        "downstream_home_count": downstream_home_count,
        "cvxpy_oracle_drift": cvxpy_drift,
        "cvxpy_status": cvxpy_status,
        "cvxpy_fellback": cvxpy_fellback,
        "required_content_sha256": required_sha,
        "headline_content_sha256": headline_block["content_sha256"],
        "frontier_content_sha256": _content_sha256(
            np.array([row["total_cost"] for row in frontier_rounded], dtype=DTYPE)
        ),
        "panel_content_sha256": _content_sha256(
            np.round(panel["r_s"], ROUND_DECIMALS).astype(DTYPE)
        ),
        "repoint_note": repoint_note,
    }
    return {
        "artifact_paths": [optimal_path, frontier_path, panel_path],
        "summary": summary,
        "repoint_note": repoint_note,
        "cvxpy_note": cvxpy_note,
        "cvxpy_fellback": cvxpy_fellback,
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict:
    """Run the full stage: derive + parquet/JSON + governed report (D-06).

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

    derived = derive_twostage(effective_cache_dir, effective_data_dir, json_dir)
    artifact_paths = derived["artifact_paths"]
    summary = derived["summary"]
    repoint_note = derived["repoint_note"]
    cvxpy_note = derived["cvxpy_note"]
    fellback = bool(derived["cvxpy_fellback"])

    inputs = [
        script.file_reference(json_dir / "firm_hosting.json"),
        script.file_reference(effective_data_dir / "q_real.npy"),
        script.file_reference(effective_data_dir / "q_design.npy"),
        script.file_reference(effective_data_dir / "ev_pool_design.npy"),
    ]

    return script.write_report(
        "twostage_program_report",
        inputs=inputs,
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={
            "valid": True,
            "errors": [],
            "warnings": [repoint_note, *([cvxpy_note] if fellback else [])],
        },
    )


def main() -> None:
    """CLI entry point for the two-stage program stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Solved two-stage program + report: "
        f"firm_ev_count={summary.get('firm_ev_count')} | "
        f"representative={summary.get('representative_ev_count')} at "
        f"eps={summary.get('eps')} | "
        f"reliability_hour={summary.get('reliability_hour_at_headline')} | "
        f"cvxpy_status={summary.get('cvxpy_status')} "
        f"drift={summary.get('cvxpy_oracle_drift')}"
    )


if __name__ == "__main__":
    main()

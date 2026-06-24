"""Solve the two-stage chance-constrained EV-flexibility program (the optimal headline).

Stage 6 of the workflow (TWOSTAGE-04..07), sitting between
``apply_flexibility_contracts`` (stage 5) and ``validate_powerflow`` (Phase 11).
The optimal sibling of the descriptive stage-5 curves: it reads ONLY the
stage-4 ``firm_hosting.json`` denominator, the stage-3 per-bus base profile +
the stage-3 ``(K, 8760)`` stochastic EV stack, and the committed TMY (GUARD-02 —
never the pickled net), and emits the study's OPTIMAL hosting headline.

The program is per-hour-independent (``_twostage.py`` kernel): each scenario
forms ``required_t(ω) = (d_t(ω) + g_t(ω) − S̄)⁺``; stage 1 reserves the per-hour
quantile ``r_t = Q_{1−ε}[required_t]`` day-ahead; stage 2 activates only
``a_t(ω) = min(r_t, required_t(ω))`` in real time. The closed-form policy is the
byte-stable reproducibility ORACLE; the gated cvxpy solve (CLARABEL,
``require_capabilities("ops")``) must reproduce it to ≤1e-6 or the stage falls
back to the oracle and records the divergence (D-08c).

This stage produces four artifacts:

* ``json/optimal_hosting.json`` — the ε=0.05 headline (``flexible_ev_count``,
  ``hosting_expansion_percent``, ``firm_ev_count``, ``annual_activated_fraction``,
  ``eps``, ``reliability_hour_at_headline``, the cvxpy drift/fallback status, and
  the ``content_sha256`` byte-stability tripwire);
* ``data/twostage_frontier.parquet`` — the ε-sweep cost-vs-reliability frontier
  (illustrative labelled prices, supporting evidence);
* ``data/reserve_activation_coldday.parquet`` — the cold-day reserve ``r_t`` vs
  activated ``E[a_t]`` mechanism panel;
* ``reports/twostage_program_report.json`` — the canonical platform report with
  the D-02 supersession note in ``validation.warnings``.

**The optimal headline (D-02) SUPERSEDES Phase-10.1's descriptive
curtailment/deferral curves as the study's citable hosting number.** The optimal
``flexible_ev_count`` is the largest swept penetration whose ANNUAL two-stage
activated-energy fraction stays strictly below the deferral feasibility ceiling
(``TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95``) — the prototype's
``breakeven_nonwires`` feasibility crossing, re-derived under the optimal scheme.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. This stage is pure-numpy + pandas/JSON IO; ``cvxpy`` enters
only through the gated kernel (deferred + ``require_capabilities("ops")``).
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
    tmy_start_hod,
)
from projects.ev_hosting_flex.scripts._twostage import (  # noqa: E402
    annual_twostage_headline,
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
    N_SCENARIOS,
    PENETRATION_SWEEP,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TMY_INPUT_PATH,
    TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95,
    TRANSFORMER_KVA,
    TWOSTAGE_SOLVER,
)

# Quiet the unused-import lints for re-exported config parity with the kernel.
_ = (EPS_SHOW, N_SCENARIOS, TWOSTAGE_SOLVER, tmy_start_hod)

# The modeled small HQ LV transformer rating in kW (D-01/D-02) — the SAME modeled
# rating stages 4/5 key congestion off, used only as a default when the read
# firm_hosting.json omits it (it does not; the read value is authoritative).
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
            "(compute_congestion.py) and stage 5 (apply_flexibility_contracts.py) "
            "before solving the two-stage program."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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


def _read_profile(parquet_path: Path, bus_ids: list[int]) -> np.ndarray:
    """Read a stage-3 profile parquet reindexed to ``bus_ids`` in sorted order.

    Args:
        parquet_path: Path to a ``(n_bus, 8760)`` profile parquet (index = bus id).
        bus_ids: The sorted bus ids to reindex/restrict the rows to.

    Returns:
        A ``(len(bus_ids), 8760)`` float64 array aligned to ``bus_ids``.

    Raises:
        ValueError: If any requested bus id is missing from the profile.
    """
    frame = pd.read_parquet(parquet_path)
    frame.index = [int(b) for b in frame.index]
    missing = [b for b in bus_ids if b not in frame.index]
    if missing:
        raise ValueError(
            f"ev_hosting_flex stage solve_twostage_program: profile "
            f"{parquet_path.name} is missing buses {missing[:10]}"
            f"{'...' if len(missing) > 10 else ''}. Remediation: re-run stage 5 "
            "(apply_flexibility_contracts.py) so the profiles cover the feeder's "
            "downstream load buses."
        )
    return frame.loc[bus_ids].to_numpy(dtype=DTYPE)


def _read_ev_stack(npy_path: Path) -> np.ndarray:
    """Read the stage-3 ``(K, 8760)`` EV stack (per-EV-unit realizations)."""
    if not npy_path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage solve_twostage_program requires the stochastic "
            f"EV stack {npy_path.name} at {npy_path}, but it is missing. "
            "Remediation: re-run stage 5 (apply_flexibility_contracts.py) which "
            "depends on stage 3 (generate_annual_profiles.py)."
        )
    return np.load(npy_path).astype(DTYPE)  # (K, 8760)


def _annual_activated_fraction(
    base_feeder: np.ndarray,
    ev_feeder: np.ndarray,
    feeder_kw: float,
    eps: float,
) -> float:
    """Return the annual two-stage activated-energy fraction (the feasibility gate).

    Streams the per-day two-stage scheme over the full annual 8760h (Pitfall 3 —
    never the ``(365, K, 24)`` cube): per day, ``r_d = Q_{1−ε}[required_d]`` and
    ``a_d = min(r_d, required_d)`` accumulate the expected annual activated energy.
    The fraction is ``E[annual activated kWh] / E[annual EV kWh]`` — the prototype's
    ``breakeven_nonwires`` deferral-feasibility ratio re-derived under the optimal
    scheme (the largest passing penetration is the optimal flexible count).

    Args:
        base_feeder: ``(8760,)`` deterministic feeder base demand (kW).
        ev_feeder: ``(K, 8760)`` per-realization feeder EV draw (kW) at the count.
        feeder_kw: The feeder's modeled kW rating ``S̄``.
        eps: The fixed headline reliability level.

    Returns:
        The annual activated-energy fraction (0 when there is no EV energy).
    """
    n_days = base_feeder.shape[0] // 24
    annual_activated = 0.0
    for day in range(n_days):
        sl = slice(day * 24, (day + 1) * 24)
        req_d = np.maximum(
            0.0, base_feeder[sl][None, :] + ev_feeder[:, sl] - float(feeder_kw)
        )
        r_d = np.quantile(req_d, 1.0 - eps, axis=0, method="linear")  # (24,)
        a_d = np.minimum(r_d[None, :], req_d)
        annual_activated += float(a_d.mean(axis=0).sum())
    annual_ev = float(ev_feeder.sum(axis=1).mean())
    return annual_activated / annual_ev if annual_ev > 1e-9 else 0.0


def derive_twostage(cache_dir: Path, data_dir: Path, json_dir: Path) -> dict:
    """Derive + persist the optimal two-stage hosting headline + frontier + panel.

    Reads the stage-4 ``firm_hosting.json`` denominator (NEVER recomputed), the
    stage-3 per-bus base profile + the ``(K, 8760)`` EV stack, composes the
    cold-day scenario ensemble for the cvxpy↔oracle equivalence + the ε-frontier +
    the cold-day panel, sweeps the penetration grid to re-derive the OPTIMAL
    ``flexible_ev_count`` under the annual two-stage scheme (largest count whose
    annual activated fraction < the deferral feasibility ceiling), and writes the
    optimal headline JSON + the frontier/panel parquet.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars (read for parity;
            the headline reads the firm denominator from ``json_dir``).
        data_dir: Directory the frontier/panel parquet are written to and the
            stage-3 base/EV-stack inputs are read from.
        json_dir: Directory the optimal-hosting JSON is written to AND the stage-4
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a degenerate firm denominator or an empty feeder profile.
    """
    _ = cache_dir  # cache sidecars are governed inputs; firm denominator drives this.
    # ── The stage-4 denominator (D-02): read, NEVER recompute the firm count. ──
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
            f"{feeder_key}; the hosting_expansion_percent denominator must be > 0. "
            "Remediation: re-run stage 4 (compute_congestion.py) so the firm leg is "
            "a positive count."
        )

    # ── The stage-3 inputs (per-bus base + per-EV-unit (K,8760) stack). ──
    base = pd.read_parquet(data_dir / "base_load_8760.parquet")
    base.index = [int(b) for b in base.index]
    bus_ids = sorted(base.index)
    base_arr = _read_profile(data_dir / "base_load_8760.parquet", bus_ids)  # (n_bus,T)
    feeder_indicator = np.ones(len(bus_ids), dtype=DTYPE)  # the feeder subtree sum
    base_feeder = feeder_indicator @ base_arr  # (8760,) deterministic feeder base
    ev_unit = _read_ev_stack(data_dir / "ev_stack_K.npy")  # (K, 8760) per-EV unit

    # ── Composed cold-day scenario ensemble (cvxpy↔oracle + frontier + panel). ──
    required = compose_scenarios(
        np.random.default_rng(SEED),
        n_ev=firm_ev_count,
        n_homes=downstream_home_count,
        feeder_kw=feeder_kw,
    )
    required_sha = _content_sha256(required)

    # ── cvxpy↔oracle equivalence (D-08) at the headline ε; record drift/fallback. ──
    _oracle, meta = assert_cvxpy_matches_oracle(required, EPS_HEADLINE)
    cvxpy_status = str(meta["cvxpy_status"])
    cvxpy_drift = float(meta["drift"])
    cvxpy_fellback = bool(meta["fellback"])

    # ── Re-derive the OPTIMAL flexible_ev_count under the annual scheme (D-02). ──
    # The largest swept EV count whose annual two-stage activated fraction stays
    # strictly below the deferral feasibility ceiling (the prototype's crossing).
    tolerance = float(TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95)
    flexible_ev_count = firm_ev_count
    for penetration in PENETRATION_SWEEP:
        ev_count = int(round(float(penetration) * downstream_home_count))
        if ev_count <= 0:
            continue
        ev_feeder = ev_unit * float(ev_count)  # (K, 8760) total feeder EV draw
        frac = _annual_activated_fraction(
            base_feeder, ev_feeder, feeder_kw, EPS_HEADLINE
        )
        if frac < tolerance:
            flexible_ev_count = max(flexible_ev_count, ev_count)

    # ── The optimal annual headline at the derived flexible count (per-day stream). ──
    ev_stack_flexible = ev_unit * float(flexible_ev_count)  # (K, 8760)
    headline = annual_twostage_headline(
        base_arr,
        ev_stack_flexible,
        feeder_indicator,
        feeder_kw,
        eps=EPS_HEADLINE,
        downstream_home_count=downstream_home_count,
        firm_ev_count=firm_ev_count,
        flexible_ev_count=flexible_ev_count,
    )
    annual_ev_kwh = float(ev_stack_flexible.sum(axis=1).mean())
    annual_activated_fraction = (
        headline["annual_activated_kwh"] / annual_ev_kwh
        if annual_ev_kwh > 1e-9
        else 0.0
    )
    rel_hour_at_headline = float(_oracle["rel_hour"])

    # ── ε-frontier + cold-day reserve-vs-activation panel (TWOSTAGE-05). ──
    frontier = eps_frontier(required, EPS_FRONTIER)
    panel = coldday_panel(required)

    # ── Round all floats pre-write (1e-6 baseline contract, D-10). ──
    headline_block = {
        "flexible_ev_count": int(headline["flexible_ev_count"]),
        "firm_ev_count": firm_ev_count,
        "hosting_expansion_percent": float(
            round(headline["hosting_expansion_percent"], ROUND_DECIMALS)
        ),
        "annual_activated_fraction": float(
            round(annual_activated_fraction, ROUND_DECIMALS)
        ),
        "annual_activated_kwh": float(
            round(headline["annual_activated_kwh"], ROUND_DECIMALS)
        ),
        "seasonal_peak_kw": float(round(headline["seasonal_peak_kw"], ROUND_DECIMALS)),
        "reservation_days": int(headline["reservation_days"]),
        "eps": float(EPS_HEADLINE),
        "reliability_hour_at_headline": float(
            round(rel_hour_at_headline, ROUND_DECIMALS)
        ),
        "downstream_home_count": downstream_home_count,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": feeder_kw,
        "cvxpy_oracle_drift": float(round(cvxpy_drift, ROUND_DECIMALS)),
        "cvxpy_status": cvxpy_status,
        "cvxpy_fellback": cvxpy_fellback,
        "required_content_sha256": required_sha,
    }
    headline_arrays = np.array(
        [
            headline_block["flexible_ev_count"],
            headline_block["hosting_expansion_percent"],
            headline_block["annual_activated_fraction"],
            headline_block["seasonal_peak_kw"],
            headline_block["reliability_hour_at_headline"],
        ],
        dtype=DTYPE,
    )
    headline_block["content_sha256"] = _content_sha256(headline_arrays)

    # ── The supersession note (D-02) + the cvxpy fallback note (D-08c). ──
    supersession_note = (
        "Supersession (D-02): the OPTIMAL two-stage hosting headline at "
        f"eps={EPS_HEADLINE} (flexible_ev_count={flexible_ev_count}, "
        f"hosting_expansion_percent="
        f"{headline_block['hosting_expansion_percent']}) REPLACES Phase-10.1's "
        "descriptive curtailment/deferral curves as the study's citable hosting "
        "number. Phase 10.1 = the re-calibrated model + descriptive limits; "
        "Phase 10.2 = the optimal number under the day-ahead reservation / "
        "real-time activation chance-constrained program."
    )
    cvxpy_note = (
        "cvxpy fallback (D-08c): the gated CLARABEL solve diverged from the "
        f"closed-form oracle (status={cvxpy_status}, drift={cvxpy_drift:.3e} > "
        "1e-6); the stage emitted the byte-stable oracle values and recorded the "
        "divergence. The hosting headline is unaffected (oracle == optimum)."
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
        "flexible_ev_count": flexible_ev_count,
        "hosting_expansion_percent": headline_block["hosting_expansion_percent"],
        "annual_activated_fraction": headline_block["annual_activated_fraction"],
        "eps": float(EPS_HEADLINE),
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
        "supersession_note": supersession_note,
    }
    return {
        "artifact_paths": [optimal_path, frontier_path, panel_path],
        "summary": summary,
        "supersession_note": supersession_note,
        "cvxpy_note": cvxpy_note,
        "cvxpy_fellback": cvxpy_fellback,
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict:
    """Run the full two-stage program stage: derive + parquet/JSON + governed report.

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
    supersession_note = derived["supersession_note"]
    cvxpy_note = derived["cvxpy_note"]
    fellback = bool(derived["cvxpy_fellback"])

    inputs = [
        script.file_reference(json_dir / "firm_hosting.json"),
        script.file_reference(effective_data_dir / "base_load_8760.parquet"),
        script.file_reference(effective_data_dir / "ev_stack_K.npy"),
        script.file_reference(TMY_INPUT_PATH),
    ]

    return script.write_report(
        "twostage_program_report",
        inputs=inputs,
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={
            "valid": True,
            "errors": [],
            "warnings": [supersession_note, *([cvxpy_note] if fellback else [])],
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
        f"optimal flexible={summary.get('flexible_ev_count')} "
        f"(+{summary.get('hosting_expansion_percent')}) at "
        f"eps={summary.get('eps')} | cvxpy_status={summary.get('cvxpy_status')}"
    )


if __name__ == "__main__":
    main()

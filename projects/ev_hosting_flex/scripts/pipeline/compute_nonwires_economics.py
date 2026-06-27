"""Non-wires economics stage — energy-preserving deferral hosting + cost ledger.

Stage 6.5 of the v1.3 generative-MC workflow (ECON-01 wiring / ECON-03
reconciliation, D-16-*), sitting between ``solve_twostage_program`` (stage 6) and the
stubbed ``validate_powerflow``/``build_study_reports``. The stage wires the Plan-02
``_economics.py`` kernel into the governed pipeline: it reads the Phase-14
``firm_hosting.json`` denominator (firm=3, 7 homes — NEVER recomputed) + the Phase-13
design-day artifacts (``q_real.npy`` / ``ev_pool_design.npy``; regenerated via the
governed ``make_design_day_ensemble`` if absent — the same governed call, no silent
fallback divergence), runs:

* **Deferral hosting (D-16-1/D-16-2):** the hosting count WITH flexibility under the
  manuscript / deck power-limiting-with-deferral model at the governed enrollment
  bound (``DEFERRAL_ENROLLMENT_FRACTION=0.30`` → headline flex 6, +100% vs firm 3);
* **Non-wires economics ledger (ECON-01):** the per-penetration quantities, the
  CRF-annualized reinforcement, the break-even-penetration vs ``c_r`` sweep, and the
  adoption-ramp deferral NPV — all on the GOVERNED firm basis
  (``p_firm = firm_ev_count / downstream_home_count``, NOT the manuscript
  ``P_FIRM = 1.0``), with the contract cost ALWAYS routed through the single
  ``flex_cost`` ledger (no double-count, the ECON-03 anchor).

It emits three CSVs + ``nonwires_economics.json`` (with a ``content_sha256`` tripwire
over the economics arrays), regenerates the two manuscript figures (Agg, written ONLY
under the project ``outputs/figures`` — manuscripts/ is NEVER touched), and emits a
canonical ``ProjectScript.write_report`` (NO hand-written report JSON). Per the D-16-6
user decision (additive-nondestructive) the JSON carries a ``headline_model``
discriminator + a coexistence note: the deferral count is the hosting headline; the
Phase-15 two-stage ``flexible_ev_count`` is retained as the OOS reserve-scheme caveat.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` / ``lightsim2grid``.
This stage is pure numpy + pandas + matplotlib (Agg) + JSON IO; the kernel is numpy.
``OMP_NUM_THREADS=1`` is set at import (Pitfall 5 — cap the BLAS thread pool so the
small per-step quantile reductions stay deterministic and cheap).
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

from projects.ev_hosting_flex.scripts._economics import (  # noqa: E402
    breakeven_sweep,
    crf,
    deferral_hosting_count,
    deferral_npv,
    deferral_npv_sweep,
    feasibility_ceiling,
    per_penetration_quantities,
    reinforcement_annual,
)
from projects.ev_hosting_flex.scripts._generators import (  # noqa: E402
    make_design_day_ensemble,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ADOPT_YEARS_BASE,
    C_A,
    C_R_BASE,
    CAPEX_UPGRADE,
    DEFERRAL_ENROLLMENT_FRACTION,
    DESIGN_DAY_EV_MAX,
    DESIGN_DAY_RES_MINUTES,
    DISCOUNT_RATE,
    DTYPE,
    EPS_HEADLINE,
    K_DESIGN,
    LIFE_YEARS,
    POWER_FACTOR,
    PMAX_ADOPT,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TOL_FRACTION,
    TRANSFORMER_KVA,
)

# Quiet the unused-import lint for re-exported config parity.
_ = (LIFE_YEARS,)

# The modeled small HQ LV transformer rating in kW — used only as a default when the
# read firm_hosting.json omits the modeled-kW key (it does not; the read value wins).
_FEEDER_TRANSFORMER_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)

# ── Non-wires economics sweep grids (ported from the manuscript figure scripts) ──
# Provenance: manuscripts/ev_hosting_flex/scripts/figures/nonwires_economics.py
# (PEN_GRID = arange(0.4, 4.01, 0.2); C_R_GRID = arange(0.5, 8.01, 0.25);
# ADOPT_GRID = arange(5, 31, 1)). The penetration grid spans the firm basis up to
# PMAX_ADOPT so the break-even / NPV crossings are interior.
PEN_GRID = np.round(np.arange(0.4, float(PMAX_ADOPT) + 0.01, 0.2), 2).tolist()
C_R_GRID = np.round(np.arange(0.5, 8.01, 0.25), 2).tolist()
ADOPT_GRID = [int(v) for v in np.arange(5, 31, 1)]


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
            f"ev_hosting_flex stage compute_nonwires_economics requires {path.name} "
            f"at {path}, but it is missing. Remediation: re-run stage 4 "
            "(compute_congestion.py) so firm_hosting.json is written (the gitignored "
            "cache lives only in the main tree — run without a worktree)."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_or_regenerate_ensemble(
    data_dir: Path, n_homes: int, res_minutes: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(q_real, ev_pool)``, regenerating via the governed call if absent.

    Reads the Phase-13 ``q_real.npy`` / ``ev_pool_design.npy`` from ``data_dir``; if
    either is missing the GOVERNED ``make_design_day_ensemble(seed=SEED, ...)`` is
    called (the SAME governed call the stage-3 generator uses — no silent-fallback
    divergence) and the arrays are persisted so subsequent runs are byte-stable.

    Args:
        data_dir: Directory the design-day artifacts are read from / written to.
        n_homes: The downstream-home count (the ensemble's building count).
        res_minutes: The aggregation resolution in minutes.

    Returns:
        ``(q_real (K, n_steps), ev_pool (K, ev_max + 1, n_steps))`` float64 arrays.
    """
    q_real_path = data_dir / "q_real.npy"
    ev_pool_path = data_dir / "ev_pool_design.npy"
    if q_real_path.is_file() and ev_pool_path.is_file():
        q_real = np.load(q_real_path).astype(DTYPE)
        ev_pool = np.load(ev_pool_path).astype(DTYPE)
        return q_real, ev_pool
    # Regenerate via the governed call (no silent fallback — the same seed/res).
    ensemble = make_design_day_ensemble(
        n_homes,
        k=K_DESIGN,
        seed=SEED,
        res_minutes=res_minutes,
        n_ev_max=DESIGN_DAY_EV_MAX,
    )
    q_real = np.asarray(ensemble["Q_real"], dtype=DTYPE)
    ev_pool = np.asarray(ensemble["ev_pool"], dtype=DTYPE)
    data_dir.mkdir(parents=True, exist_ok=True)
    np.save(q_real_path, q_real)
    np.save(ev_pool_path, ev_pool)
    return q_real, ev_pool


def _write_json(path: Path, payload: object) -> Path:
    """Write ``payload`` to ``path`` as deterministic, sorted-key JSON.

    Args:
        path: Destination path (parent dirs created as needed).
        payload: The JSON-serializable payload.

    Returns:
        The written path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _content_sha256(arr: np.ndarray) -> str:
    """Return the canonical-bytes sha256 of a rounded float64 array (D-16-8).

    Args:
        arr: The float64 array whose canonical bytes are hashed.

    Returns:
        The hex sha256 digest of the contiguous canonical-bytes representation.
    """
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0  # kill signed zero
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _render_figures(
    fig_dir: Path,
    *,
    pen: np.ndarray,
    kw_days: np.ndarray,
    activated: np.ndarray,
    undeliverable_fraction: np.ndarray,
    c_r_grid: list,
    p_star: np.ndarray,
    p_feas: float,
    adopt_grid: list,
    npv: np.ndarray,
    reinf_annual: float,
    crf_val: float,
    n_homes: int,
) -> list[Path]:
    """Render the two manuscript figures (Agg) under the project outputs/figures.

    Ports the manuscript breakeven_nonwires.py + nonwires_economics.py figure blocks
    onto the governed quantities. Matplotlib is forced to the Agg backend; figures are
    written ONLY under ``fig_dir`` — manuscripts/ is NEVER touched (T-16-10).

    Args:
        fig_dir: The project outputs/figures directory.
        pen: ``(n_p,)`` penetration grid.
        kw_days: ``(n_p,)`` reserved kW-days per penetration.
        activated: ``(n_p,)`` activated energy per penetration (kWh).
        undeliverable_fraction: ``(n_p,)`` undeliverable fraction per penetration.
        c_r_grid: The reservation-price sweep.
        p_star: ``(n_cr,)`` break-even penetration per swept ``c_r``.
        p_feas: The deferral feasibility ceiling penetration.
        adopt_grid: The adoption-speed sweep.
        npv: ``(n_adopt,)`` deferral NPV per adoption speed.
        reinf_annual: The annualized reinforcement cost ($/yr).
        crf_val: The capital-recovery factor.
        n_homes: The downstream-home count (for the figure suptitle).

    Returns:
        The list of written figure paths (png + pdf for each of the two figures).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    res_cost = float(C_R_BASE) * np.asarray(kw_days, dtype=DTYPE)
    act_cost = float(C_A) * np.asarray(activated, dtype=DTYPE)
    flex_total = res_cost + act_cost

    # ── Figure 1: non-wires break-even + deferral feasibility (breakeven_nonwires) ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.3))
    ax1.plot(pen, flex_total, color="#1A2B3C", lw=2.4, marker="o", ms=4,
             label="flexibility (total)")
    ax1.plot(pen, res_cost, color="#2E6FB7", lw=1.6, ls="--", marker="s", ms=3,
             label="  reservation")
    ax1.plot(pen, act_cost, color="#2AA198", lw=1.6, ls="--", marker="^", ms=3,
             label="  activation")
    ax1.axhline(reinf_annual, color="#C0392B", lw=2.0,
                label=f"reinforce (50$\\to$100 kVA), ${reinf_annual:.0f}/yr")
    ax1.set_xlabel("EV per home", fontsize=10)
    ax1.set_ylabel("annual cost ($/yr)", fontsize=10)
    ax1.set_title("Non-wires break-even", fontsize=11, fontweight="bold")
    ax1.legend(frameon=True, fontsize=7.5, loc="upper left")

    ax2.plot(pen, np.asarray(undeliverable_fraction, dtype=DTYPE) * 100,
             color="#E08A1E", lw=2.4, marker="o", ms=4)
    ax2.axhline(float(TOL_FRACTION) * 100, color="#C0392B", lw=1.6, ls="--",
                label=f"deferral ceiling ({float(TOL_FRACTION) * 100:.0f}%)")
    ax2.set_xlabel("EV per home", fontsize=10)
    ax2.set_ylabel("undeliverable energy (% of EV)", fontsize=10)
    ax2.set_title("Deferral feasibility", fontsize=11, fontweight="bold")
    ax2.legend(frameon=True, fontsize=8, loc="upper left")
    fig.suptitle(
        f"Flexibility vs reinforcement — {TRANSFORMER_KVA:.0f} kVA / {n_homes} homes, "
        f"$\\varepsilon$={EPS_HEADLINE} (governed prices: ${C_A:.2f}/kWh, "
        f"${C_R_BASE:.0f}/kW per reservation-day)",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for ext in ("png", "pdf"):
        path = fig_dir / f"breakeven_nonwires.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        written.append(path)
    plt.close(fig)

    # ── Figure 2: break-even sensitivity + deferral NPV vs adoption (nonwires_econ) ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.3))
    ax1.plot(c_r_grid, p_star, color="#1A2B3C", lw=2.4,
             label="cost break-even $p^*(c_r)$")
    ax1.axhline(p_feas, color="#E08A1E", lw=1.8, ls="--",
                label=f"feasibility ceiling ($\\sim${p_feas:.1f})")
    ax1.axvline(float(C_R_BASE), color="#7F8C8D", lw=1.0, ls=":")
    ax1.set_xlabel("reservation price $c_r$ ($/kW per reservation-day)", fontsize=9.5)
    ax1.set_ylabel("break-even penetration (EV/home)", fontsize=10)
    ax1.set_title("Break-even sensitivity to price", fontsize=11, fontweight="bold")
    ax1.set_ylim(0, float(PMAX_ADOPT))
    ax1.legend(frameon=True, fontsize=8, loc="upper right")

    ax2.plot(adopt_grid, npv, color="#2E6FB7", lw=2.4)
    ax2.axvline(int(ADOPT_YEARS_BASE), color="#7F8C8D", lw=1.0, ls=":")
    ax2.set_xlabel("adoption speed (years to reach 4 EV/home)", fontsize=9.5)
    ax2.set_ylabel("PV of deferral — flexibility value ($)", fontsize=10)
    ax2.set_title("Deferral value vs adoption speed", fontsize=11, fontweight="bold")
    fig.suptitle(
        f"Non-wires economics — {TRANSFORMER_KVA:.0f} kVA / {n_homes} homes, "
        f"reinforce ${CAPEX_UPGRADE:,.0f} (CRF {crf_val:.3f} = ${reinf_annual:.0f}/yr), "
        f"d={DISCOUNT_RATE:.0%}",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for ext in ("png", "pdf"):
        path = fig_dir / f"nonwires_economics.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        written.append(path)
    plt.close(fig)

    return written


def derive_economics(cache_dir: Path, data_dir: Path, json_dir: Path) -> dict:
    """Derive + persist the deferral hosting headline + the non-wires economics ledger.

    Reads the stage-4 ``firm_hosting.json`` denominator (NEVER recomputed) + the
    stage-3 design-day ``q_real.npy`` / ``ev_pool_design.npy`` (regenerated via the
    governed ``make_design_day_ensemble`` if absent), runs the deferral hosting count
    at the governed enrollment bound + the economics ledger on the GOVERNED firm basis
    (``p_firm = firm/n_homes``, NOT 1.0), writes the three CSVs + the economics JSON
    (with a ``content_sha256`` tripwire), and regenerates the two manuscript figures.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars (read for parity; the
            headline reads the firm denominator from ``json_dir``).
        data_dir: Directory the CSVs are written to and the design-day artifacts are
            read from / regenerated into.
        json_dir: Directory the economics JSON is written to AND the stage-4
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths``, a ``summary`` dict, and a coexistence
        ``note``.

    Raises:
        ValueError: On a degenerate firm denominator.
    """
    _ = cache_dir  # cache sidecars are governed inputs; the firm denominator drives.
    fig_dir = json_dir.parent / "figures"

    # ── The stage-4 denominator (D-16-4): read, NEVER recompute the firm count. ──
    firm = _load_json(json_dir / "firm_hosting.json")
    firm_ev_count = int(firm["firm_ev_count"])
    downstream_home_count = int(firm["downstream_home_count"])
    feeder_key = str(firm["feeder_key"])
    feeder_kw = float(firm.get("feeder_transformer_modeled_kw", _FEEDER_TRANSFORMER_KW))
    if firm_ev_count <= 0 or downstream_home_count <= 0:
        raise ValueError(
            "ev_hosting_flex stage compute_nonwires_economics: degenerate firm basis "
            f"firm_ev_count={firm_ev_count}, downstream_home_count="
            f"{downstream_home_count} read from firm_hosting.json for feeder "
            f"{feeder_key}; both must be > 0 so p_firm = firm/n_homes is well-defined. "
            "Remediation: re-run stage 4 (compute_congestion.py)."
        )

    res_minutes = int(DESIGN_DAY_RES_MINUTES)
    q_real, ev_pool = _load_or_regenerate_ensemble(
        data_dir, downstream_home_count, res_minutes
    )
    ev_max = int(ev_pool.shape[1]) - 1

    # ── Deferral hosting count WITH flexibility (D-16-1/D-16-2, the headline). ──
    deferral = deferral_hosting_count(
        q_real,
        ev_pool,
        feeder_kw,
        float(TOL_FRACTION),
        ev_max,
        res_minutes,
        enrollment_fraction=float(DEFERRAL_ENROLLMENT_FRACTION),
    )
    flexible_ev_count = int(deferral["flexible_ev_count"])
    hosting_expansion_percent = (
        float(flexible_ev_count - firm_ev_count) / float(firm_ev_count)
    )

    # ── Per-penetration quantities on the GOVERNED firm basis (p_firm, NOT 1.0). ──
    p_firm = float(firm_ev_count) / float(downstream_home_count)
    quant = per_penetration_quantities(
        q_real,
        ev_pool,
        feeder_kw,
        float(EPS_HEADLINE),
        res_minutes,
        PEN_GRID,
        downstream_home_count,
        enrollment_fraction=float(DEFERRAL_ENROLLMENT_FRACTION),
    )
    pen = quant["penetration"]
    kw_days = quant["kw_days"]
    activated = quant["activated"]
    undeliverable_fraction = quant["undeliverable_fraction"]

    # ── CRF-annualized reinforcement + break-even sweep + feasibility ceiling. ──
    crf_val = crf(float(DISCOUNT_RATE), int(LIFE_YEARS))
    reinf_annual = reinforcement_annual(crf_val, float(CAPEX_UPGRADE))
    breakeven_rows = breakeven_sweep(
        PEN_GRID, kw_days, activated, C_R_GRID, float(C_A), reinf_annual
    )
    p_star = np.asarray([row["p_star"] for row in breakeven_rows], dtype=DTYPE)
    p_feas = feasibility_ceiling(
        undeliverable_fraction, PEN_GRID, float(TOL_FRACTION), pmax=float(PMAX_ADOPT)
    )

    # ── Adoption-ramp deferral NPV (governed firm basis p_firm, NOT 1.0). ──
    npv_rows = deferral_npv_sweep(
        ADOPT_GRID,
        PEN_GRID,
        kw_days,
        activated,
        c_r=float(C_R_BASE),
        c_a=float(C_A),
        discount_rate=float(DISCOUNT_RATE),
        horizon=int(LIFE_YEARS),
        p_firm=p_firm,
        reinf_annual=reinf_annual,
        p_feas=p_feas,
    )
    npv = np.asarray([row["deferral_npv"] for row in npv_rows], dtype=DTYPE)
    npv_base = deferral_npv(
        float(ADOPT_YEARS_BASE),
        PEN_GRID,
        kw_days,
        activated,
        c_r=float(C_R_BASE),
        c_a=float(C_A),
        discount_rate=float(DISCOUNT_RATE),
        horizon=int(LIFE_YEARS),
        p_firm=p_firm,
        reinf_annual=reinf_annual,
        p_feas=p_feas,
    )

    # ── The single ledger identity Σr / Σa at the deferral headline penetration. ──
    # The headline flex cost equals c_r·Σr + c_a·Σa from the SAME physical totals at
    # the deferral count's penetration (no double-count, T-16-06 / ECON-03 anchor).
    p_headline = float(flexible_ev_count) / float(downstream_home_count)
    sum_r_headline = float(np.interp(p_headline, pen, kw_days))
    e_sum_a_headline = float(np.interp(p_headline, pen, activated))
    flex_cost_headline = (
        float(C_R_BASE) * sum_r_headline + float(C_A) * e_sum_a_headline
    )

    # ── Round all floats pre-write (1e-6 baseline contract). ──
    def _r(x: float) -> float:
        return float(round(float(x), ROUND_DECIMALS))

    pen_r = np.round(pen, ROUND_DECIMALS).astype("float64")
    kw_days_r = np.round(kw_days, ROUND_DECIMALS).astype("float64")
    activated_r = np.round(activated, ROUND_DECIMALS).astype("float64")
    undeliv_r = np.round(undeliverable_fraction, ROUND_DECIMALS).astype("float64")
    p_star_r = np.round(p_star, ROUND_DECIMALS).astype("float64")
    npv_r = np.round(npv, ROUND_DECIMALS).astype("float64")

    # ── content_sha256 tripwire over the economics arrays (kw_days/activated/p*). ──
    content_arrays = np.concatenate(
        [
            pen_r,
            kw_days_r,
            activated_r,
            undeliv_r,
            p_star_r,
            npv_r,
            np.asarray(
                [float(flexible_ev_count), _r(hosting_expansion_percent)],
                dtype="float64",
            ),
        ]
    )
    content_sha256 = _content_sha256(content_arrays)

    # ── D-16-6 coexistence (additive-nondestructive): the deferral count is the ──
    # hosting headline; the Phase-15 two-stage flexible_ev_count is the OOS caveat.
    headline_model = "deferral_power_limiting"
    coexistence_note = (
        "D-16-6 (additive-nondestructive): the deferral power-limiting count "
        f"(flexible_ev_count={flexible_ev_count}, +"
        f"{hosting_expansion_percent * 100:.0f}% vs firm {firm_ev_count}) is the "
        "hosting headline (headline_model=deferral_power_limiting). The Phase-15 "
        "two-stage reserve-scheme count (flexible_ev_count=2 < firm 3, the OOS "
        "forecast-blindness finding) is RETAINED as the reserve-scheme caveat in "
        "flexible_hosting.json (harder_truth / divergence_note preserved verbatim) — "
        "it is NOT the hosting headline and is not overwritten."
    )

    # ── Write the three CSVs. ──
    data_dir.mkdir(parents=True, exist_ok=True)
    breakeven_path = data_dir / "nonwires_economics_breakeven.csv"
    pd.DataFrame(
        {
            "ev_per_home": pen_r,
            "kw_days": kw_days_r,
            "activated_kwh": activated_r,
            "reservation_cost": np.round(
                float(C_R_BASE) * kw_days, ROUND_DECIMALS
            ).astype("float64"),
            "activation_cost": np.round(
                float(C_A) * activated, ROUND_DECIMALS
            ).astype("float64"),
            "flex_cost": np.round(
                float(C_R_BASE) * kw_days + float(C_A) * activated, ROUND_DECIMALS
            ).astype("float64"),
            "undeliverable_fraction": undeliv_r,
        }
    ).to_csv(breakeven_path, index=False)

    sensitivity_path = data_dir / "nonwires_economics_sensitivity.csv"
    pd.DataFrame(
        {
            "c_r": np.asarray(C_R_GRID, dtype="float64"),
            "p_star": p_star_r,
            "p_effective": np.round(
                np.minimum(p_star, float(p_feas)), ROUND_DECIMALS
            ).astype("float64"),
        }
    ).to_csv(sensitivity_path, index=False)

    npv_path = data_dir / "nonwires_economics_npv.csv"
    pd.DataFrame(
        {
            "adopt_years": np.asarray(ADOPT_GRID, dtype="int64"),
            "deferral_npv": npv_r,
        }
    ).to_csv(npv_path, index=False)

    # ── Write the economics JSON (with the D-16-6 discriminator + the tripwire). ──
    economics_block = {
        "headline_model": headline_model,
        "phase16_coexistence_note": coexistence_note,
        "flexible_ev_count": flexible_ev_count,
        "deferral_flexible_ev_count": flexible_ev_count,
        "firm_ev_count": firm_ev_count,
        "hosting_expansion_percent": _r(hosting_expansion_percent),
        "deferral_hosting_expansion_percent": _r(hosting_expansion_percent),
        "enrollment_fraction": _r(float(DEFERRAL_ENROLLMENT_FRACTION)),
        "downstream_home_count": downstream_home_count,
        "firm_penetration": _r(p_firm),
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": feeder_kw,
        "eps": float(EPS_HEADLINE),
        "tol_fraction": float(TOL_FRACTION),
        "c_r_base": float(C_R_BASE),
        "c_a": float(C_A),
        "capex_upgrade": float(CAPEX_UPGRADE),
        "discount_rate": float(DISCOUNT_RATE),
        "life_years": int(LIFE_YEARS),
        "crf": _r(crf_val),
        "reinforcement_annual": _r(reinf_annual),
        "feasibility_ceiling_penetration": _r(float(p_feas)),
        "breakeven_penetration_at_base_c_r": _r(
            float(np.interp(float(C_R_BASE), C_R_GRID, p_star))
        ),
        "deferral_npv_base": _r(float(npv_base)),
        "deferral_npv_min": _r(float(npv.min())),
        "deferral_npv_max": _r(float(npv.max())),
        "sum_r_headline_kw": _r(sum_r_headline),
        "e_sum_a_headline_kwh": _r(e_sum_a_headline),
        "flex_cost_headline": _r(flex_cost_headline),
        "k_realizations": int(q_real.shape[0]),
        "n_steps": int(q_real.shape[1]),
        "ev_max": ev_max,
        "threshold_convention": str(deferral["threshold_convention"]),
        "content_sha256": content_sha256,
    }
    economics_path = _write_json(
        json_dir / "nonwires_economics.json", economics_block
    )

    # ── Regenerate the two manuscript figures (Agg; outputs/figures only). ──
    figure_paths = _render_figures(
        fig_dir,
        pen=pen,
        kw_days=kw_days,
        activated=activated,
        undeliverable_fraction=undeliverable_fraction,
        c_r_grid=C_R_GRID,
        p_star=p_star,
        p_feas=float(p_feas),
        adopt_grid=ADOPT_GRID,
        npv=npv,
        reinf_annual=reinf_annual,
        crf_val=crf_val,
        n_homes=downstream_home_count,
    )

    summary = {
        "headline_model": headline_model,
        "flexible_ev_count": flexible_ev_count,
        "deferral_flexible_ev_count": flexible_ev_count,
        "firm_ev_count": firm_ev_count,
        "hosting_expansion_percent": economics_block["hosting_expansion_percent"],
        "enrollment_fraction": economics_block["enrollment_fraction"],
        "firm_penetration": economics_block["firm_penetration"],
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": feeder_kw,
        "crf": economics_block["crf"],
        "reinforcement_annual": economics_block["reinforcement_annual"],
        "feasibility_ceiling_penetration": economics_block[
            "feasibility_ceiling_penetration"
        ],
        "breakeven_penetration_at_base_c_r": economics_block[
            "breakeven_penetration_at_base_c_r"
        ],
        "deferral_npv_base": economics_block["deferral_npv_base"],
        "flex_cost_headline": economics_block["flex_cost_headline"],
        "k_realizations": economics_block["k_realizations"],
        "n_steps": economics_block["n_steps"],
        "content_sha256": content_sha256,
        "coexistence_note": coexistence_note,
    }
    return {
        "artifact_paths": [
            breakeven_path,
            sensitivity_path,
            npv_path,
            economics_path,
            *figure_paths,
        ],
        "summary": summary,
        "note": coexistence_note,
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict:
    """Run the full economics stage: derive + CSV/JSON/figures + governed report.

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

    derived = derive_economics(effective_cache_dir, effective_data_dir, json_dir)
    artifact_paths = derived["artifact_paths"]
    summary = derived["summary"]
    note = derived["note"]

    inputs = [
        script.file_reference(json_dir / "firm_hosting.json"),
        script.file_reference(effective_data_dir / "q_real.npy"),
        script.file_reference(effective_data_dir / "ev_pool_design.npy"),
    ]

    return script.write_report(
        "nonwires_economics_report",
        inputs=inputs,
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": [note]},
    )


def main() -> None:
    """CLI entry point for the non-wires economics stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Computed non-wires economics + report: "
        f"headline_model={summary.get('headline_model')} | "
        f"deferral flexible_ev_count={summary.get('flexible_ev_count')} "
        f"(+{summary.get('hosting_expansion_percent', 0.0) * 100:.0f}%) vs firm "
        f"{summary.get('firm_ev_count')} | "
        f"reinforce ${summary.get('reinforcement_annual')}/yr | "
        f"deferral NPV base ${summary.get('deferral_npv_base')}"
    )


if __name__ == "__main__":
    main()

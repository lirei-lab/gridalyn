"""Apply flexibility contracts: the two-stage day-ahead curtailment CONTROLLER.

Stage 5 of the workflow (Phase 15 CTRL-01..04 / RETIRE-02). This is the genuine
new logic of the milestone — the re-point of stage 5 off the retired
power-limited availability sweep onto the two-stage chance-constrained controller:

* **PLAN (CTRL-01).** ``r_t = Q_{1-eps}[required]`` is computed by the inherited
  byte-stable ``twostage_oracle`` over a forecast ``required`` ensemble built by the
  Plan-01 re-anchored ``compose_scenarios(q_design=...)`` — anchored on the emitted
  ``Q_design`` building mean and drawn from a DISJOINT plan seed (``SEED``, D-01).
  The reserve is NEVER quantiled over the in-sample ``Q_real`` (Pitfall 1).
* **REALIZE / VALIDATE out-of-sample (CTRL-02).** A FRESH disjoint ``Q_real``
  ensemble is drawn at controller time via
  ``make_design_day_ensemble(seed=SEED + OOS_SEED_OFFSET)`` (D-03/D-04, N=60) — a
  draw the plan never saw. The EV pool is overlaid, the actuator activates
  ``a_t = min(r_t, required_real)`` at 100% enrollment (D-08, the cap PATTERN in
  numpy on the MDPI aggregate — NOT the SDK EV-charger session object, D-09), and
  realized
  ``P(overload after activation)`` is evaluated via the Phase-14 ``is_overloaded``
  kernel (D-05). The in-band ``realized <= eps`` is asserted and the realized-vs-eps
  gap is surfaced + quantified (a "harder truth than forecast" note when it exceeds).
* **ADVERSARIAL (CTRL-02, D-11).** A pinned ``-5 degC`` colder ``Q_real`` ensemble
  (``building_realization(t_offset=ADVERSARIAL_DELTA_C)`` over a disjoint
  ``ADV_SEED_OFFSET`` block) reports a DEGRADED realized ``P(overload)`` above the
  non-adversarial value — REPORTED, never gated to fail.
* **RESOURCE VALUE (CTRL-03, D-10).** Per-step ``r_t`` vs ``E[a_t]``, the ratio
  ``E[Sum a]/Sum r``, and the cold-day reserve-vs-activation panel; the invariant
  ``a_t <= r_t`` and a sane ratio range are asserted.
* **HEADLINE (CTRL-04, D-12).** ``flexible_ev_count`` = the largest adoption with
  realized reliability ``<= eps`` on ``Q_real`` ALONE (the cost gate is deferred to
  Phase 16); ``hosting_expansion_percent = (flexible - firm) / firm`` with ``firm=3``
  READ from ``firm_hosting.json`` (never re-run). ``Sum r`` / ``E[Sum a]`` totals are
  emitted so Phase 16 applies the cost gate WITHOUT re-running.

**The unit of congestion is the MODELED small HQ LV transformer.** The feeder
rating is ``TRANSFORMER_KVA * POWER_FACTOR`` = 71.25 kW (the same modeled rating
stage 4 keys congestion off), read from ``firm_hosting.json``.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` / ``lightsim2grid``.
This stage is pure-numpy + pandas/JSON IO; the SDK building imports stay deferred
inside ``_generators``. Determinism (Pitfall 5): a single seeded
``np.random.default_rng`` per stream, float64 throughout, round-before-write to
``ROUND_DECIMALS``, ``OMP_NUM_THREADS=1``, ``np.quantile(method="linear")`` only.
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

# Determinism (Pitfall 5): pin the BLAS thread count BEFORE any heavy numeric work
# so run-vs-run reductions are byte-stable for the Phase-17 seal.
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.ev_hosting_flex.scripts._congestion import (  # noqa: E402
    is_overloaded,
)
from projects.ev_hosting_flex.scripts._generators import (  # noqa: E402
    building_realization,
    make_design_day_ensemble,
    select_design_day,
)
from projects.ev_hosting_flex.scripts._twostage import (  # noqa: E402
    coldday_panel,
    compose_scenarios,
    twostage_oracle,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ADV_SEED_OFFSET,
    ADVERSARIAL_DELTA_C,
    DESIGN_DAY_EV_MAX,
    DESIGN_DAY_RES_MINUTES,
    DTYPE,
    EPS_HEADLINE,
    K_DESIGN,
    OOS_N,
    OOS_SEED_OFFSET,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TRANSFORMER_KVA,
)

# The in-band tolerance on the realized P(overload) vs eps assertion (CTRL-02). The
# realized reliability is estimated from N=60 finite samples so it carries Monte-Carlo
# tail noise of order 1/N; this small band absorbs that sampling jitter WITHOUT
# loosening the scientific finding — the realized-vs-eps GAP is still surfaced and
# quantified, and a realized > eps result is reported as the harder truth (D-02).
_REALIZED_EPS_TOL = 1.0 / float(OOS_N)

# The modeled small HQ LV transformer rating in kW (the SAME modeled rating stage 4
# keys congestion off). Read from firm_hosting.json at runtime; this is the fallback.
_FEEDER_TRANSFORMER_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def _load_json(path: Path) -> dict:
    """Load a required JSON artifact, failing loudly if it is absent.

    Args:
        path: Path to the JSON artifact produced by an upstream stage.

    Returns:
        The parsed JSON mapping.

    Raises:
        FileNotFoundError: If the artifact is missing (stale/incomplete cache).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 5 (controller) requires {path.name} at {path}, "
            "but it is missing. Remediation: re-run stage 2 "
            "(prepare_topology_cache.py), stage 3 (generate_design_day_mc.py), and "
            "stage 4 (compute_congestion.py) before applying flexibility contracts."
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_npy(path: Path) -> np.ndarray:
    """Load a required design-day ``.npy`` artifact, failing loudly if absent.

    Args:
        path: Path to the ``.npy`` artifact produced by stage 3.

    Returns:
        The loaded float64 array.

    Raises:
        FileNotFoundError: If the artifact is missing (stale/incomplete cache).
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 5 (controller) requires the design-day artifact "
            f"{path.name} at {path}, but it is missing. Remediation: re-run stage 3 "
            "(generate_design_day_mc.py) to emit q_real/q_design/ev_pool_design."
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
    """Return the canonical-bytes sha256 of a float64 array (kill signed zero)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0  # kill signed zero
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def plan_reserve(
    *,
    q_design: np.ndarray,
    n_ev: int,
    feeder_kw: float,
    eps: float = EPS_HEADLINE,
    seed: int = SEED,
    n_scenarios: int = K_DESIGN,
) -> dict[str, np.ndarray]:
    """Plan the day-ahead reserve ``r_t = Q_{1-eps}[required]`` (CTRL-01).

    Builds the forecast ``required`` ensemble via the Plan-01 re-anchored
    ``compose_scenarios`` — anchored on the emitted ``q_design`` building mean and
    drawn from the DISJOINT plan seed ``np.random.default_rng(seed)`` (D-01) — then
    applies the inherited byte-stable ``twostage_oracle`` to obtain the reserve
    ``r_t`` and the plan-time activation ``a`` (used only for the resource-value
    panel). The reserve is NEVER quantiled over the in-sample ``Q_real`` (Pitfall 1).

    Args:
        q_design: The ``(n_steps,)`` float64 day-ahead forecast trajectory (kW).
        n_ev: The EV count sampled per scenario (the adoption's feeder EV count).
        feeder_kw: The feeder's modeled kW rating (subtracted to form ``required``).
        eps: The per-hour exceedance level ``eps`` in (0, 1).
        seed: The DISJOINT plan seed (default ``SEED``); the OOS validation block is
            ``SEED + OOS_SEED_OFFSET``, never this block.
        n_scenarios: The plan Monte-Carlo scenario count (default ``K_DESIGN``).

    Returns:
        The ``twostage_oracle`` dict: ``r`` (n_steps,), ``a`` (n_scenarios, n_steps),
        reliabilities, costs, ``activated_mean_kwh``, plus ``required_plan``.
    """
    required_plan = compose_scenarios(
        np.random.default_rng(int(seed)),
        n_ev=int(n_ev),
        feeder_kw=float(feeder_kw),
        q_design=np.asarray(q_design, dtype=DTYPE),
        n_scenarios=int(n_scenarios),
    )
    out = twostage_oracle(required_plan, float(eps))
    out["required_plan"] = required_plan
    return out


def realize_validate(
    *,
    r_t: np.ndarray,
    q_real: np.ndarray,
    ev_pool: np.ndarray,
    n_ev: int,
    feeder_kw: float,
) -> dict[str, object]:
    """Realize + validate the reserve out-of-sample on a fresh ``Q_real`` (CTRL-02).

    Overlays the nested cumulative EV pool row ``n_ev`` onto the EV-free building
    base ``q_real``, forms ``required_real = (q_real + ev_draw - feeder_kw)^+``,
    activates ``a = min(r_t, required_real)`` at 100% enrollment (D-08, the cap
    actuator PATTERN in numpy — never the SDK EV-charger session object, D-09), and
    computes the
    realized ``P(overload after activation)`` via the Phase-14 ``is_overloaded``
    kernel over the post-activation total ``q_real + ev_draw - a`` (Open-Q4, D-05).

    Args:
        r_t: The ``(n_steps,)`` day-ahead reserve planned on ``Q_design``.
        q_real: The ``(N, n_steps)`` fresh disjoint EV-free building-base ensemble.
        ev_pool: The ``(N, ev_max + 1, n_steps)`` nested cumulative EV pool.
        n_ev: The EV count to overlay (indexes the EV-pool middle axis).
        feeder_kw: The modeled feeder transformer rating in kW.

    Returns:
        A mapping with ``a`` ((N, n_steps) activation), ``realized_p_overload``
        (float in [0, 1]), and ``post_total`` ((N, n_steps) post-activation load).
    """
    q = np.asarray(q_real, dtype=DTYPE)
    ev_draw = np.asarray(ev_pool, dtype=DTYPE)[:, int(n_ev), :]  # (N, n_steps)
    required_real = np.maximum(0.0, q + ev_draw - float(feeder_kw))  # (N, n_steps)
    a = np.minimum(np.asarray(r_t, dtype=DTYPE)[None, :], required_real)  # actuator
    post_total = q + (ev_draw - a)  # building + curtailed EV (D-05 reuse below)
    realized = float(is_overloaded(post_total, float(feeder_kw)).any(axis=1).mean())
    return {"a": a, "realized_p_overload": realized, "post_total": post_total}


def resource_value(r_t: np.ndarray, a: np.ndarray) -> dict[str, float]:
    """Return the resource-value totals + the ``a_t <= r_t`` / ratio invariants (CTRL-03).

    Args:
        r_t: The ``(n_steps,)`` day-ahead reserve.
        a: The ``(n_scen, n_steps)`` activation (plan or realize).

    Returns:
        ``{sum_r, e_sum_a, ratio_e_sum_a_over_sum_r}`` — ``Sum r``, ``E[Sum a]`` and
        the activation/reservation ratio (emitted for Phase 16, D-12).

    Raises:
        ValueError: If the ``a_t <= r_t`` invariant is violated (D-10 / Pitfall 4).
    """
    r = np.asarray(r_t, dtype=DTYPE)
    act = np.asarray(a, dtype=DTYPE)
    if not bool(np.all(act <= r[None, :] + 1e-9)):
        raise ValueError(
            "ev_hosting_flex stage 5 (controller): the a_t <= r_t resource-value "
            "invariant is violated (the actuator must not activate more than the "
            "reserved cap). Remediation: the activation MUST be "
            "a = min(r_t, required) at 100% enrollment (D-08); do not add an "
            "enrollment-cap term that breaks the closed-form oracle (Pitfall 4)."
        )
    sum_r = float(r.sum())
    e_sum_a = float(act.sum(axis=1).mean())
    ratio = float(e_sum_a / sum_r) if sum_r > 0.0 else 0.0
    return {
        "sum_r": sum_r,
        "e_sum_a": e_sum_a,
        "ratio_e_sum_a_over_sum_r": ratio,
    }


def flexible_from_curve(
    curve: list[float], *, eps: float = EPS_HEADLINE
) -> tuple[int, float]:
    """Return the largest adoption with realized ``P(overload) <= eps`` (CTRL-04).

    Mirrors ``firm_transformer_count``'s LAST-IN-TOLERANCE accumulation (NO early
    break): the nested cumulative EV pool makes realized ``P(overload)`` monotone
    non-decreasing in ``n_ev``, so "largest with ``P <= eps``" is the well-defined
    flexible count. The cost / break-even gate is NOT applied (D-12; Phase 16).

    Args:
        curve: The realized ``P(overload)`` per adoption ``n_ev`` (index = ``n_ev``).
        eps: The realized-reliability tolerance (default ``EPS_HEADLINE``).

    Returns:
        ``(flexible_ev_count, realized_p_overload_at_flexible)``; ``(0, curve[0])``
        if only the zero-EV count passes.
    """
    flexible = 0
    p_at = float(curve[0]) if curve else 0.0
    for n_ev, p in enumerate(curve):
        if float(p) <= float(eps):
            flexible = n_ev
            p_at = float(p)  # last-in-tolerance: keep updating, NO break (CONG-02)
    return int(flexible), float(p_at)


def _adversarial_q_real(
    design_day: pd.DataFrame,
    n_homes: int,
    *,
    n: int = OOS_N,
    res_minutes: int = DESIGN_DAY_RES_MINUTES,
    delta_c: float = ADVERSARIAL_DELTA_C,
) -> np.ndarray:
    """Return a pinned colder ``(n, n_steps)`` adversarial ``Q_real`` ensemble (D-11).

    Regenerates the validation building base over a DISJOINT adversarial seed block
    (``SEED + ADV_SEED_OFFSET + r``) with the design-day temperature offset by
    ``delta_c`` (-5 degC), via ``building_realization(..., t_offset=delta_c)`` — a
    third disjoint block distinct from both the plan (``SEED``) and OOS
    (``SEED + OOS_SEED_OFFSET``) blocks (RESEARCH A4). Reported, never gated (D-11).

    Args:
        design_day: The 1-min design-day frame (``select_design_day`` output).
        n_homes: Number of dwellings on the idx-62 subtree.
        n: The adversarial ensemble size (default ``OOS_N``).
        res_minutes: The design-day resolution (default ``DESIGN_DAY_RES_MINUTES``).
        delta_c: The pinned colder temperature offset in degC (default -5).

    Returns:
        A ``(n, n_steps)`` float64 colder building-base ensemble (kW).
    """
    rows = [
        building_realization(
            design_day,
            int(n_homes),
            int(SEED) + int(ADV_SEED_OFFSET) + r,
            int(res_minutes),
            t_offset=float(delta_c),
        )
        for r in range(int(n))
    ]
    return np.stack(rows).astype(DTYPE)


def derive_controller(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the two-stage controller headline + governed artifacts.

    Reads the design-day ``q_real``/``q_design``/``ev_pool_design`` artifacts + the
    Phase-14 ``firm_hosting.json`` denominator (firm=3, never re-run), plans the
    reserve on ``Q_design`` (disjoint plan seed), draws a FRESH disjoint OOS
    ``Q_real`` ensemble + a colder adversarial ensemble, sweeps adoption to the
    reliability-only flexible count, validates the in-band realized ``P(overload)``,
    and writes the reserve/activation + realized-reliability + flexible-hosting
    artifacts (round-before-write + content sha256).

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars (unused here beyond
            symmetry; the design-day path is artifact-driven).
        data_dir: Directory the parquet artifacts are written to AND the design-day
            ``.npy`` artifacts are read from.
        json_dir: Directory the flexible-hosting JSON is written to AND the
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a degenerate firm denominator, a pool-ceiling saturation, or a
            broken resource-value invariant.
    """
    firm = _load_json(json_dir / "firm_hosting.json")
    firm_ev = int(firm["firm_ev_count"])
    feeder_kw = float(firm.get("feeder_transformer_modeled_kw", _FEEDER_TRANSFORMER_KW))
    feeder_key = str(firm.get("feeder_key", "transformer:?"))
    homes = int(firm.get("downstream_home_count", 7))
    if firm_ev <= 0:
        raise ValueError(
            "ev_hosting_flex stage 5 (controller): degenerate firm_ev_count="
            f"{firm_ev} read from firm_hosting.json for feeder {feeder_key}; the "
            "hosting_expansion_percent denominator must be > 0. Remediation: re-run "
            "stage 4 (compute_congestion.py) so the firm leg is a positive count."
        )

    q_design = _load_npy(data_dir / "q_design.npy")  # (n_steps,)
    ev_max = int(DESIGN_DAY_EV_MAX)

    # ── REALIZE: a FRESH disjoint OOS Q_real ensemble (Pitfall 1; D-03) ──
    # Drawn at controller time from SEED + OOS_SEED_OFFSET — a draw the plan never
    # saw (NOT the on-disk q_real.npy, which is the plan-adjacent K=60 block).
    design_day = select_design_day()
    oos = make_design_day_ensemble(
        n_homes=homes,
        k=int(OOS_N),
        seed=int(SEED) + int(OOS_SEED_OFFSET),
        res_minutes=int(DESIGN_DAY_RES_MINUTES),
        n_ev_max=ev_max,
        design_day=design_day,
    )
    q_real_oos = np.asarray(oos["Q_real"], dtype=DTYPE)  # (N, n_steps)
    ev_pool_oos = np.asarray(oos["ev_pool"], dtype=DTYPE)  # (N, ev_max+1, n_steps)
    q_real_adv = _adversarial_q_real(design_day, homes)  # (N, n_steps) colder

    # ── SWEEP (CTRL-04, D-12): plan r_t(n_ev) on Q_design, validate realized P ──
    # over the disjoint OOS ensemble; last-in-tolerance, NO early break.
    realized_curve: list[float] = []
    plan_cache: dict[int, dict[str, object]] = {}
    realize_cache: dict[int, dict[str, object]] = {}
    for n_ev in range(ev_max + 1):
        plan = plan_reserve(
            q_design=q_design, n_ev=n_ev, feeder_kw=feeder_kw, eps=EPS_HEADLINE
        )
        rv_out = realize_validate(
            r_t=plan["r"],
            q_real=q_real_oos,
            ev_pool=ev_pool_oos,
            n_ev=n_ev,
            feeder_kw=feeder_kw,
        )
        plan_cache[n_ev] = plan
        realize_cache[n_ev] = rv_out
        realized_curve.append(float(rv_out["realized_p_overload"]))

    flexible_ev, realized_p_at_flex = flexible_from_curve(
        realized_curve, eps=EPS_HEADLINE
    )
    if flexible_ev >= ev_max and realized_curve[ev_max] <= EPS_HEADLINE:
        # Pool ceiling reached: the reliability gate never binds inside the pool
        # (A3) — surface rather than silently capping the headline.
        pool_ceiling_warning = (
            f"pool ceiling reached: flexible_ev_count saturated at "
            f"DESIGN_DAY_EV_MAX={ev_max} with realized P(overload)="
            f"{realized_curve[ev_max]:.6f} <= eps={EPS_HEADLINE} — regenerate the "
            "design-day MC with a higher DESIGN_DAY_EV_MAX to find the true crossing."
        )
    else:
        pool_ceiling_warning = ""

    # ── In-band assertion + the realized-vs-eps gap (CTRL-02, D-02) ──
    realized_gap = float(realized_p_at_flex - EPS_HEADLINE)
    hosting_pct = round((flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS)
    if realized_p_at_flex > EPS_HEADLINE + _REALIZED_EPS_TOL:
        raise ValueError(
            "ev_hosting_flex stage 5 (controller): realized P(overload) at the "
            f"flexible count ({realized_p_at_flex:.6f}) exceeds eps={EPS_HEADLINE} "
            f"by more than the in-band tolerance {_REALIZED_EPS_TOL:.6f}; the "
            "out-of-sample reliability gate failed. Remediation: this is the "
            "harder-truth finding (D-02) — investigate the Q_design vs Q_real "
            "variance gap, do NOT relax the gate."
        )
    # The D-02 forecast-blindness diagnostic that EXPLAINS the negative finding:
    # Q_design (the plan ensemble anchor) carries only the +-3%/degC forecast
    # variance, so its peak is BLIND to the building-base spread the disjoint OOS
    # Q_real draw actually realizes. Quantify both so the harder-truth note cites
    # live numbers (the realized-vs-eps gap is the central scientific result, D-02).
    q_design_peak = float(np.asarray(q_design, dtype=DTYPE).max())
    oos_peaks = q_real_oos.max(axis=1)  # (N,) per-realization daily peak (kW)
    oos_peak_p95 = float(np.quantile(oos_peaks, 0.95, method="linear"))
    oos_peak_max = float(oos_peaks.max())

    harder_truth_note = ""
    if flexible_ev < firm_ev:
        # THE central finding (user Option-A authorization, 2026-06-26): on this
        # calibration the honest out-of-sample controller does NOT expand hosting
        # above firm. Surface it PROMINENTLY — it is reported, never hidden or gated.
        harder_truth_note = (
            f"HARDER TRUTH THAN FORECAST (D-02, the central finding): the two-stage "
            f"day-ahead curtailment controller does NOT expand hosting above firm on "
            f"this calibration out-of-sample — flexible_ev_count={flexible_ev} < "
            f"firm_ev_count={firm_ev} (hosting_expansion_percent={hosting_pct}). Root "
            f"cause is the D-02 forecast asymmetry, NOT a bug: Q_design (the plan "
            f"ensemble anchor, peak ~{q_design_peak:.1f} kW, carrying only the "
            f"+-3%/degC forecast variance) is BLIND to the building-base spread the "
            f"disjoint out-of-sample Q_real draw actually realizes (per-realization "
            f"daily peak p95={oos_peak_p95:.1f} kW, max={oos_peak_max:.1f} kW). The "
            f"reserve therefore under-provisions and barely binds at low EV counts, "
            f"so realized reliability degrades into eps before the firm count is "
            f"reached. The realized-vs-eps gap and the two-disjoint-draws methodology "
            f"(reserve NEVER quantiled over the in-sample Q_real, Pitfall 1) are the "
            f"scientific result. realized P(overload)={realized_p_at_flex:.6f} <= "
            f"eps={EPS_HEADLINE} holds AT flexible_ev_count={flexible_ev}; reported, "
            f"not hidden."
        )
    elif realized_p_at_flex > EPS_HEADLINE:
        harder_truth_note = (
            f"harder truth than forecast (D-02): realized P(overload)="
            f"{realized_p_at_flex:.6f} at the flexible count sits ABOVE the planning "
            f"eps={EPS_HEADLINE} (gap {realized_gap:+.6f}), within the in-band "
            f"tolerance {_REALIZED_EPS_TOL:.6f} — the out-of-sample reserve is "
            "modestly under-conservative vs the in-sample plan; reported, not hidden."
        )

    # ── ADVERSARIAL (CTRL-02, D-11): same r_t, colder Q_real, reported not gated ──
    flex_plan = plan_cache[flexible_ev]
    r_t_flex = np.asarray(flex_plan["r"], dtype=DTYPE)
    adv = realize_validate(
        r_t=r_t_flex,
        q_real=q_real_adv,
        ev_pool=ev_pool_oos,
        n_ev=flexible_ev,
        feeder_kw=feeder_kw,
    )
    adversarial_p = float(adv["realized_p_overload"])

    # ── RESOURCE VALUE (CTRL-03, D-10): r_t vs E[a_t], ratio, cold-day panel ──
    rv = resource_value(r_t_flex, np.asarray(flex_plan["a"], dtype=DTYPE))
    realize_a = np.asarray(realize_cache[flexible_ev]["a"], dtype=DTYPE)
    e_a_t = realize_a.mean(axis=0)  # (n_steps,) realized E[a_t]
    panel = coldday_panel(np.asarray(flex_plan["required_plan"], dtype=DTYPE))

    # ── ARTIFACTS (round-before-write + content sha256) ──
    data_dir.mkdir(parents=True, exist_ok=True)
    n_steps = int(q_design.shape[0])

    reserve_activation = pd.DataFrame(
        {
            "hour": np.arange(n_steps),
            "r_t": np.round(r_t_flex, ROUND_DECIMALS),
            "e_a_t": np.round(e_a_t, ROUND_DECIMALS),
            "req_p50": np.round(
                np.asarray(panel["req_p50"], dtype=DTYPE), ROUND_DECIMALS
            ),
            "req_p90": np.round(
                np.asarray(panel["req_p90"], dtype=DTYPE), ROUND_DECIMALS
            ),
        }
    )
    reserve_path = data_dir / "reserve_activation.parquet"
    reserve_activation.to_parquet(reserve_path)

    realized_rows = pd.DataFrame(
        {
            "ev_count": np.arange(ev_max + 1),
            "ev_per_home": np.round(
                np.arange(ev_max + 1) / float(homes), ROUND_DECIMALS
            ),
            "realized_p_overload": np.round(
                np.asarray(realized_curve, dtype=DTYPE), ROUND_DECIMALS
            ),
        }
    )
    realized_path = data_dir / "realized_reliability.parquet"
    realized_rows.to_parquet(realized_path)

    reserve_matrix = np.round(
        np.vstack([r_t_flex, e_a_t]).astype("float64"), ROUND_DECIMALS
    )
    realized_arr = np.round(np.asarray(realized_curve, dtype="float64"), ROUND_DECIMALS)

    # The headline-shift framing: lead with the HONEST sign of the result. When the
    # reliability gate yields flexible < firm (the authorized Option-A finding) this
    # is a falsified-hypothesis negative result, NOT an expansion — say so plainly.
    if flexible_ev < firm_ev:
        headline_clause = (
            f"the reliability-gated flexible count ({flexible_ev}) sits BELOW the "
            f"firm count ({firm_ev}, read from firm_hosting.json, never re-run) under "
            f"the two-stage day-ahead curtailment controller — hosting_expansion_"
            f"percent={hosting_pct} (a NEGATIVE result: the controller does NOT expand "
            f"hosting above firm on this calibration out-of-sample). This FALSIFIES "
            f"the plan's 'flexible > firm' hypothesis and is the central scientific "
            f"finding (D-02 forecast-blindness; see the harder_truth note), reported "
            f"honestly and not gated."
        )
    else:
        headline_clause = (
            f"the citable headline shifts from the firm count ({firm_ev}, read from "
            f"firm_hosting.json, never re-run) to the reliability-gated flexible count "
            f"({flexible_ev}) under the two-stage day-ahead curtailment controller — a "
            f"{hosting_pct:+} hosting expansion."
        )
    divergence_note = (
        f"Re-baseline (Phase 15 CTRL-04): {headline_clause} "
        "ROADMAP Phase-15 criterion #4 ('AND contract cost below break-even') is "
        "EXPLICITLY DIVERGED from per CONTEXT D-12 (authoritative): Phase 15 gates "
        "flexible_ev_count on realized P(overload) <= eps ALONE; the contract-cost / "
        "break-even gate is deferred to Phase 16, which applies it to the emitted "
        f"sum_r / e_sum_a totals WITHOUT re-running. Realized P(overload)="
        f"{realized_p_at_flex:.6f} vs eps={EPS_HEADLINE} (gap {realized_gap:+.6f}); "
        f"adversarial (-5 degC) P(overload)={adversarial_p:.6f} (reported, not gated)."
    )

    flexible_payload = {
        "firm_ev_count": firm_ev,
        "flexible_ev_count": flexible_ev,
        "hosting_expansion_percent": hosting_pct,
        "realized_p_overload_at_flexible": round(realized_p_at_flex, ROUND_DECIMALS),
        "realized_minus_eps_gap": round(realized_gap, ROUND_DECIMALS),
        "adversarial_p_overload": round(adversarial_p, ROUND_DECIMALS),
        "adversarial_delta_c": float(ADVERSARIAL_DELTA_C),
        "eps": float(EPS_HEADLINE),
        "sum_r": round(rv["sum_r"], ROUND_DECIMALS),
        "e_sum_a": round(rv["e_sum_a"], ROUND_DECIMALS),
        "ratio_e_sum_a_over_sum_r": round(
            rv["ratio_e_sum_a_over_sum_r"], ROUND_DECIMALS
        ),
        "downstream_home_count": homes,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": round(feeder_kw, ROUND_DECIMALS),
        "oos_n": int(OOS_N),
        "oos_seed_offset": int(OOS_SEED_OFFSET),
        "threshold_convention": "strict_gt_rating",
        "reserve_activation_content_sha256": _content_sha256(reserve_matrix),
        "realized_reliability_content_sha256": _content_sha256(realized_arr),
        "q_design_peak_kw": round(q_design_peak, ROUND_DECIMALS),
        "oos_q_real_peak_p95_kw": round(oos_peak_p95, ROUND_DECIMALS),
        "oos_q_real_peak_max_kw": round(oos_peak_max, ROUND_DECIMALS),
        "harder_truth": harder_truth_note,
        "divergence_note": divergence_note,
    }
    flexible_path = _write_json(json_dir / "flexible_hosting.json", flexible_payload)

    # Lead the governed report's warnings with the harder-truth note when it is the
    # negative-result finding (flexible < firm) so the central scientific result is
    # the FIRST thing a report reader sees (D-02; user Option-A authorization).
    warnings = []
    if harder_truth_note:
        warnings.append(harder_truth_note)
    warnings.append(divergence_note)
    if pool_ceiling_warning:
        warnings.append(pool_ceiling_warning)

    summary = {
        "firm_ev_count": firm_ev,
        "flexible_ev_count": flexible_ev,
        "hosting_expansion_percent": hosting_pct,
        "realized_p_overload_at_flexible": round(realized_p_at_flex, ROUND_DECIMALS),
        "realized_minus_eps_gap": round(realized_gap, ROUND_DECIMALS),
        "adversarial_p_overload": round(adversarial_p, ROUND_DECIMALS),
        "eps": float(EPS_HEADLINE),
        "sum_r": round(rv["sum_r"], ROUND_DECIMALS),
        "e_sum_a": round(rv["e_sum_a"], ROUND_DECIMALS),
        "ratio_e_sum_a_over_sum_r": round(
            rv["ratio_e_sum_a_over_sum_r"], ROUND_DECIMALS
        ),
        "downstream_home_count": homes,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": round(feeder_kw, ROUND_DECIMALS),
        "oos_n": int(OOS_N),
        "q_design_peak_kw": round(q_design_peak, ROUND_DECIMALS),
        "oos_q_real_peak_p95_kw": round(oos_peak_p95, ROUND_DECIMALS),
        "oos_q_real_peak_max_kw": round(oos_peak_max, ROUND_DECIMALS),
        "reserve_activation_content_sha256": _content_sha256(reserve_matrix),
        "realized_reliability_content_sha256": _content_sha256(realized_arr),
        "harder_truth": harder_truth_note,
        "divergence_note": divergence_note,
    }

    return {
        "artifact_paths": [reserve_path, realized_path, flexible_path],
        "summary": summary,
        "warnings": warnings,
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full controller stage: derive + parquet/JSON + governed report.

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

    derived = derive_controller(effective_cache_dir, effective_data_dir, json_dir)
    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]
    warnings = derived["warnings"]  # type: ignore[assignment]

    # Govern the load-bearing upstream provenance: the firm denominator + the
    # design-day forecast/realize inputs that wholly determine the controller result.
    inputs = [
        script.file_reference(json_dir / "firm_hosting.json"),
        script.file_reference(effective_data_dir / "q_design.npy"),
        script.file_reference(effective_data_dir / "q_real.npy"),
        script.file_reference(effective_data_dir / "ev_pool_design.npy"),
    ]

    return script.write_report(
        "flexibility_contracts_report",
        inputs=inputs,
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": list(warnings)},
    )


def main() -> None:
    """CLI entry point for the two-stage controller stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Applied two-stage controller + report: "
        f"firm_ev_count={summary.get('firm_ev_count')} -> "
        f"flexible_ev_count={summary.get('flexible_ev_count')} "
        f"(+{summary.get('hosting_expansion_percent')}) | "
        f"realized_P(overload)={summary.get('realized_p_overload_at_flexible')} "
        f"(eps={summary.get('eps')}) | "
        f"adversarial_P(overload)={summary.get('adversarial_p_overload')}"
    )


if __name__ == "__main__":
    main()

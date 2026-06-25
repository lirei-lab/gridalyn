"""Apply flexibility contracts: three-scenario power-limited availability sweep.

Stage 5 of the workflow (DAYTIME-04/05, amends RECAL-07/08 / FLEX-01..04). The
flexibility sibling of stage-4 ``compute_congestion.py``: it reads ONLY the stage-2
topology cache JSON sidecars, the stage-3 annual profile parquet, the stage-3
``(K, 8760)`` stochastic EV stack, and the stage-4 ``firm_hosting.json`` (GUARD-02 —
never the pickled net), and emits the re-baselined flexible leg:

* **Power-limited availability curves (D-04, the headline leg)** — the new
  ``flex_power_limited`` natural-charging mechanism swept over THREE availability
  scenarios (``overnight`` home-only / ``workplace`` home+daytime ``[9-16]`` /
  ``all_day`` ceiling). For each scenario, at each penetration, over the K
  realizations the aggregate EV draw is throttled per hour to
  ``min(draw, max(0, rating − base))`` walked chronologically across the day's
  available sessions (undelivered energy carries forward to the day's next session);
  energy still undelivered after the day's last session is the UNSERVED energy. The
  per-realization unserved-energy fraction is reduced over K at P95 and gated strict
  ``< TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95`` (1%). ``workplace`` is the citable
  HEADLINE (D-07). Each scenario reports ``flexible_ev_count`` +
  ``hosting_expansion_percent = (flexible − firm) / firm`` against the firm count
  READ from ``firm_hosting.json`` (D-07, the firm leg is NEVER re-run here).
* **Curtailment curve (retained, Phase-12 continuity)** — the kept Phase-10
  closed-form shed-to-limit cap over the feeder subtree (``flex_curtailment``). Its
  ``flexible_ev_count`` is the largest penetration passing the curtailed-energy
  fraction gate; ``hosting_expansion_percent = (flexible − firm) / firm``. The
  curtailment lost-fraction is a SEPARATE column/concern from the power-limited
  unserved gate; it backs the kept ``line_loading_flex.parquet`` capped loading.

The flexible-leg mechanism is power-limited charging; the 10.1 valley-fill deferral
kernel is REMOVED from this pipeline path (left dormant-importable in the kernel
module). The curtailment leg + the SC4 monotonicity tripwire survive the rewrite.

Artifacts:

* ``data/line_loading_flex.parquet`` — ``(n_elements, 8760)`` CAPPED loading% at the
  curtailment-flexible state (every feeder element ≤ the limit, FLEX-01 retained);
* ``data/availability_curve.parquet`` — the tidy THREE-scenario power-limited
  trade-curve (``scenario``, ``penetration``, ``ev_count``,
  ``unserved_fraction_p95``) + the retained ``curtailed_lost_fraction_p95`` column;
* ``json/flexible_hosting.json`` — the firm head + a ``scenarios`` mapping (overnight
  / workplace / all_day) + ``headline_scenario: "workplace"`` + the retained
  curtailment block + the read firm denominator;
* ``reports/flexibility_contracts_report.json`` — canonical platform report carrying
  both ``availability_curve_content_sha256`` (the NEW flexible-leg output, DAYTIME-05)
  and the retained ``flex_loading_content_sha256`` (the unchanged-curtailment guard).

**The unit of congestion is the MODELED small HQ LV transformer (D-01).** The feeder
transformer element rating is ``TRANSFORMER_KVA × POWER_FACTOR`` (D-02), the SAME
modeled rating stage 4 uses, not the cache subtree rating.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` / ``lightsim2grid``.
This stage is pure-numpy + pandas/JSON IO; pandapower enters the study only at
Phase-11.
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
    downstream_indicator,
    feeder_elements,
    is_congested,
    proxy_loading,
)
from projects.ev_hosting_flex.scripts._flexibility import (  # noqa: E402
    flex_curtailment,
    flex_metrics,
    flex_power_limited,
)
from projects.ev_hosting_flex.scripts._profiles import (  # noqa: E402
    allocate_ev_per_bus,
)
from projects.ev_hosting_flex.scripts._stochastic import (  # noqa: E402
    mc_p95,
    tmy_start_hod,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    AVAILABILITY_SCENARIOS,
    DTYPE,
    EXTENDED_PENETRATION_SWEEP,
    LINE_LOADING_LIMIT_PERCENT,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
    TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95,
    TRANSFORMER_KVA,
)

# ``is_congested`` is re-exported for downstream tooling parity with stage 4.
_ = is_congested

# The citable headline scenario (D-07): workplace home+daytime availability.
HEADLINE_SCENARIO = "workplace"

# The modeled small HQ LV transformer rating in kW (D-01/D-02) — the SAME modeled
# rating stage 4 keys congestion off, not the cache subtree rating.
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
            f"ev_hosting_flex stage 5 requires {path.name} at {path}, but it is "
            "missing. Remediation: re-run stage 2 (prepare_topology_cache.py), "
            "stage 3 (generate_annual_profiles.py), and stage 4 "
            "(compute_congestion.py) before applying flexibility contracts."
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
            f"ev_hosting_flex stage 5: profile {parquet_path.name} is missing buses "
            f"{missing[:10]}{'...' if len(missing) > 10 else ''}. Remediation: "
            "re-run generate_annual_profiles.py so the profiles cover the feeder's "
            "downstream load buses."
        )
    return frame.loc[bus_ids].to_numpy(dtype=DTYPE)


def _read_ev_stack(npy_path: Path) -> np.ndarray:
    """Read the stage-3 ``(K, 8760)`` EV stack (per-EV-unit realizations)."""
    if not npy_path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 5 requires the stochastic EV stack "
            f"{npy_path.name} at {npy_path}, but it is missing. Remediation: re-run "
            "stage 3 (generate_annual_profiles.py)."
        )
    return np.load(npy_path).astype(DTYPE)  # (K, 8760)


def _availability_sweep(
    base: np.ndarray,
    ev_stack: np.ndarray,
    indicator: np.ndarray,
    feeder_row: int,
    feeder_kw: float,
    alloc_fn,
    downstream_home_count: int,
    limit: float,
    start_hod: int = 0,
) -> dict[str, list[dict[str, object]]]:
    """Sweep the THREE availability scenarios + the retained curtailment curve.

    For each ``AVAILABILITY_SCENARIOS`` scenario (the OUTER loop), sweep penetration
    and, over the K realizations at each swept penetration, reduce the per-realization
    POWER-LIMITED unserved-energy fraction at the binding FEEDER TRANSFORMER element to
    P95. The aggregate EV draw is throttled per hour by ``flex_power_limited`` (the
    ``max(0, rating − base)`` headroom is the cap, walked chronologically across the
    scenario's per-day sessions with carry-forward); the per-realization gate value is
    ``out["unserved_fraction"]``. The CURTAILMENT lost fraction (the over-cap shed
    ``excess`` energy, scenario-independent) is computed alongside and reduced over K
    at P95 — the retained Phase-10 trade-curve column + the ``line_loading_flex``
    capped-loading basis (a SEPARATE concern from the power-limited unserved gate).

    Both the per-scenario unserved P95 and the curtailment P95 carry the SC4
    monotonic-non-decreasing tripwire (more EV energy => at least as much unfittable
    remainder). The over-cap determination routes through the kept ``is_congested``
    (strict ``>``, no second epsilon); the power-limited headroom cap encodes the same
    convention inside ``flex_power_limited``.

    Args:
        base: ``(n_bus, n_hour)`` float64 TMY base demand in kW.
        ev_stack: ``(K, n_hour)`` per-EV-unit realization stack.
        indicator: ``(n_elem, n_bus)`` downstream matrix.
        feeder_row: The feeder transformer element row index (its downstream sum
            aggregates the whole subtree).
        feeder_kw: The modeled feeder transformer kW rating (the headroom).
        alloc_fn: ``penetration -> (n_bus,)`` per-bus EV allocation.
        downstream_home_count: The feeder's downstream home count (EV-count units).
        limit: The loading-percent congestion limit (strict ``>``).
        start_hod: The TMY's first-row clock hour-of-day (session segmentation phase).

    Returns:
        ``{"scenarios": {name: [rows...]}, "curtailment": [rows...]}`` where each
        scenario row carries ``penetration / ev_count / unserved_fraction_p95`` and the
        curtailment row carries ``penetration / ev_count / curtailed_lost_fraction_p95``.
    """
    feeder_indicator = indicator[feeder_row]  # (n_bus,)
    # The feeder-transformer aggregate base (downstream-sum), shared across
    # realizations (the base is deterministic). The headroom per hour.
    base_feeder = feeder_indicator @ base  # (n_hour,)
    headroom = np.maximum(0.0, float(feeder_kw) - base_feeder)  # (n_hour,)
    k = int(ev_stack.shape[0])

    # Pre-compute the per-penetration EV scale + count once (penetration-independent
    # of scenario); reused across the scenario loop and the curtailment curve. The
    # sweep reads EXTENDED_PENETRATION_SWEEP (the append-only 0 → 5.0 grid) so the
    # overnight unserved cliff lands inside the effective sweep (RESEARCH Pitfall 2);
    # the frozen PENETRATION_SWEEP (0 → 2.0) is never edited — this is the single
    # re-point site (DAYTIME-04 / T-10.3-06).
    pens = list(EXTENDED_PENETRATION_SWEEP)
    ev_scales: list[float] = []
    ev_counts: list[int] = []
    for penetration in pens:
        per_bus_ev = alloc_fn(float(penetration))  # (n_bus,)
        ev_scales.append(float(feeder_indicator @ per_bus_ev))
        ev_counts.append(int(round(float(penetration) * downstream_home_count)))

    # ── The retained CURTAILMENT curve (scenario-independent over-cap excess) ──
    curtail_curve: list[dict[str, object]] = []
    prev_curt_p95 = -1.0
    for pi, penetration in enumerate(pens):
        ev_unit_feeder_scale = ev_scales[pi]
        curt_fractions = np.empty(k, dtype=DTYPE)
        for kk in range(k):
            ev_feeder = ev_stack[kk] * ev_unit_feeder_scale  # (n_hour,)
            total = float(ev_feeder.sum())
            loading = (base_feeder + ev_feeder) / float(feeder_kw) * 100.0
            over = is_congested(loading, limit)  # strict-> reuse, no second epsilon
            placed = np.minimum(ev_feeder, headroom)
            excess = float(np.where(over, ev_feeder - placed, 0.0).sum())
            curt_fractions[kk] = excess / total if total > 0 else 0.0
        curt_p95 = mc_p95(curt_fractions)
        if curt_p95 + 10.0**-ROUND_DECIMALS < prev_curt_p95:
            raise ValueError(
                "ev_hosting_flex stage 5: P95 curtailment-lost fraction decreased "
                f"from {prev_curt_p95} to {curt_p95} as penetration rose to "
                f"{penetration} EV/home — it must be monotonic non-decreasing (SC4). "
                "Remediation: an alloc_fn / curtailment bug broke the trade curve."
            )
        prev_curt_p95 = curt_p95
        curtail_curve.append(
            {
                "penetration": float(round(float(penetration), ROUND_DECIMALS)),
                "ev_count": ev_counts[pi],
                "curtailed_lost_fraction_p95": float(round(curt_p95, ROUND_DECIMALS)),
            }
        )

    # ── The THREE power-limited availability scenario curves (the headline leg) ──
    scenario_curves: dict[str, list[dict[str, object]]] = {}
    for scenario, sessions in AVAILABILITY_SCENARIOS.items():
        curve: list[dict[str, object]] = []
        prev_unserved_p95 = -1.0
        for pi, penetration in enumerate(pens):
            ev_unit_feeder_scale = ev_scales[pi]
            unserved_fractions = np.empty(k, dtype=DTYPE)
            for kk in range(k):
                ev_feeder = ev_stack[kk] * ev_unit_feeder_scale  # (n_hour,)
                # charger_kw=inf: at aggregate level the natural EV draw is the only
                # non-headroom ceiling; the max(0, rating - base) headroom binds first
                # (RESEARCH Open-Q1 / Assumption A1). The throttle walks each day's
                # sessions chronologically with carry-forward.
                out = flex_power_limited(
                    ev_feeder,
                    base_feeder,
                    feeder_kw,
                    sessions=sessions,
                    charger_kw=float("inf"),
                    limit=limit,
                    start_hod=start_hod,
                )
                unserved_fractions[kk] = float(out["unserved_fraction"])
            unserved_p95 = mc_p95(unserved_fractions)
            # SC4 monotonicity tripwire per scenario: the P95 unserved fraction is
            # non-decreasing in penetration (more EV energy => at least as much
            # undeliverable remainder at throttled power).
            if unserved_p95 + 10.0**-ROUND_DECIMALS < prev_unserved_p95:
                raise ValueError(
                    "ev_hosting_flex stage 5: P95 unserved-energy fraction decreased "
                    f"from {prev_unserved_p95} to {unserved_p95} as penetration rose "
                    f"to {penetration} EV/home in scenario {scenario!r} — it must be "
                    "monotonic non-decreasing (SC4). Remediation: an alloc_fn / "
                    "power-limit bug broke the trade curve."
                )
            prev_unserved_p95 = unserved_p95
            curve.append(
                {
                    "penetration": float(round(float(penetration), ROUND_DECIMALS)),
                    "ev_count": ev_counts[pi],
                    "unserved_fraction_p95": float(round(unserved_p95, ROUND_DECIMALS)),
                }
            )
        scenario_curves[scenario] = curve

    return {"scenarios": scenario_curves, "curtailment": curtail_curve}


def _curve_flexible(
    curve: list[dict[str, object]], frac_key: str, tolerance: float
) -> tuple[int, float]:
    """Return the largest EV count whose P95 lost fraction is strictly < tolerance.

    Args:
        curve: The per-penetration trade-curve rows from ``_availability_sweep``.
        frac_key: The P95 lost-fraction key to gate on.
        tolerance: The strict-``<`` P95 tolerance.

    Returns:
        ``(flexible_ev_count, lost_fraction_p95_at_flexible)``.
    """
    passing = [
        int(row["ev_count"]) for row in curve if float(row[frac_key]) < float(tolerance)
    ]
    flexible = max(passing) if passing else 0
    at_flex = 0.0
    for row in curve:
        if int(row["ev_count"]) == flexible:
            at_flex = float(row[frac_key])
    return flexible, at_flex


def _session_windows(sessions) -> list[list[int]]:
    """Return the scenario's session windows as JSON-serializable hour lists."""
    return [[int(h) for h in window] for window in sessions]


def _gate_scenarios(
    scenario_curves: dict[str, list[dict[str, object]]], firm_ev: int
) -> dict[str, dict[str, object]]:
    """Gate each scenario's curve on the P95 unserved-energy tolerance (D-04).

    Args:
        scenario_curves: ``{scenario: [rows...]}`` from ``_availability_sweep``.
        firm_ev: The read firm denominator (the per-scenario feasibility floor).

    Returns:
        ``{scenario: block}`` — one ``mechanism="power_limited"`` block per scenario.

    Raises:
        ValueError: If a scenario's flexible count lands below the firm count.
    """
    unserved_tol = float(TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95)
    scenario_blocks: dict[str, dict[str, object]] = {}
    for scenario, curve in scenario_curves.items():
        flexible_ev, unserved_at_flex = _curve_flexible(
            curve, "unserved_fraction_p95", unserved_tol
        )
        # WR-01 per scenario: the firm count is a feasible passing point, so a
        # scenario's flexible count may not land below it (Pitfall 5, per scenario).
        if flexible_ev < firm_ev:
            raise ValueError(
                "ev_hosting_flex stage 5: power-limited flexible_ev_count="
                f"{flexible_ev} for scenario {scenario!r} is below firm_ev_count="
                f"{firm_ev}; the firm count is a feasible point and MUST pass. "
                "Remediation: a feasibility / P95-gate bug dropped a point that "
                "should pass — re-check the AVAILABILITY_SCENARIOS sessions and "
                "TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95; do NOT relax the gate."
            )
        hosting_pct = round((flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS)
        scenario_blocks[scenario] = {
            "mechanism": "power_limited",
            "flexible_ev_count": flexible_ev,
            "hosting_expansion_percent": hosting_pct,
            "unserved_fraction_p95_at_flexible": float(
                round(unserved_at_flex, ROUND_DECIMALS)
            ),
            "session_windows": _session_windows(AVAILABILITY_SCENARIOS[scenario]),
            "tolerance_unserved_energy_fraction_max_p95": unserved_tol,
        }
    return scenario_blocks


def _availability_table(
    scenario_curves: dict[str, list[dict[str, object]]],
    curtail_curve: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build the tidy three-scenario availability trade-curve rows (DAYTIME-04).

    One row per (scenario, penetration); the scenario-independent curtailment lost
    fraction is joined by penetration as a retained column (Phase-12 continuity).
    """
    curt_by_pen = {
        float(row["penetration"]): float(row["curtailed_lost_fraction_p95"])
        for row in curtail_curve
    }
    rows: list[dict[str, object]] = []
    for scenario, curve in scenario_curves.items():
        for row in curve:
            rows.append(
                {
                    "scenario": scenario,
                    "penetration": row["penetration"],
                    "ev_count": row["ev_count"],
                    "unserved_fraction_p95": row["unserved_fraction_p95"],
                    "curtailed_lost_fraction_p95": curt_by_pen.get(
                        float(row["penetration"]), 0.0
                    ),
                }
            )
    return rows


def _availability_matrix(
    scenario_curves: dict[str, list[dict[str, object]]],
) -> np.ndarray:
    """Return the canonical [scenario x penetration] unserved-P95 matrix (DAYTIME-05).

    A fixed scenario/penetration order, rounded to ``ROUND_DECIMALS`` — the
    byte-stability fingerprint of the NEW power-limited flexible-leg output.
    """
    scenario_order = list(AVAILABILITY_SCENARIOS.keys())
    matrix = np.array(
        [
            [float(row["unserved_fraction_p95"]) for row in scenario_curves[s]]
            for s in scenario_order
        ],
        dtype="float64",
    )
    return np.round(matrix, ROUND_DECIMALS).astype("float64")


def derive_flexibility(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the three-scenario power-limited leg + retained curtailment.

    Reads the cache sidecars + stage-3 profiles + the stage-3 EV stack + the stage-4
    ``firm_hosting.json`` (pandapower-free), builds the feeder-subtree proxy with the
    MODELED transformer rating (D-01/D-02), sweeps the THREE availability scenarios
    with ``flex_power_limited`` (gated on the P95 unserved-energy fraction) AND the
    retained curtailment curve, reads (NEVER re-runs) the firm denominator, and writes
    the curtailment capped loading + the three-scenario availability trade curve + the
    ``flexible_hosting.json`` (firm head + scenarios + headline + curtailment block).

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars.
        data_dir: Directory the loading + trade-curve parquet are written to.
        json_dir: Directory the flexible-hosting JSON is written to AND the stage-4
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a non-positive rating, an empty feeder subtree, a degenerate
            firm denominator, or a per-scenario flexible-below-firm curve.
    """
    ratings = _load_json(cache_dir / "line_transformer_ratings_kw.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    feeder = _load_json(cache_dir / "feeder_selection.json")
    node_building_count = _load_json(cache_dir / "node_building_count.json")
    # The stage-4 output: the headline denominator (D-07, never recomputed).
    firm = _load_json(json_dir / "firm_hosting.json")

    # Read the feeder key at runtime — never hardcode the transformer index.
    feeder_idx = int(feeder["feeder_transformer_idx"])
    feeder_key = f"transformer:{feeder_idx}"

    elements, feeder_buses = feeder_elements(downstream, feeder_key)
    feeder_row = elements.index(feeder_key)

    load_buses = {int(b) for b in node_building_count}
    bus_ids = sorted(set(feeder_buses) & load_buses)
    if not bus_ids:
        raise ValueError(
            f"ev_hosting_flex stage 5: feeder {feeder_key} has no downstream load "
            "buses in node_building_count.json. Remediation: verify the load-aware "
            "topology cache was built from the expected feeder."
        )

    indicator = downstream_indicator(elements, bus_ids, downstream)
    elem_kw = np.empty(len(elements), dtype=DTYPE)
    for i, key in enumerate(elements):
        elem_kw[i] = (
            _FEEDER_TRANSFORMER_KW if key == feeder_key else float(ratings[key])
        )
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "ev_hosting_flex stage 5: a feeder element has a non-positive kW rating "
            f"(min={float(elem_kw.min())}). Remediation: re-run "
            "prepare_topology_cache.py at pf>0 and verify TRANSFORMER_KVA > 0."
        )

    base = _read_profile(data_dir / "base_load_8760.parquet", bus_ids)
    ev_unit = _read_profile(data_dir / "ev_load_unit.parquet", bus_ids)
    ev_stack = _read_ev_stack(data_dir / "ev_stack_K.npy")

    building_count = np.array(
        [int(node_building_count[str(b)]) for b in bus_ids], dtype=DTYPE
    )
    downstream_home_count = int(building_count.sum())

    def alloc_fn(penetration: float) -> np.ndarray:
        total_ev = int(round(float(penetration) * downstream_home_count))
        return allocate_ev_per_bus(total_ev, building_count).astype(DTYPE)

    # The read firm denominator (D-07): guard a degenerate firm BEFORE dividing.
    firm_ev = int(firm["firm_ev_count"])
    firm_penetration = float(firm["firm_penetration"])
    if firm_ev <= 0:
        raise ValueError(
            "ev_hosting_flex stage 5: degenerate firm_ev_count="
            f"{firm_ev} read from firm_hosting.json for feeder {feeder_key}; the "
            "hosting_expansion_percent denominator must be > 0. Remediation: re-run "
            "stage 4 (compute_congestion.py) so the firm leg is a positive count."
        )

    # ── The three power-limited availability scenario curves + the retained ──
    # curtailment curve, each reduced over the K-axis at P95. CR-02: the per-day
    # session segmentation needs the annual clock phase the EV stack/base were
    # aligned to (tmy_start_hod after CR-01).
    start_hod = tmy_start_hod()
    swept = _availability_sweep(
        base,
        ev_stack,
        indicator,
        feeder_row,
        _FEEDER_TRANSFORMER_KW,
        alloc_fn,
        downstream_home_count,
        float(LINE_LOADING_LIMIT_PERCENT),
        start_hod,
    )
    scenario_curves = swept["scenarios"]  # type: ignore[assignment]
    curtail_curve = swept["curtailment"]  # type: ignore[assignment]

    scenario_blocks = _gate_scenarios(scenario_curves, firm_ev)

    # Curtailment-flexible: largest EV count with P95 curtailed-lost fraction < the
    # curtailed-energy tolerance (the retained conservative shed-to-limit bound).
    curtail_flexible_ev, curtail_lost_p95 = _curve_flexible(
        curtail_curve,
        "curtailed_lost_fraction_p95",
        float(TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX),
    )
    if curtail_flexible_ev < firm_ev:
        raise ValueError(
            "ev_hosting_flex stage 5: curtailment flexible_ev_count="
            f"{curtail_flexible_ev} is below firm_ev_count={firm_ev}; the firm "
            "count is a feasible point and MUST pass. Remediation: a feasibility/"
            "tolerance gate or cap bug dropped a point that should pass — re-check "
            "the sweep grid and TOLERANCE_* config; do NOT relax the tolerance."
        )
    curtail_hosting_pct = round(
        (curtail_flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS
    )

    # ── The kept closed-form cap capped-loading parquet (FLEX-01 artifact) ──
    # Recompute the CAPPED loading at the curtailment-flexible state on the MEAN EV
    # unit: the kept node-level cap relieves every feeder element to <= the limit
    # (the FLEX-01 capped-loading reference for Phase-12). The P95 curtailed-lost
    # FRACTION (the trade-curve column) comes from the stochastic sweep above.
    per_bus = alloc_fn(curtail_flexible_ev / downstream_home_count)
    ev_demand = ev_unit * per_bus[:, None]
    demand = base + ev_demand
    cap = flex_curtailment(
        indicator, demand, ev_demand, elem_kw, float(LINE_LOADING_LIMIT_PERCENT)
    )
    loading_flex, _ = proxy_loading(indicator, demand - cap["curtailed"], elem_kw)
    loading_flex_rounded = np.round(loading_flex, ROUND_DECIMALS).astype("float64")

    flex_metrics_at_limit = flex_metrics(
        cap["curtailed"],
        ev_demand,
        ev_demand.sum(axis=1),
        total_annual_ev_demand=float(ev_demand.sum()),
    )

    data_dir.mkdir(parents=True, exist_ok=True)
    columns = [f"h{h}" for h in range(loading_flex_rounded.shape[1])]
    loading_path = data_dir / "line_loading_flex.parquet"
    pd.DataFrame(loading_flex_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(loading_path)

    # The tidy THREE-scenario availability trade curve (the schema Phase-11/12's
    # trade-curve figure consumes directly). One row per (scenario, penetration) with
    # the power-limited unserved P95 + the retained curtailment lost fraction (joined
    # by penetration — the curtailment fraction is scenario-independent).
    availability_rows = _availability_table(scenario_curves, curtail_curve)
    availability_path = data_dir / "availability_curve.parquet"
    pd.DataFrame(
        availability_rows,
        columns=[
            "scenario",
            "penetration",
            "ev_count",
            "unserved_fraction_p95",
            "curtailed_lost_fraction_p95",
        ],
    ).to_parquet(availability_path)

    # The canonical [scenario x penetration] unserved_fraction_p95 matrix in a fixed
    # scenario/penetration order — the byte-stability fingerprint of the NEW
    # flexible-leg output (DAYTIME-05). Round-before-hash to ROUND_DECIMALS.
    availability_matrix = _availability_matrix(scenario_curves)

    curtailment_block = {
        "mechanism": "curtailment",
        "flexible_ev_count": curtail_flexible_ev,
        "hosting_expansion_percent": curtail_hosting_pct,
        "curtailed_lost_fraction_p95_at_flexible": float(
            round(curtail_lost_p95, ROUND_DECIMALS)
        ),
        "tolerance_curtailed_energy_fraction_max": float(
            TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX
        ),
        "capped_loading_feasible_at_flexible": bool(cap["feasible"]),
        "capped_curtailed_energy_mwh_at_flexible": flex_metrics_at_limit[
            "curtailed_energy_mwh"
        ],
    }

    headline_block = scenario_blocks[HEADLINE_SCENARIO]
    rebaseline_note = (
        "Re-baseline (D-08): the flexible leg is POWER-LIMITED natural charging "
        "(flex_power_limited), swept over three availability scenarios "
        "(overnight / workplace[9-16] HEADLINE / all_day) and gated on the "
        "unserved-energy fraction at P95 < 1%. This REPLACES the 10.1 valley-fill "
        "deferral mechanism. The curtailment curve is retained as a separate column "
        "(Phase-12 continuity). The workplace lift comes from the extra ~8 daytime "
        "hours, not richer midday headroom (the validated +~5% margin is weak)."
    )

    flexible_payload = {
        "firm_ev_count": firm_ev,
        "firm_penetration": firm_penetration,
        "headline_scenario": HEADLINE_SCENARIO,
        "scenarios": scenario_blocks,
        "curtailment": curtailment_block,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
        "scope": "feeder_subtree",
        "n_feeder_bus": len(bus_ids),
        "n_elements": len(elements),
        "downstream_home_count": downstream_home_count,
        "threshold_convention": "strict_gt_limit",
        "availability_ordering": {
            "firm_ev_count": firm_ev,
            "overnight_flexible_ev_count": scenario_blocks["overnight"][
                "flexible_ev_count"
            ],
            "workplace_flexible_ev_count": scenario_blocks["workplace"][
                "flexible_ev_count"
            ],
            "all_day_flexible_ev_count": scenario_blocks["all_day"][
                "flexible_ev_count"
            ],
            "ordering_holds": bool(
                scenario_blocks["overnight"]["flexible_ev_count"]  # type: ignore[operator]
                <= scenario_blocks["workplace"]["flexible_ev_count"]
                <= scenario_blocks["all_day"]["flexible_ev_count"]
            ),
        },
        "rebaseline_note": rebaseline_note,
    }
    flexible_path = _write_json(json_dir / "flexible_hosting.json", flexible_payload)

    return {
        "artifact_paths": [
            loading_path,
            availability_path,
            flexible_path,
        ],
        "summary": {
            "firm_ev_count": firm_ev,
            "firm_penetration": firm_penetration,
            "headline_scenario": HEADLINE_SCENARIO,
            "headline_flexible_ev_count": headline_block["flexible_ev_count"],
            "headline_hosting_expansion_percent": headline_block[
                "hosting_expansion_percent"
            ],
            "scenarios": scenario_blocks,
            "curtailment": curtailment_block,
            "availability_ordering": flexible_payload["availability_ordering"],
            "feeder_key": feeder_key,
            "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
            "scope": "feeder_subtree",
            "n_feeder_bus": len(bus_ids),
            "n_elements": len(elements),
            "downstream_home_count": downstream_home_count,
            "threshold_convention": "strict_gt_limit",
            "availability_curve_content_sha256": _content_sha256(availability_matrix),
            "flex_loading_content_sha256": _content_sha256(loading_flex_rounded),
            "rebaseline_note": rebaseline_note,
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full flexibility stage: derive + parquet/JSON + governed report.

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

    derived = derive_flexibility(effective_cache_dir, effective_data_dir, json_dir)
    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]
    rebaseline_note = summary["rebaseline_note"]  # type: ignore[index]

    # WR-02: govern the headline's load-bearing upstream provenance (the firm
    # denominator + the stage-3 inputs that wholly determine the swept result).
    inputs = [
        script.file_reference(json_dir / "firm_hosting.json"),
        script.file_reference(effective_data_dir / "base_load_8760.parquet"),
        script.file_reference(effective_data_dir / "ev_load_unit.parquet"),
        script.file_reference(effective_data_dir / "ev_stack_K.npy"),
    ]

    return script.write_report(
        "flexibility_contracts_report",
        inputs=inputs,
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": [rebaseline_note]},
    )


def main() -> None:
    """CLI entry point for the flexibility-contracts stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    scenarios = summary.get("scenarios", {})
    parts = []
    for name in ("overnight", "workplace", "all_day"):
        block = scenarios.get(name, {})
        marker = " (HEADLINE)" if name == summary.get("headline_scenario") else ""
        parts.append(
            f"{name}{marker} flexible={block.get('flexible_ev_count')} "
            f"(+{block.get('hosting_expansion_percent')})"
        )
    print(
        "Applied flexibility contracts + report: "
        f"firm_ev_count={summary.get('firm_ev_count')} | " + " | ".join(parts)
    )


if __name__ == "__main__":
    main()

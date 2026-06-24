"""Apply per-node flexibility contracts + BOTH hosting-expansion curves.

Stage 5 of the workflow (RECAL-07/08, amends FLEX-01/02/03/04). The flexibility
sibling of stage-4 ``compute_congestion.py``: it reads ONLY the stage-2 topology
cache JSON sidecars, the stage-3 annual profile parquet, the stage-3 ``(K, 8760)``
stochastic EV stack, and the stage-4 ``firm_hosting.json`` (GUARD-02 — never the
pickled net), and emits BOTH flexibility curves (D-10) with NO single headline
mechanism:

* **Curtailment curve** — the kept Phase-10 closed-form shed-to-limit cap over the
  feeder subtree (``flex_curtailment`` / ``flexible_ev_count``). Its
  ``flexible_ev_count`` is the largest penetration passing the curtailed-energy
  fraction gate; ``hosting_expansion_percent = (flexible − firm) / firm``.
* **Deferral curve** — the new in-window valley-fill mechanism (``flex_deferral``,
  D-11). For each penetration, over the K realizations, the over-cap EV energy is
  valley-filled into the EV's plug-in window; the irreducible-lost-energy fraction
  is reduced over K at P95 (D-07/D-12). Its ``flexible_ev_count`` is the largest
  penetration whose P95 irreducible-lost fraction is strictly ``<
  TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95`` (1%); ``hosting_expansion_percent
  = (flexible − firm) / firm``.

Both curves report their own ``flexible_ev_count`` and ``hosting_expansion_percent``
against the re-baselined firm read from ``firm_hosting.json`` (D-11, never
recomputed). The trade-curve ordering ``firm ≤ curtail-flexible ≤ defer-flexible``
is the manuscript "EVs shift, not drop" story (SC4).

Artifacts:

* ``data/line_loading_flex.parquet`` — ``(n_elements, 8760)`` CAPPED loading% at
  the curtailment-flexible state (every feeder element ≤ the limit, FLEX-01);
* ``data/contract_activations.parquet`` — the tidy curtailment trade-curve series;
* ``data/deferral_curve.parquet`` — the per-penetration deferral trade-curve
  (penetration, ev_count, curtailed_lost_fraction_p95,
  irreducible_lost_fraction_p95, deferral_feasible), where ``deferral_feasible``
  is ``irreducible_lost_fraction_p95 < TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95``;
* ``json/flexible_hosting.json`` — BOTH curve blocks + the read firm denominator;
* ``reports/flexibility_contracts_report.json`` — canonical platform report.

**The unit of congestion is the MODELED small HQ LV transformer (D-01).** The
feeder transformer element rating is ``TRANSFORMER_KVA × POWER_FACTOR`` (D-02), the
SAME modeled rating stage 4 uses, not the cache subtree rating.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. This stage is pure-numpy + pandas/JSON IO; pandapower enters
the study only at Phase-11.
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
    flex_deferral,
    flex_metrics,
)
from projects.ev_hosting_flex.scripts._profiles import (  # noqa: E402
    allocate_ev_per_bus,
)
from projects.ev_hosting_flex.scripts._stochastic import (  # noqa: E402
    mc_p95,
    tmy_start_hod,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    LINE_LOADING_LIMIT_PERCENT,
    PENETRATION_SWEEP,
    PLUGIN_WINDOW,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
    TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95,
    TRANSFORMER_KVA,
)

# ``is_congested`` is re-exported for downstream tooling parity with stage 4.
_ = is_congested

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


def _two_curve_sweep(
    base: np.ndarray,
    ev_stack: np.ndarray,
    indicator: np.ndarray,
    feeder_row: int,
    feeder_kw: float,
    alloc_fn,
    downstream_home_count: int,
    limit: float,
    start_hod: int = 0,
) -> list[dict[str, object]]:
    """Sweep penetration and return BOTH curves' per-penetration P95 trade curve.

    Over the K realizations at each swept penetration, the per-realization aggregate
    EV draw + base at the binding FEEDER TRANSFORMER element drive the manuscript
    ``_relief`` two-mechanism reduction (port of
    ``congestion_tradecurve_mc.py:_relief`` L91-104, the validated reference): the
    CURTAILMENT lost fraction is the over-cap ``excess`` energy that would be shed,
    and the DEFERRAL lost fraction is the IRREDUCIBLE ``remaining`` after in-window
    valley-fill (``flex_deferral``, D-11). Both are reduced over K at P95
    (D-07/D-12). Both route the over-cap determination through ``is_congested``
    (strict ``>``, no second epsilon) — the deferral path inside ``flex_deferral``,
    the curtailment path here.

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

    Returns:
        The per-penetration list of trade-curve rows, each carrying the EV count,
        the P95 curtailment-lost fraction, and the P95 deferral-lost fraction.
    """
    feeder_indicator = indicator[feeder_row]  # (n_bus,)
    # The feeder-transformer aggregate base (downstream-sum), shared across
    # realizations (the base is deterministic). The curtailment headroom per hour.
    base_feeder = feeder_indicator @ base  # (n_hour,)
    headroom = np.maximum(0.0, float(feeder_kw) - base_feeder)  # (n_hour,)
    k = int(ev_stack.shape[0])

    curve: list[dict[str, object]] = []
    prev_curt_p95 = -1.0
    prev_defer_p95 = -1.0
    for penetration in PENETRATION_SWEEP:
        per_bus_ev = alloc_fn(float(penetration))  # (n_bus,)
        # Total feeder EV count = downstream-sum of the per-bus EV allocation.
        ev_unit_feeder_scale = float(feeder_indicator @ per_bus_ev)
        ev_count = int(round(float(penetration) * downstream_home_count))

        curt_fractions = np.empty(k, dtype=DTYPE)
        defer_fractions = np.empty(k, dtype=DTYPE)
        for kk in range(k):
            ev_feeder = ev_stack[kk] * ev_unit_feeder_scale  # (n_hour,)
            total = float(ev_feeder.sum())
            # CURTAILMENT (manuscript _relief excess): the over-cap energy shed at
            # the strictly-over-limit hours (placed = min(ev, headroom)).
            loading = (base_feeder + ev_feeder) / float(feeder_kw) * 100.0
            over = is_congested(loading, limit)  # strict-> reuse, no second epsilon
            placed = np.minimum(ev_feeder, headroom)
            excess = float(np.where(over, ev_feeder - placed, 0.0).sum())
            curt_fractions[kk] = excess / total if total > 0 else 0.0
            # DEFERRAL (the kept in-window valley-fill kernel): irreducible remainder.
            out = flex_deferral(
                ev_feeder,
                base_feeder,
                feeder_kw,
                plugin_window=PLUGIN_WINDOW,
                limit=limit,
                start_hod=start_hod,
            )
            defer_fractions[kk] = float(out["irreducible_lost_fraction"])

        curt_p95 = mc_p95(curt_fractions)
        defer_p95 = mc_p95(defer_fractions)

        # SC4 monotonicity tripwire: both P95 lost fractions are non-decreasing in
        # penetration (more EV energy => at least as much unfittable remainder).
        if curt_p95 + 10.0**-ROUND_DECIMALS < prev_curt_p95:
            raise ValueError(
                "ev_hosting_flex stage 5: P95 curtailment-lost fraction decreased "
                f"from {prev_curt_p95} to {curt_p95} as penetration rose to "
                f"{penetration} EV/home — it must be monotonic non-decreasing (SC4). "
                "Remediation: an alloc_fn / curtailment bug broke the trade curve."
            )
        if defer_p95 + 10.0**-ROUND_DECIMALS < prev_defer_p95:
            raise ValueError(
                "ev_hosting_flex stage 5: P95 deferral-lost fraction decreased from "
                f"{prev_defer_p95} to {defer_p95} as penetration rose to "
                f"{penetration} EV/home — it must be monotonic non-decreasing (SC4). "
                "Remediation: an alloc_fn / deferral bug broke the trade curve."
            )
        prev_curt_p95 = curt_p95
        prev_defer_p95 = defer_p95

        curve.append(
            {
                "penetration": float(round(float(penetration), ROUND_DECIMALS)),
                "ev_count": ev_count,
                "curtailed_lost_fraction_p95": float(round(curt_p95, ROUND_DECIMALS)),
                "irreducible_lost_fraction_p95": float(
                    round(defer_p95, ROUND_DECIMALS)
                ),
            }
        )
    return curve


def _curve_flexible(
    curve: list[dict[str, object]], frac_key: str, tolerance: float
) -> tuple[int, float]:
    """Return the largest EV count whose P95 lost fraction is strictly < tolerance.

    Args:
        curve: The per-penetration trade-curve rows from ``_two_curve_sweep``.
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


def derive_flexibility(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist BOTH flexibility curves + the read firm denominator.

    Reads the cache sidecars + stage-3 profiles + the stage-3 EV stack + the
    stage-4 ``firm_hosting.json`` (pandapower-free), builds the feeder-subtree proxy
    with the MODELED transformer rating (D-01/D-02), runs the kept curtailment sweep
    (mean EV unit) AND the new deferral sweep (K-axis, P95), and writes the
    curtailment capped loading + both trade curves + the two-curve
    ``flexible_hosting.json``.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars.
        data_dir: Directory the loading + trade-curve parquet are written to.
        json_dir: Directory the flexible-hosting JSON is written to AND the stage-4
            ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a non-positive rating, an empty feeder subtree, a degenerate
            firm denominator, or a flexible-below-firm curve.
    """
    ratings = _load_json(cache_dir / "line_transformer_ratings_kw.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    feeder = _load_json(cache_dir / "feeder_selection.json")
    node_building_count = _load_json(cache_dir / "node_building_count.json")
    # The stage-4 output: the headline denominator (D-11, never recomputed).
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

    # The read firm denominator (D-11): guard a degenerate firm BEFORE dividing.
    firm_ev = int(firm["firm_ev_count"])
    firm_penetration = float(firm["firm_penetration"])
    if firm_ev <= 0:
        raise ValueError(
            "ev_hosting_flex stage 5: degenerate firm_ev_count="
            f"{firm_ev} read from firm_hosting.json for feeder {feeder_key}; the "
            "hosting_expansion_percent denominator must be > 0. Remediation: re-run "
            "stage 4 (compute_congestion.py) so the firm leg is a positive count."
        )

    # ── BOTH curves over the K-axis at P95 (the manuscript _relief two-mechanism ──
    # reduction): curtailment-lost (over-cap excess) AND deferral-lost (irreducible
    # remainder after in-window valley-fill), each reduced over K at P95 (D-07/D-10).
    # CR-02: the deferral valley-fill is confined to each overnight plug-in session;
    # segmenting needs the annual clock phase the EV stack/base were aligned to.
    start_hod = tmy_start_hod()
    trade_curve = _two_curve_sweep(
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
    # Curtailment-flexible: largest EV count with P95 curtailed-lost fraction < the
    # curtailed-energy tolerance (the conservative shed-to-limit bound).
    curtail_flexible_ev, curtail_lost_p95 = _curve_flexible(
        trade_curve,
        "curtailed_lost_fraction_p95",
        float(TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX),
    )
    # Deferral-flexible: largest EV count with P95 irreducible-lost fraction < the
    # irreducible-lost tolerance (the EVs-shift story; D-12).
    defer_flexible_ev, defer_lost_p95 = _curve_flexible(
        trade_curve,
        "irreducible_lost_fraction_p95",
        float(TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95),
    )

    # WR-01: the firm count is a feasible passing point for BOTH curves, so neither
    # flexible count may land below it (Pitfall 5, re-expressed for both curves).
    if curtail_flexible_ev < firm_ev:
        raise ValueError(
            "ev_hosting_flex stage 5: curtailment flexible_ev_count="
            f"{curtail_flexible_ev} is below firm_ev_count={firm_ev}; the firm "
            "count is a feasible point and MUST pass. Remediation: a feasibility/"
            "tolerance gate or cap bug dropped a point that should pass — re-check "
            "the sweep grid and TOLERANCE_* config; do NOT relax the tolerance."
        )
    if defer_flexible_ev < firm_ev:
        raise ValueError(
            "ev_hosting_flex stage 5: deferral flexible_ev_count="
            f"{defer_flexible_ev} is below firm_ev_count={firm_ev}; the firm count "
            "is a feasible point and MUST pass the deferral curve. Remediation: a "
            "deferral / P95-gate bug dropped a point that should pass — re-check the "
            "PLUGIN_WINDOW and TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95 config."
        )

    # Per-mechanism headline: (flexible − firm) / firm against the re-baselined firm.
    curtail_hosting_pct = round(
        (curtail_flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS
    )
    defer_hosting_pct = round((defer_flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS)

    # ── The kept closed-form cap capped-loading parquet (FLEX-01 artifact) ──
    # Recompute the CAPPED loading at the curtailment-flexible state on the MEAN EV
    # unit: the kept node-level cap relieves every feeder element to <= the limit
    # (the FLEX-01 capped-loading reference for Phase-12). The P95 curtailed-lost
    # FRACTION (the trade-curve gate) comes from the stochastic two-curve sweep above.
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

    # The tidy two-curve trade-curve series — one row per swept penetration with
    # BOTH mechanisms' P95 lost fractions (the schema Phase-12's trade-curve figure
    # consumes directly).
    activations_path = data_dir / "contract_activations.parquet"
    pd.DataFrame(
        trade_curve,
        columns=[
            "penetration",
            "ev_count",
            "curtailed_lost_fraction_p95",
            "irreducible_lost_fraction_p95",
        ],
    ).to_parquet(activations_path)

    # The per-penetration DEFERRAL trade-curve (the same corrected ``_two_curve_sweep``
    # result, gated for the deferral mechanism). Persisting it keeps the on-disk
    # artifact consistent with the deferral headline in ``flexible_hosting.json``
    # (its ``deferral_feasible`` == the < tolerance gate ``_curve_flexible`` keys on),
    # so the shipped curve reproduces the cliff — NOT a stale 0-loss orphan.
    deferral_curve_path = data_dir / "deferral_curve.parquet"
    deferral_tol = float(TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95)
    deferral_rows = [
        {
            "penetration": row["penetration"],
            "ev_count": row["ev_count"],
            "curtailed_lost_fraction_p95": row["curtailed_lost_fraction_p95"],
            "irreducible_lost_fraction_p95": row["irreducible_lost_fraction_p95"],
            "deferral_feasible": bool(
                float(row["irreducible_lost_fraction_p95"]) < deferral_tol
            ),
        }
        for row in trade_curve
    ]
    pd.DataFrame(
        deferral_rows,
        columns=[
            "penetration",
            "ev_count",
            "curtailed_lost_fraction_p95",
            "irreducible_lost_fraction_p95",
            "deferral_feasible",
        ],
    ).to_parquet(deferral_curve_path)

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
    deferral_block = {
        "mechanism": "deferral",
        "flexible_ev_count": defer_flexible_ev,
        "hosting_expansion_percent": defer_hosting_pct,
        "irreducible_lost_fraction_p95_at_flexible": float(
            round(defer_lost_p95, ROUND_DECIMALS)
        ),
        "tolerance_irreducible_lost_fraction_max_p95": float(
            TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95
        ),
        "plugin_window": [int(h) for h in PLUGIN_WINDOW],
    }

    flexible_payload = {
        "firm_ev_count": firm_ev,
        "firm_penetration": firm_penetration,
        "curtailment": curtailment_block,
        "deferral": deferral_block,
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
        "scope": "feeder_subtree",
        "n_feeder_bus": len(bus_ids),
        "n_elements": len(elements),
        "downstream_home_count": downstream_home_count,
        "threshold_convention": "strict_gt_limit",
        "trade_curve_ordering": {
            "firm_ev_count": firm_ev,
            "curtail_flexible_ev_count": curtail_flexible_ev,
            "defer_flexible_ev_count": defer_flexible_ev,
            "ordering_holds": bool(firm_ev <= curtail_flexible_ev <= defer_flexible_ev),
        },
        "divergence_note": (
            "Re-baseline (D-10): BOTH flexibility curves are reported with NO single "
            "headline mechanism — curtailment (the conservative shed-to-limit bound) "
            "and in-window deferral (valley-fill, the EVs-shift story). The deferral "
            "curve gates on the irreducible-lost-energy fraction at P95 < 1% (D-12)."
        ),
    }
    flexible_path = _write_json(json_dir / "flexible_hosting.json", flexible_payload)

    return {
        "artifact_paths": [
            loading_path,
            activations_path,
            deferral_curve_path,
            flexible_path,
        ],
        "summary": {
            "firm_ev_count": firm_ev,
            "firm_penetration": firm_penetration,
            "curtailment": curtailment_block,
            "deferral": deferral_block,
            "trade_curve_ordering": flexible_payload["trade_curve_ordering"],
            "feeder_key": feeder_key,
            "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
            "scope": "feeder_subtree",
            "n_feeder_bus": len(bus_ids),
            "n_elements": len(elements),
            "downstream_home_count": downstream_home_count,
            "threshold_convention": "strict_gt_limit",
            "flex_loading_content_sha256": _content_sha256(loading_flex_rounded),
            "divergence_note": flexible_payload["divergence_note"],
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
    rebaseline_note = summary["divergence_note"]  # type: ignore[index]

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
    curt = summary.get("curtailment", {})
    defer = summary.get("deferral", {})
    print(
        "Applied flexibility contracts + report: "
        f"firm_ev_count={summary.get('firm_ev_count')} | "
        f"curtailment flexible={curt.get('flexible_ev_count')} "
        f"(+{curt.get('hosting_expansion_percent')}) | "
        f"deferral flexible={defer.get('flexible_ev_count')} "
        f"(+{defer.get('hosting_expansion_percent')})"
    )


if __name__ == "__main__":
    main()

"""Compute the probabilistic congestion + firm EV hosting limit for ev_hosting_flex.

Stage 4 of the workflow (RECAL-05/06, amends CONG-01/02/03). Reads ONLY the
stage-2 topology cache JSON sidecars + the stage-3 annual profile parquet + the
stage-3 ``(K, 8760)`` stochastic EV stack (GUARD-02 — never the pickled net),
runs the vectorized radial downstream-sum congestion proxy over the SELECTED
feeder subtree across all 8760h × K Monte-Carlo realizations (no per-hour AC
solve, D-10), reduces over K to the re-calibrated firm gate ``firm = P(cong) ≤
FIRM_PCONG_TOLERANCE`` (D-06), reports P95 congestion metrics over K (D-07), and
emits the named artifacts plus a governed report:

* ``data/line_loading_firm.parquet`` — ``(n_elements, 8760)`` loading% at the FIRM
  penetration on the MEAN EV realization (float64, rounded) — the firm BASELINE
  reference, kept for Phase-10/12;
* ``data/line_loading_p95.parquet`` — ``(n_elements, 8760)`` loading% at the firm
  penetration on the P95-congestion realization (the conservative headline state,
  D-07);
* ``json/congestion_metrics.json`` — the five project-local CONG-02 metrics
  reported at P95 over K (D-07) plus the Pearson ``r(loading, temp)`` correlation;
* ``json/firm_hosting.json`` — the re-calibrated firm: ``firm_penetration``
  (EV/home), ``firm_ev_count``, the per-penetration ``p_cong`` vector,
  ``p_cong_at_firm`` (``≤ FIRM_PCONG_TOLERANCE``), the ~6-home feeder assertion
  result, and the threshold convention;
* ``reports/congestion_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-02; never hand-written report JSON).

**The unit of congestion is the MODELED small HQ LV transformer (D-01).** The
feeder transformer element's kW rating is the MODELED ``TRANSFORMER_KVA ×
POWER_FACTOR`` (decoupled from the twin's physical 210 kVA nameplate, D-02), NOT
the cache's load-aware subtree rating — congestion keys off the modeled rating so
the transformer is a meaningful unit of congestion. The interior lines keep their
cache ratings.

Pitfall 1 (T-09-05) + Pitfall 4: before the proxy, assert ``grid_cache_meta.json``
shows ``lines.sizing.mode == "load_aware"`` AND the selected feeder is in the
(25/0.4 kV) LV/MV class with a downstream home count within tolerance of
``TARGET_HOMES`` (~6) — a stale cache encoding the old large feeder fails loudly.

Pitfall 3 / D-13: cap BLAS threads (``OMP_NUM_THREADS=1`` recommended at the
shell) around the K-fold matmul so the byte-stability tripwire does not flicker;
``ROUND_DECIMALS=6`` pre-write rounding pins the comparator.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas``. This stage is
pure-numpy + pandas/JSON IO; pandapower enters the study only at Phase-11.
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
    congestion_metrics,
    downstream_indicator,
    feeder_elements,
    firm_pcong_count,
    proxy_loading,
)
from projects.ev_hosting_flex.scripts._profiles import (  # noqa: E402
    allocate_ev_per_bus,
)
from projects.ev_hosting_flex.scripts._stochastic import (  # noqa: E402
    blend_ev_per_bus,
    mc_p95,
    tmy_start_hod,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    EV_COINCIDENCE_RHO,
    FIRM_PCONG_TOLERANCE,
    LINE_LOADING_LIMIT_PERCENT,
    PENETRATION_SWEEP,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
    SEED,
    TARGET_HOMES,
    TRANSFORMER_KVA,
)

# Tolerance (homes) on the ~6-home feeder assertion (Pitfall 4). The selected
# closest-to-TARGET_HOMES unit is idx 62 with 7 homes; a tolerance of 3 admits
# 3..9 homes (a genuinely small LV unit) and fails loudly on the old large feeder.
_FEEDER_HOMES_TOLERANCE = 3

# The modeled small HQ LV transformer rating in kW (D-01/D-02): TRANSFORMER_KVA at
# POWER_FACTOR. Congestion keys off THIS modeled rating, not the cache subtree
# rating (which would be the deprecated winter-envelope load-aware size).
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
            f"ev_hosting_flex stage 4 requires {path.name} at {path}, but it is "
            "missing. Remediation: re-run stage 2 (prepare_topology_cache.py) and "
            "stage 3 (generate_annual_profiles.py) before computing congestion."
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


def _assert_load_aware_small_lv_feeder(
    cache_dir: Path,
    feeder_key: str,
    downstream: dict,
    downstream_home_count: int,
) -> dict[str, object]:
    """Assert the cache is load-aware AND the feeder is the ~6-home small LV unit.

    Pitfall 1 / T-09-05: a stale or ``uniform``-mode topology cache silently
    corrupts the firm count. Pitfall 4 / T-10.1-09: a stale cache encoding the old
    LARGE feeder must fail loudly — the selected feeder MUST be a ``transformer:``
    element in the (25/0.4 kV) LV/MV class with a downstream home count within
    tolerance of ``TARGET_HOMES`` (~6).

    Args:
        cache_dir: Directory holding ``grid_cache_meta.json``.
        feeder_key: The runtime feeder element key.
        downstream: The parsed ``downstream_bus_map.json``.
        downstream_home_count: The feeder's downstream load-bus home count.

    Returns:
        A mapping describing the passed assertion (for the report summary).

    Raises:
        ValueError: If the sizing mode is not ``load_aware``, the feeder key is
            absent, the feeder is not an LV/MV transformer, or the home count is
            outside the ~6-home tolerance band.
    """
    meta = _load_json(cache_dir / "grid_cache_meta.json")
    config = meta.get("config", {})
    mode = config.get("lines", {}).get("sizing", {}).get("mode")
    if mode != "load_aware":
        raise ValueError(
            "ev_hosting_flex stage 4 requires a load-aware topology cache, but "
            f"grid_cache_meta.json reports sizing.mode={mode!r}. A uniform-mode "
            "cache yields wrong element ratings and a wrong firm count. "
            "Remediation: re-run prepare_topology_cache.py (the project config "
            "opts into lines.sizing.mode=load_aware)."
        )
    if feeder_key not in downstream:
        raise ValueError(
            f"ev_hosting_flex stage 4: feeder key {feeder_key!r} from "
            "feeder_selection.json is absent from downstream_bus_map.json. "
            "Remediation: re-run prepare_topology_cache.py so the feeder selection "
            "and downstream map come from the same net."
        )
    # The feeder MUST be a transformer (the small LV unit of congestion, D-01).
    if not feeder_key.startswith("transformer:"):
        raise ValueError(
            f"ev_hosting_flex stage 4: feeder key {feeder_key!r} is not a "
            "transformer element; the unit of congestion (D-01) must be the small "
            "HQ LV transformer. Remediation: re-run prepare_topology_cache.py so "
            "select_feeder picks the closest-to-TARGET_HOMES LV transformer."
        )
    # The LV/MV transformer class is (25/0.4 kV) per the cache meta (pandapower-free
    # voltage-class read). Confirm the cache models that class so a stale cache that
    # somehow re-pointed to a different voltage class fails loudly (Pitfall 4).
    lv_mv = config.get("transformers", {}).get("lv_mv", {})
    std_type = str(lv_mv.get("std_type", ""))
    if "25/0.4" not in std_type:
        raise ValueError(
            "ev_hosting_flex stage 4: the cache lv_mv transformer std_type "
            f"{std_type!r} is not the expected (25/0.4 kV) LV/MV class. "
            "Remediation: re-run prepare_topology_cache.py against the project net "
            "(the small HQ LV transformer is the 25/0.4 kV class, D-01)."
        )
    # The ~6-home assertion (Pitfall 4): a stale LARGE-feeder cache (e.g. the old
    # idx-78 26-dwelling subtree) would carry far more than TARGET_HOMES homes.
    if abs(int(downstream_home_count) - int(TARGET_HOMES)) > _FEEDER_HOMES_TOLERANCE:
        raise ValueError(
            "ev_hosting_flex stage 4: the selected feeder "
            f"{feeder_key} has {downstream_home_count} downstream homes, outside "
            f"the ~{TARGET_HOMES}-home tolerance band "
            f"(|{downstream_home_count} - {TARGET_HOMES}| > "
            f"{_FEEDER_HOMES_TOLERANCE}). A stale cache may encode the OLD large "
            "feeder. Remediation: re-run prepare_topology_cache.py --force-rebuild "
            "so feeder_selection.json points at the small LV transformer (D-03)."
        )
    return {
        "feeder_voltage_class": "25/0.4 kV",
        "feeder_std_type": std_type,
        "downstream_home_count": int(downstream_home_count),
        "target_homes": int(TARGET_HOMES),
        "homes_tolerance": int(_FEEDER_HOMES_TOLERANCE),
    }


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
            f"ev_hosting_flex stage 4: profile {parquet_path.name} is missing buses "
            f"{missing[:10]}{'...' if len(missing) > 10 else ''}. Remediation: "
            "re-run generate_annual_profiles.py so the profiles cover the feeder's "
            "downstream load buses."
        )
    return frame.loc[bus_ids].to_numpy(dtype=DTYPE)


def _read_ev_stack(npy_path: Path, n_bus: int) -> np.ndarray:
    """Read the stage-3 ``(K, 8760)`` EV stack and broadcast it to ``(K, n_bus, 8760)``.

    Every bus carries the same per-EV-unit realization shape (the per-bus EV count
    is applied at sweep time via ``allocate_ev_per_bus``), so the persisted
    ``(K, 8760)`` stack broadcasts to the per-bus axis without re-sampling.

    Args:
        npy_path: Path to the ``(K, 8760)`` stage-3 EV stack ``.npy``.
        n_bus: The per-bus axis width to broadcast across.

    Returns:
        A ``(K, n_bus, 8760)`` float64 EV-unit stack.

    Raises:
        FileNotFoundError: If the EV stack is missing (stale/incomplete stage 3).
    """
    if not npy_path.is_file():
        raise FileNotFoundError(
            f"ev_hosting_flex stage 4 requires the stochastic EV stack "
            f"{npy_path.name} at {npy_path}, but it is missing. Remediation: re-run "
            "stage 3 (generate_annual_profiles.py) so the (K, 8760) ev_stack_K.npy "
            "is written."
        )
    stack = np.load(npy_path).astype(DTYPE)  # (K, 8760)
    k = int(stack.shape[0])
    n_hour = int(stack.shape[1])
    return np.broadcast_to(stack[:, None, :], (k, n_bus, n_hour)).astype(DTYPE)


def derive_congestion(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the re-calibrated firm (P(cong)≤tol) + P95 metrics.

    Reads the cache sidecars + stage-3 profiles + the stage-3 EV stack
    (pandapower-free), validates the load-aware ~6-home LV feeder (Pitfall 1/4),
    builds the feeder-subtree proxy with the MODELED transformer rating (D-01/D-02),
    sweeps the K-axis to the firm ``P(cong) ≤ FIRM_PCONG_TOLERANCE`` crossing (D-06),
    reports the five CONG-02 metrics at P95 over K (D-07), and writes the firm + P95
    loading parquets + two JSON artifacts.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars.
        data_dir: Directory the loading parquet is written to.
        json_dir: Directory the metrics + firm-hosting JSON are written to.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.
    """
    ratings = _load_json(cache_dir / "line_transformer_ratings_kw.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    feeder = _load_json(cache_dir / "feeder_selection.json")
    node_building_count = _load_json(cache_dir / "node_building_count.json")

    # Read the feeder key at runtime — never hardcode the transformer index.
    feeder_idx = int(feeder["feeder_transformer_idx"])
    feeder_key = f"transformer:{feeder_idx}"

    elements, feeder_buses = feeder_elements(downstream, feeder_key)

    # EV-adoption denominator = feeder buses ∩ load buses (the per-bus
    # building-count sidecar keys), in deterministic SORTED bus order.
    load_buses = {int(b) for b in node_building_count}
    bus_ids = sorted(set(feeder_buses) & load_buses)
    if not bus_ids:
        raise ValueError(
            f"ev_hosting_flex stage 4: feeder {feeder_key} has no downstream load "
            "buses in node_building_count.json. Remediation: verify the load-aware "
            "topology cache was built from the expected feeder."
        )

    building_count = np.array(
        [int(node_building_count[str(b)]) for b in bus_ids], dtype=DTYPE
    )
    downstream_home_count = int(building_count.sum())

    # Pitfall 1 + Pitfall 4: load-aware cache + ~6-home (25/0.4 kV) feeder assertion.
    feeder_assertion = _assert_load_aware_small_lv_feeder(
        cache_dir, feeder_key, downstream, downstream_home_count
    )

    indicator = downstream_indicator(elements, bus_ids, downstream)

    # elem_kw: the feeder TRANSFORMER element uses the MODELED rating (D-01/D-02);
    # the interior lines keep their cache ratings. The feeder transformer is always
    # elements[0] (feeder_elements returns it first).
    elem_kw = np.empty(len(elements), dtype=DTYPE)
    for i, key in enumerate(elements):
        if key == feeder_key:
            elem_kw[i] = _FEEDER_TRANSFORMER_KW
        else:
            elem_kw[i] = float(ratings[key])
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "ev_hosting_flex stage 4: a feeder element has a non-positive kW rating "
            f"(min={float(elem_kw.min())}). Remediation: re-run "
            "prepare_topology_cache.py at pf>0 and verify TRANSFORMER_KVA > 0."
        )

    base = _read_profile(data_dir / "base_load_8760.parquet", bus_ids)
    ev_stack = _read_ev_stack(data_dir / "ev_stack_K.npy", len(bus_ids))
    k_realizations = int(ev_stack.shape[0])
    # The per-EV-unit (K, 8760) stack (every bus carries the same shape); the blend
    # kernel distributes the ρ-blended feeder aggregate across buses by alloc shares.
    ev_unit_k = np.asarray(ev_stack[:, 0, :], dtype=DTYPE)  # (K, 8760)
    start_hod = tmy_start_hod()

    # The penetration->per-bus EV allocation: EV/home penetration × downstream homes,
    # distributed by the largest-remainder Hamilton allocator over the buses.
    def alloc_fn(penetration: float) -> np.ndarray:
        total_ev = int(round(float(penetration) * downstream_home_count))
        return allocate_ev_per_bus(total_ev, building_count).astype(DTYPE)

    # PARTIAL-COINCIDENCE blend (EV-COINCIDENCE-RECAL): the per-bus blended EV demand
    # stack for an integer EV count. Distributes the byte-stable ρ-blended feeder
    # aggregate across buses by the SAME allocate_ev_per_bus shares so the
    # downstream-sum proxy (D-02) is preserved — proxy_loading is never bypassed.
    def blend_fn(total_ev: int) -> np.ndarray:
        per_bus_ev = allocate_ev_per_bus(int(total_ev), building_count).astype(DTYPE)
        return blend_ev_per_bus(
            ev_unit_k, per_bus_ev, EV_COINCIDENCE_RHO, seed=SEED, start_hod=start_hod
        )

    # ── The re-calibrated firm gate: firm = P(cong) ≤ FIRM_PCONG_TOLERANCE (D-06) ──
    firm = firm_pcong_count(
        base,
        ev_stack,
        alloc_fn,
        indicator,
        elem_kw,
        PENETRATION_SWEEP,
        float(FIRM_PCONG_TOLERANCE),
        float(LINE_LOADING_LIMIT_PERCENT),
        blend_fn=blend_fn,
    )

    firm_penetration = float(firm["firm_penetration"])
    firm_ev = int(firm["firm_ev_count"])

    # Degenerate-firm guard re-expressed for the fractional EV/home units (Pitfall 5):
    # the firm penetration must land strictly inside the sweep so the Phase-10
    # hosting_expansion_percent denominator is positive and a crossing was observed.
    sweep_max = float(max(PENETRATION_SWEEP))
    if not 0.0 < firm_penetration <= sweep_max:
        raise ValueError(
            "ev_hosting_flex stage 4: degenerate firm_penetration="
            f"{firm_penetration} for feeder {feeder_key} (firm_ev_count={firm_ev}, "
            f"sweep max={sweep_max}); it must satisfy 0 < firm_penetration <= "
            "max(PENETRATION_SWEEP) to be a usable Phase-10 denominator. "
            "firm_penetration==0 means the feeder is already congested at 0 EVs (a "
            "wrong modeled rating); Remediation: verify TRANSFORMER_KVA sizing or "
            "widen PENETRATION_SWEEP in config.py."
        )
    if firm_ev <= 0:
        raise ValueError(
            "ev_hosting_flex stage 4: firm_ev_count="
            f"{firm_ev} <= 0 (firm_penetration={firm_penetration}, "
            f"downstream_home_count={downstream_home_count}); the headline EV count "
            "must be positive. Remediation: a too-small TARGET_HOMES feeder or a "
            "too-coarse PENETRATION_SWEEP near the crossing — refine the sweep."
        )

    # ── Firm-penetration loading at the MEAN + P95 EV realizations (D-07) ──
    # The per-bus blended EV demand stack at the firm EV count (same ρ-blend the
    # firm gate swept), so the reported MEAN/P95 loading states are consistent with
    # the partial-coincidence firm (EV-COINCIDENCE-RECAL).
    ev_demand_firm = blend_fn(firm_ev)  # (K, n_bus, 8760)
    # Per-realization max loading over the feeder subtree, to find the P95
    # realization index (the conservative headline congestion state, D-07).
    per_realization_max = np.empty(k_realizations, dtype=DTYPE)
    for kk in range(k_realizations):
        demand_kk = base + ev_demand_firm[kk]
        loading_kk, _ = proxy_loading(indicator, demand_kk, elem_kw)
        per_realization_max[kk] = float(loading_kk.max())

    # MEAN realization (firm baseline reference) + P95 realization (headline).
    mean_demand = base + ev_demand_firm.mean(axis=0)
    loading_firm_mean, _ = proxy_loading(indicator, mean_demand, elem_kw)

    p95_max_loading = mc_p95(per_realization_max)
    # The realization whose subtree max-loading is closest to the P95 value is the
    # representative P95 congestion state (deterministic argmin over K).
    p95_idx = int(np.argmin(np.abs(per_realization_max - p95_max_loading)))
    p95_demand = base + ev_demand_firm[p95_idx]
    loading_p95, elem_demand_p95 = proxy_loading(indicator, p95_demand, elem_kw)

    # The five CONG-02 metrics at the P95 realization (D-07 conservative headline).
    metrics = congestion_metrics(
        loading_p95,
        elem_demand_p95,
        elem_kw,
        float(LINE_LOADING_LIMIT_PERCENT),
    )

    # Pearson r(loading, temp): the cold-evening tail correlation (manuscript
    # r≈-0.88). Computed over the feeder-transformer hourly loading vs the per-home
    # base proxy for temperature (base load rises as temperature falls). np.corrcoef
    # avoids a scipy dependency.
    feeder_loading_hourly = loading_p95[0]  # the feeder transformer element row
    base_proxy_hourly = base.sum(axis=0)  # higher base ≈ colder hour
    if (
        float(np.std(feeder_loading_hourly)) > 0
        and float(np.std(base_proxy_hourly)) > 0
    ):
        pearson_r_loading_basecold = float(
            round(
                float(np.corrcoef(feeder_loading_hourly, base_proxy_hourly)[0, 1]),
                ROUND_DECIMALS,
            )
        )
    else:
        pearson_r_loading_basecold = 0.0

    # Round before write so float noise < 1e-6 never reaches the comparator (D-12).
    loading_firm_rounded = np.round(loading_firm_mean, ROUND_DECIMALS).astype("float64")
    loading_p95_rounded = np.round(loading_p95, ROUND_DECIMALS).astype("float64")

    data_dir.mkdir(parents=True, exist_ok=True)
    columns = [f"h{h}" for h in range(loading_firm_rounded.shape[1])]
    loading_path = data_dir / "line_loading_firm.parquet"
    pd.DataFrame(loading_firm_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(loading_path)
    p95_path = data_dir / "line_loading_p95.parquet"
    pd.DataFrame(loading_p95_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(p95_path)

    metrics_payload = {
        **metrics,
        "state": "p95_firm",
        "p95_max_loading_percent": float(round(p95_max_loading, ROUND_DECIMALS)),
        "pearson_r_loading_vs_cold_base": pearson_r_loading_basecold,
        "k_realizations": k_realizations,
    }
    metrics_path = _write_json(json_dir / "congestion_metrics.json", metrics_payload)

    firm_payload = {
        "firm_penetration": float(round(firm_penetration, ROUND_DECIMALS)),
        "firm_ev_count": firm_ev,
        "p_cong": [float(round(v, ROUND_DECIMALS)) for v in firm["p_cong"]],
        "p_cong_at_firm": float(round(float(firm["p_cong_at_firm"]), ROUND_DECIMALS)),
        "firm_pcong_tolerance": float(FIRM_PCONG_TOLERANCE),
        "penetration_sweep": [float(p) for p in firm["penetration_sweep"]],
        "downstream_home_count": downstream_home_count,
        "threshold_convention": firm["threshold_convention"],
        "feeder_key": feeder_key,
        "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
        "scope": "feeder_subtree",
        "n_feeder_bus": len(bus_ids),
        "n_elements": len(elements),
        "k_realizations": k_realizations,
        "feeder_assertion": feeder_assertion,
        "p95_max_loading_percent": float(round(p95_max_loading, ROUND_DECIMALS)),
    }
    firm_path = _write_json(json_dir / "firm_hosting.json", firm_payload)

    return {
        "artifact_paths": [loading_path, p95_path, metrics_path, firm_path],
        "summary": {
            **metrics,
            "state": "p95_firm",
            "firm_penetration": float(round(firm_penetration, ROUND_DECIMALS)),
            "firm_ev_count": firm_ev,
            "p_cong_at_firm": float(
                round(float(firm["p_cong_at_firm"]), ROUND_DECIMALS)
            ),
            "firm_pcong_tolerance": float(FIRM_PCONG_TOLERANCE),
            "p95_max_loading_percent": float(round(p95_max_loading, ROUND_DECIMALS)),
            "pearson_r_loading_vs_cold_base": pearson_r_loading_basecold,
            "downstream_home_count": downstream_home_count,
            "feeder_key": feeder_key,
            "feeder_transformer_modeled_kw": _FEEDER_TRANSFORMER_KW,
            "scope": "feeder_subtree",
            "n_feeder_bus": len(bus_ids),
            "n_elements": len(elements),
            "k_realizations": k_realizations,
            "feeder_assertion": feeder_assertion,
            # Byte-stability tripwire over BOTH rounded loading arrays.
            "loading_content_sha256": _content_sha256(loading_firm_rounded),
            "p95_loading_content_sha256": _content_sha256(loading_p95_rounded),
            "divergence_note": (
                "Re-baseline (D-06/D-07): firm = largest penetration with "
                "P(cong) <= FIRM_PCONG_TOLERANCE over K realizations (replaces the "
                "Phase-9 zero-overload firm); congestion metrics reported at P95 "
                "over K. The feeder transformer rating is the modeled "
                "TRANSFORMER_KVA*POWER_FACTOR (D-01/D-02), not the cache subtree "
                "rating."
            ),
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Run the full congestion stage: derive + parquet/JSON + governed report.

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
    rebaseline_note = summary["divergence_note"]  # type: ignore[index]

    return script.write_report(
        "congestion_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": [rebaseline_note]},
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
        "Computed congestion + report: "
        f"firm_penetration={summary.get('firm_penetration')} EV/home, "
        f"firm_ev_count={summary.get('firm_ev_count')}, "
        f"p_cong_at_firm={summary.get('p_cong_at_firm')}, "
        f"p95_max_loading={summary.get('p95_max_loading_percent')}%"
    )


if __name__ == "__main__":
    main()

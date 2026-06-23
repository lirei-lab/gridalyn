"""Compute the congestion proxy + firm EV hosting limit for ev_hosting_flex.

Stage 4 of the workflow (CONG-01/02/03). Reads ONLY the stage-2 topology cache
JSON sidecars + the stage-3 annual profile parquet (GUARD-02 — never the pickled
net), runs the vectorized radial downstream-sum congestion proxy over the
SELECTED feeder subtree across all 8760h (no per-hour AC solve, D-10), sweeps to
an integer ``firm_ev_count`` with a single pinned strict-``>`` threshold (D-09),
and emits the named artifacts plus a governed report:

* ``data/line_loading_firm.parquet`` — ``(n_elements, 8760)`` loading% at the FIRM
  count (float64, rounded to ROUND_DECIMALS) — the firm BASELINE (non-congested by
  construction), kept for the Phase-10/12 firm reference;
* ``data/line_loading_first_overload.parquet`` — ``(n_elements, 8760)`` loading% at
  the BINDING ``first_overload_ev_count`` state (float64, rounded), distinctly named
  so it is never conflated with the firm baseline;
* ``json/congestion_metrics.json`` — exactly the five project-local CONG-02 metrics
  computed at the BINDING (first-overload) state (NOT at the firm count, where they
  are vacuous by construction), plus explicit ``state`` / ``ev_count_at_metrics``
  labels (computed from the loading array, NOT ``summarize_network_constraints``, D-11);
* ``json/firm_hosting.json`` — ``firm_ev_count``, ``first_overload_ev_count``, the
  swept grid, the threshold convention, the pinned feeder-subtree scope, and a
  ``metrics_state`` / ``metrics_ev_count`` cross-reference recording WHERE the
  metrics were taken (no semantic change to ``firm_ev_count``);
* ``reports/congestion_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-02; never hand-written report JSON).

The five HEADLINE metrics AND the CIM-typed congestion constraint *set* (reusing
``gridalyn.operations.build_network_constraint_set``, D-11) are computed at the
BINDING ``first_overload_ev_count`` state — the state where ``is_congested`` is
actually true — so the four binding metrics + the constraint set are meaningful for
any correct firm count. ``firm_ev_count`` stays the unchanged headline scalar
(D-08/D-09); ``line_loading_firm.parquet`` keeps its firm-baseline semantics.

Pitfall 1 (T-09-05): before the proxy, assert ``grid_cache_meta.json`` shows
``lines.sizing.mode == "load_aware"`` and the runtime feeder key is present in
``downstream_bus_map.json`` — a stale / ``uniform``-mode cache would silently
corrupt the firm count, so it fails loudly with a located+remediating ValueError.

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

from gridalyn.operations import build_network_constraint_set  # noqa: E402
from projects.ev_hosting_flex.scripts._congestion import (  # noqa: E402
    congestion_metrics,
    downstream_indicator,
    feeder_elements,
    firm_ev_count,
    is_congested,
    proxy_loading,
)
from projects.ev_hosting_flex.scripts._profiles import (  # noqa: E402
    allocate_ev_per_bus,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    EV_SWEEP,
    LINE_LOADING_LIMIT_PERCENT,
    PROJECT_CACHE_DIR,
    ROUND_DECIMALS,
)


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


def _assert_load_aware_cache(cache_dir: Path, feeder_key: str, downstream: dict) -> None:
    """Assert the cache is load-aware and the runtime feeder key is present.

    Pitfall 1 / T-09-05: a stale or ``uniform``-mode topology cache silently
    corrupts the firm count, so fail loudly BEFORE the proxy.

    Args:
        cache_dir: Directory holding ``grid_cache_meta.json``.
        feeder_key: The runtime feeder element key.
        downstream: The parsed ``downstream_bus_map.json``.

    Raises:
        ValueError: If the sizing mode is not ``load_aware`` or the feeder key is
            absent from the downstream map.
    """
    meta = _load_json(cache_dir / "grid_cache_meta.json")
    mode = (
        meta.get("config", {})
        .get("lines", {})
        .get("sizing", {})
        .get("mode")
    )
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


def derive_congestion(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the firm baseline, the binding-state metrics, and the sweep.

    Reads the cache sidecars + stage-3 profiles (pandapower-free), validates the
    load-aware cache + runtime feeder key (Pitfall 1), builds the feeder-subtree
    proxy, sweeps to ``firm_ev_count``, recomputes loading at BOTH the firm count
    (the firm baseline) and the binding ``first_overload_ev_count`` state, computes
    the five CONG-02 metrics + reuses ``build_network_constraint_set`` AT THE BINDING
    STATE (so they are non-vacuous for any correct firm count), and writes the two
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
    _assert_load_aware_cache(cache_dir, feeder_key, downstream)

    elements, feeder_buses = feeder_elements(downstream, feeder_key)

    # D-A3: EV-adoption denominator = feeder buses ∩ load buses (the per-bus
    # building-count sidecar keys), in deterministic SORTED bus order.
    load_buses = {int(b) for b in node_building_count}
    bus_ids = sorted(set(feeder_buses) & load_buses)
    if not bus_ids:
        raise ValueError(
            f"ev_hosting_flex stage 4: feeder {feeder_key} has no downstream load "
            "buses in node_building_count.json. Remediation: verify the load-aware "
            "topology cache was built from the expected feeder."
        )

    indicator = downstream_indicator(elements, bus_ids, downstream)
    elem_kw = np.array([ratings[k] for k in elements], dtype=DTYPE)
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "ev_hosting_flex stage 4: a feeder element has a non-positive kW rating "
            f"(min={float(elem_kw.min())}) in line_transformer_ratings_kw.json. "
            "Remediation: re-run prepare_topology_cache.py at pf>0."
        )

    base = _read_profile(data_dir / "base_load_8760.parquet", bus_ids)
    ev_unit = _read_profile(data_dir / "ev_load_unit.parquet", bus_ids)

    building_count = np.array(
        [int(node_building_count[str(b)]) for b in bus_ids], dtype=DTYPE
    )

    def alloc_fn(total_ev: int) -> np.ndarray:
        return allocate_ev_per_bus(total_ev, building_count).astype(DTYPE)

    sweep = firm_ev_count(
        EV_SWEEP,
        base,
        ev_unit,
        alloc_fn,
        indicator,
        elem_kw,
        float(LINE_LOADING_LIMIT_PERCENT),
    )

    # GAP 1 / CONG-03 (09-03): fail loudly on a degenerate firm denominator. The
    # firm count must land strictly inside the sweep (0 < firm < max(EV_SWEEP)) so
    # Phase 10's hosting_expansion_percent = (flexible - firm)/firm never divides
    # by zero. firm==0 means the feeder is already overloaded at 0 EVs (the feeder
    # transformer was not load-aware sized); firm==max means the sweep is too
    # narrow to observe the crossing.
    firm = int(sweep["firm_ev_count"])
    if not 0 < firm < max(EV_SWEEP):
        raise ValueError(
            "ev_hosting_flex stage 4: degenerate firm_ev_count="
            f"{firm} for feeder {feeder_key} "
            f"(first_overload_ev_count={sweep['first_overload_ev_count']}, "
            f"EV_SWEEP max={max(EV_SWEEP)}); it must satisfy "
            "0 < firm_ev_count < max(EV_SWEEP) to be a usable Phase-10 "
            "denominator. Remediation: re-run prepare_topology_cache.py (the "
            "feeder transformer must be load-aware sized to its annual "
            "winter-peak downstream demand per plan 09-03) or widen EV_SWEEP in "
            "config.py."
        )

    # ── Firm BASELINE loading (kept for Phase-10/12; non-congested by design) ──
    # Recompute loading at the firm count — this is the firm baseline, NOT where the
    # metrics are taken. line_loading_firm.parquet keeps these semantics unchanged.
    per_bus_firm = alloc_fn(int(sweep["firm_ev_count"]))
    demand_firm = base + ev_unit * per_bus_firm[:, None]
    loading_firm, _elem_demand_firm = proxy_loading(indicator, demand_firm, elem_kw)

    # ── BINDING (first-overload) state — where the metrics + constraint set live ──
    # firm_ev_count is by construction the last ZERO-overload count, so
    # is_congested(loading_firm) is all-False and the four binding metrics + the CIM
    # set would be vacuous (the CR-01 defect). Compute them at first_overload_ev_count
    # (the binding state) instead. report_ct falls back to max(EV_SWEEP) only if the
    # sweep saw no overload — still a defined, non-firm state.
    report_ct = sweep["first_overload_ev_count"]
    if report_ct is None:
        report_ct = max(EV_SWEEP)
    report_ct = int(report_ct)

    per_bus_overload = alloc_fn(report_ct)
    demand_overload = base + ev_unit * per_bus_overload[:, None]
    loading_overload, elem_demand_overload = proxy_loading(
        indicator, demand_overload, elem_kw
    )

    # The five CONG-02 metrics at the BINDING state.
    metrics = congestion_metrics(
        loading_overload,
        elem_demand_overload,
        elem_kw,
        float(LINE_LOADING_LIMIT_PERCENT),
    )

    # Build the CIM-typed constraint SET from the BINDING-state overload element-hours
    # (D-11). Round the row floats to ROUND_DECIMALS so they agree with the rounded
    # binding parquet (WR-04). scenario_id="first_overload" so the CIM set is not
    # mislabelled as the firm baseline.
    congested = is_congested(loading_overload)
    rows: list[dict[str, object]] = []
    for ei in range(len(elements)):
        for h in np.nonzero(congested[ei])[0]:
            rows.append(
                {
                    "timestep": int(h),
                    "constraint_id": elements[ei],
                    "required_kw": round(
                        float(elem_demand_overload[ei, h] - elem_kw[ei]),
                        ROUND_DECIMALS,
                    ),
                    "limit_percent": float(LINE_LOADING_LIMIT_PERCENT),
                    "loading_percent": round(
                        float(loading_overload[ei, h]), ROUND_DECIMALS
                    ),
                    "overload_pctpt": round(
                        float(loading_overload[ei, h] - LINE_LOADING_LIMIT_PERCENT),
                        ROUND_DECIMALS,
                    ),
                }
            )
    constraint_set = build_network_constraint_set(
        pd.DataFrame(rows), scenario_id="first_overload"
    )

    # Round before write so float noise < 1e-6 never reaches the comparator (D-12).
    loading_firm_rounded = np.round(loading_firm, ROUND_DECIMALS).astype("float64")
    loading_overload_rounded = np.round(loading_overload, ROUND_DECIMALS).astype(
        "float64"
    )

    data_dir.mkdir(parents=True, exist_ok=True)
    columns = [f"h{h}" for h in range(loading_firm_rounded.shape[1])]
    # Firm baseline (unchanged semantics for Phase 10/12).
    loading_path = data_dir / "line_loading_firm.parquet"
    pd.DataFrame(loading_firm_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(loading_path)
    # Binding (first-overload) state — distinctly named so it is never conflated.
    binding_path = data_dir / "line_loading_first_overload.parquet"
    pd.DataFrame(loading_overload_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(binding_path)

    # Metrics carry the five CONG-02 keys PLUS explicit state labels (the five metric
    # NAMES are unchanged; the labels sit alongside them).
    metrics_payload = {
        **metrics,
        "state": "first_overload",
        "ev_count_at_metrics": report_ct,
    }
    metrics_path = _write_json(json_dir / "congestion_metrics.json", metrics_payload)
    firm_payload = {
        "firm_ev_count": int(sweep["firm_ev_count"]),
        "first_overload_ev_count": sweep["first_overload_ev_count"],
        "ev_sweep": list(sweep["ev_sweep"]),
        "threshold_convention": sweep["threshold_convention"],
        "feeder_key": feeder_key,
        "scope": "feeder_subtree",
        "n_feeder_bus": len(bus_ids),
        "n_elements": len(elements),
        "constraint_set_rows": int(len(constraint_set)),
        # Cross-reference recording WHERE the metrics were taken (no semantic change
        # to firm_ev_count).
        "metrics_state": "first_overload",
        "metrics_ev_count": report_ct,
    }
    firm_path = _write_json(json_dir / "firm_hosting.json", firm_payload)

    return {
        "artifact_paths": [loading_path, binding_path, metrics_path, firm_path],
        "summary": {
            **metrics,
            "state": "first_overload",
            "ev_count_at_metrics": report_ct,
            "firm_ev_count": int(sweep["firm_ev_count"]),
            "first_overload_ev_count": sweep["first_overload_ev_count"],
            "metrics_state": "first_overload",
            "metrics_ev_count": report_ct,
            "feeder_key": feeder_key,
            "scope": "feeder_subtree",
            "n_feeder_bus": len(bus_ids),
            "n_elements": len(elements),
            "constraint_set_rows": int(len(constraint_set)),
            # Byte-stability tripwire over BOTH rounded loading arrays.
            "loading_content_sha256": _content_sha256(loading_firm_rounded),
            "binding_loading_content_sha256": _content_sha256(
                loading_overload_rounded
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

    return script.write_report(
        "congestion_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": []},
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
        f"firm_ev_count={summary.get('firm_ev_count')}, "
        f"max_line_loading_percent={summary.get('max_line_loading_percent')}"
    )


if __name__ == "__main__":
    main()

"""Apply per-node flexibility contracts + the hosting-expansion headline.

Stage 5 of the workflow (FLEX-01/02/03/04). The flexibility sibling of the
Phase-9 stage-4 ``compute_congestion.py``: it reads ONLY the stage-2 topology
cache JSON sidecars, the stage-3 annual profile parquet, and the Phase-9
stage-4 ``firm_hosting.json`` (GUARD-02 — never the pickled net), runs the
proven Phase-10 closed-form cap kernel over the SELECTED feeder subtree across
all 8760h, sweeps to an integer ``flexible_ev_count`` with the feasible-AND-
tolerance gate, assembles the headline
``hosting_expansion_percent = (flexible - firm) / firm`` from the read (never
recomputed, D-11) firm count, and emits the named artifacts plus a governed
report:

* ``data/line_loading_flex.parquet`` — ``(n_elements, 8760)`` CAPPED loading% at
  the FLEXIBLE-LIMIT state (float64, rounded to ROUND_DECIMALS) — every feeder
  element <= the limit by construction of the cap (FLEX-01);
* ``data/contract_activations.parquet`` — the tidy trade-curve series, one row
  per swept EV count with ``ev_count, curtailed_energy_mwh,
  curtailed_energy_fraction, n_active_contracts, feasible,
  residual_overload_kw`` — the schema Phase-12's trade-curve figure consumes
  directly (FLEX-02/03);
* ``json/flexible_hosting.json`` — ``flexible_ev_count``, ``firm_ev_count`` (read
  from ``firm_hosting.json``, D-11), the headline ``hosting_expansion_percent``
  (FLEX-04), the curtailed fraction at the flexible limit, the swept grid, the
  trade-curve series, the threshold convention, the pinned feeder-subtree scope,
  and the active acceptability tolerance block;
* ``reports/flexibility_contracts_report.json`` — canonical platform report via
  ``script.write_report`` (GOV-precursor; never hand-written report JSON).

The headline denominator ``firm_ev_count`` is READ from the Phase-9 stage-4
``firm_hosting.json`` and never recomputed (D-11), with a ``firm_ev > 0`` guard
(mirrored from stage-4's degenerate-firm guard) before dividing — the flexible
leg cannot silently shift the denominator.

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
    flex_metrics,
    flexible_ev_count,
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
    TOLERANCE_ACTIVATION_HOURS_MAX,
    TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
    TOLERANCE_PRIMARY,
)

# ``is_congested`` is re-exported for downstream tooling parity with stage 4 and
# is part of the public surface of this stage even though the kernel owns the
# congested-set logic; reference it so linters keep the import.
_ = is_congested


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


def derive_flexibility(
    cache_dir: Path, data_dir: Path, json_dir: Path
) -> dict[str, object]:
    """Derive + persist the flexible-limit state, trade curve, and headline.

    Reads the cache sidecars + stage-3 profiles + the stage-4 ``firm_hosting.json``
    (pandapower-free), builds the feeder-subtree proxy, runs the proven flexible
    sweep, recomputes the CAPPED loading at the flexible-limit state, computes the
    FLEX-02 per-contract metrics + the FLEX-04 headline
    ``hosting_expansion_percent``, and writes the loading parquet, the trade-curve
    parquet, and the ``flexible_hosting.json`` artifact.

    Args:
        cache_dir: Directory holding the stage-2 cache sidecars.
        data_dir: Directory the loading + trade-curve parquet are written to.
        json_dir: Directory the flexible-hosting JSON is written to AND the
            stage-4 ``firm_hosting.json`` denominator is read from.

    Returns:
        A mapping with ``artifact_paths`` and a ``summary`` dict.

    Raises:
        ValueError: On a non-positive element rating, an empty feeder subtree, or
            a degenerate (``<= 0``) firm denominator.
    """
    ratings = _load_json(cache_dir / "line_transformer_ratings_kw.json")
    downstream = _load_json(cache_dir / "downstream_bus_map.json")
    feeder = _load_json(cache_dir / "feeder_selection.json")
    node_building_count = _load_json(cache_dir / "node_building_count.json")
    # The Phase-9 stage-4 output: the headline denominator (D-11, never recomputed).
    firm = _load_json(json_dir / "firm_hosting.json")

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
            f"ev_hosting_flex stage 5: feeder {feeder_key} has no downstream load "
            "buses in node_building_count.json. Remediation: verify the load-aware "
            "topology cache was built from the expected feeder."
        )

    indicator = downstream_indicator(elements, bus_ids, downstream)
    elem_kw = np.array([ratings[k] for k in elements], dtype=DTYPE)
    if not np.all(elem_kw > 0.0):
        raise ValueError(
            "ev_hosting_flex stage 5: a feeder element has a non-positive kW rating "
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

    # The headline denominator (D-11): read, never recomputed. Guard a degenerate
    # firm count BEFORE dividing (mirror stage 4's degenerate-firm guard — a
    # firm_ev_count <= 0 means the firm leg was wrong and the expansion percent
    # would divide by zero / go negative).
    firm_ev = int(firm["firm_ev_count"])
    if firm_ev <= 0:
        raise ValueError(
            "ev_hosting_flex stage 5: degenerate firm_ev_count="
            f"{firm_ev} read from firm_hosting.json for feeder {feeder_key}; the "
            "hosting_expansion_percent denominator must be > 0. Remediation: "
            "re-run stage 4 (compute_congestion.py / plan 09-03) so the feeder "
            "transformer is load-aware sized to a positive firm count."
        )

    # ── The flexible sweep (the proven Phase-10 kernel) ──────────────────────
    result = flexible_ev_count(
        EV_SWEEP,
        base,
        ev_unit,
        alloc_fn,
        indicator,
        elem_kw,
        float(LINE_LOADING_LIMIT_PERCENT),
        tolerance_primary=TOLERANCE_PRIMARY,
        curtailed_fraction_max=TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX,
        activation_hours_max=TOLERANCE_ACTIVATION_HOURS_MAX,
    )
    flexible_ev = int(result["flexible_ev_count"])
    trade_curve = result["trade_curve"]

    # The FLEX-04 headline: (flexible - firm) / firm, rounded to the reproducibility
    # decimals. firm_ev > 0 guaranteed by the guard above.
    hosting_expansion_percent = round((flexible_ev - firm_ev) / firm_ev, ROUND_DECIMALS)

    # ── Recompute the CAPPED loading at the FLEXIBLE-LIMIT state ──────────────
    # The flexible-limit state is the largest swept passing EV count; the cap
    # relieves every congested element to <= limit there (FLEX-01).
    per_bus = alloc_fn(flexible_ev)
    ev_demand = ev_unit * per_bus[:, None]
    demand = base + ev_demand
    cap = flex_curtailment(
        indicator, demand, ev_demand, elem_kw, float(LINE_LOADING_LIMIT_PERCENT)
    )
    loading_flex, _elem_demand_flex = proxy_loading(
        indicator, demand - cap["curtailed"], elem_kw
    )

    # Round before write so float noise < 1e-6 never reaches the comparator (D-12).
    loading_flex_rounded = np.round(loading_flex, ROUND_DECIMALS).astype("float64")

    data_dir.mkdir(parents=True, exist_ok=True)
    columns = [f"h{h}" for h in range(loading_flex_rounded.shape[1])]
    loading_path = data_dir / "line_loading_flex.parquet"
    pd.DataFrame(loading_flex_rounded, index=elements, columns=columns).astype(
        "float64"
    ).to_parquet(loading_path)

    # Per-contract metrics at the flexible-limit state (FLEX-02). The explicit
    # per-node annual EV demand (ev_demand.sum(axis=1)) is the D-10 reconciliation
    # `<=` upper bound.
    flex_metrics_at_limit = flex_metrics(
        cap["curtailed"],
        ev_demand,
        ev_demand.sum(axis=1),
        total_annual_ev_demand=float(ev_demand.sum()),
    )
    curtailed_energy_fraction_at_flexible = flex_metrics_at_limit[
        "curtailed_energy_fraction"
    ]

    # The tidy trade-curve series — one row per swept EV count (the schema
    # Phase-12's trade-curve figure consumes directly, FLEX-02/03).
    activations_path = data_dir / "contract_activations.parquet"
    pd.DataFrame(
        trade_curve,
        columns=[
            "ev_count",
            "curtailed_energy_mwh",
            "curtailed_energy_fraction",
            "n_active_contracts",
            "feasible",
            "residual_overload_kw",
        ],
    ).to_parquet(activations_path)

    flexible_payload = {
        "flexible_ev_count": flexible_ev,
        "firm_ev_count": firm_ev,
        "hosting_expansion_percent": hosting_expansion_percent,
        "curtailed_energy_fraction_at_flexible": (
            curtailed_energy_fraction_at_flexible
        ),
        "ev_sweep": list(result["ev_sweep"]),
        "threshold_convention": result["threshold_convention"],
        "feeder_key": feeder_key,
        "scope": "feeder_subtree",
        "n_feeder_bus": len(bus_ids),
        "n_elements": len(elements),
        "trade_curve": trade_curve,
        "tolerance": result["tolerance"],
    }
    flexible_path = _write_json(json_dir / "flexible_hosting.json", flexible_payload)

    return {
        "artifact_paths": [
            loading_path,
            activations_path,
            flexible_path,
        ],
        "summary": {
            "flexible_ev_count": flexible_ev,
            "firm_ev_count": firm_ev,
            "hosting_expansion_percent": hosting_expansion_percent,
            "curtailed_energy_fraction_at_flexible": (
                curtailed_energy_fraction_at_flexible
            ),
            "curtailed_energy_mwh_at_flexible": flex_metrics_at_limit[
                "curtailed_energy_mwh"
            ],
            "contract_activation_hours_at_flexible": flex_metrics_at_limit[
                "contract_activation_hours"
            ],
            "n_active_contracts_at_flexible": flex_metrics_at_limit[
                "n_active_contracts"
            ],
            "max_curtailment_kw_at_flexible": flex_metrics_at_limit[
                "max_curtailment_kw"
            ],
            "feasible_at_flexible": bool(cap["feasible"]),
            "residual_overload_kw_at_flexible": float(cap["residual_overload_kw"]),
            "feeder_key": feeder_key,
            "scope": "feeder_subtree",
            "n_feeder_bus": len(bus_ids),
            "n_elements": len(elements),
            "threshold_convention": result["threshold_convention"],
            "tolerance": result["tolerance"],
            # Byte-stability tripwire over the rounded flexible loading array.
            "flex_loading_content_sha256": _content_sha256(loading_flex_rounded),
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

    return script.write_report(
        "flexibility_contracts_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the flexibility-contracts stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    report = run_stage(cache_dir=args.cache_dir, data_dir=args.data_dir)
    summary = report.get("summary", {})
    print(
        "Applied flexibility contracts + report: "
        f"flexible_ev_count={summary.get('flexible_ev_count')}, "
        f"firm_ev_count={summary.get('firm_ev_count')}, "
        f"hosting_expansion_percent={summary.get('hosting_expansion_percent')}"
    )


if __name__ == "__main__":
    main()

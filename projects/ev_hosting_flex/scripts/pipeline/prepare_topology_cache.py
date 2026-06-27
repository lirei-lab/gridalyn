"""Prepare project-owned synthetic topology cache artifacts for ev_hosting_flex.

Stage 2 of the workflow. After building the synthetic radial twin + pandapower
net through the PUBLIC ``gridalyn.simulation`` facade (GUARD-01, TWIN-01), it
loads the cached net and derives the project-local topology contract via
``_topology.py``:

* asserts the feeder is radial with no embedded generation (TWIN-04) BEFORE any
  rating is derived — silent topology drift fails loudly here;
* derives per-line / per-transformer kW thermal ratings (TWIN-02);
* builds the transformer-hop-aware radial downstream-bus map (TWIN-03);
* deterministically selects the study feeder transformer (D-01/D-02);
* persists ratings + downstream map as deterministic cache artifacts and emits
  the canonical ``topology_cache_report`` via ``script.write_report`` (GOV-02 —
  never hand-written report JSON).

GUARD-02: no module-scope ``import pandapower`` / ``geopandas``. The facade
defers pandapower internally; the cached net is read via ``pickle`` as an
attribute-bag of pandas DataFrames.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

# Pitfall 2 (SEAL-01): cap the BLAS thread pool at module top, BEFORE any import
# that pulls numpy transitively (``_topology`` / the simulation facade) spins up
# its thread pool — defense-in-depth so cache derivation stays deterministic.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.simulation import prepare_synthetic_topology_cache  # noqa: E402
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    FEEDER_ID,
    GRID_CONFIG,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    PROJECT_ROOT,
    ROUND_DECIMALS,
    TOPOLOGY_CACHE_MANIFEST,
    TRANSFORMER_UTILIZATION_MARGIN,
)


def prepare_topology_cache(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    input_file: Path | None = None,
    force_rebuild: bool = False,
) -> Path:
    """Build or refresh the EV hosting-flex project topology cache.

    Builds the synthetic radial twin and pandapower net through the PUBLIC
    ``gridalyn.simulation`` facade only (GUARD-01) and writes the 3 cache files
    plus the footprint-validation report and lineage manifest.

    Args:
        cache_dir: Directory the cache artifacts are written to.
        input_file: Building-footprint GeoJSON. Defaults to the project-local
            copy under ``inputs/buildings.geojson`` (D-03), not the shared SDK
            dataset.
        force_rebuild: Rebuild even when a valid cache already exists.

    Returns:
        The path to the written ``topology_cache_manifest.json``.
    """

    source = input_file or (PROJECT_ROOT / "inputs" / "buildings.geojson")
    manifest_path = (
        TOPOLOGY_CACHE_MANIFEST
        if cache_dir == PROJECT_CACHE_DIR
        else cache_dir / "topology_cache_manifest.json"
    )
    return prepare_synthetic_topology_cache(
        input_file=source,
        cache_dir=cache_dir,
        config=GRID_CONFIG,
        manifest_path=manifest_path,
        force_rebuild=force_rebuild,
        notes=[
            "Project-owned runtime cache for the EV Hosting Flex workflow.",
            "Generated artifacts under projects/*/outputs are not committed.",
        ],
    )


def _write_json(path: Path, payload: object) -> Path:
    """Write ``payload`` to ``path`` as deterministic, sorted-key JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def derive_topology_artifacts(cache_dir: Path) -> dict[str, object]:
    """Derive + persist topology ratings, downstream map, and feeder selection.

    Loads the cached pandapower net (via ``pickle``; GUARD-02 — no module-scope
    pandapower), asserts radiality + no embedded generation (TWIN-04), derives
    the kW ratings (TWIN-02) and downstream map (TWIN-03), selects the study
    feeder (D-02), and writes deterministic cache artifacts.

    Args:
        cache_dir: Directory holding ``pp_net_cache.pkl`` and where derived
            artifacts are written.

    Returns:
        A summary dict (counts + selected feeder + selected-feeder load).
    """
    from projects.ev_hosting_flex.scripts._topology import (
        annual_peak_base_factor,
        assert_radial_no_generation,
        build_downstream_map,
        line_rating_kw,
        select_feeder,
        size_feeder_subtree_kw,
        trafo_rating_kw,
    )

    net_path = cache_dir / "pp_net_cache.pkl"
    with open(net_path, "rb") as handle:
        net = pickle.load(handle)

    # TWIN-04: fail loudly on silent topology drift BEFORE deriving anything.
    assert_radial_no_generation(net)

    line_kw = line_rating_kw(net, POWER_FACTOR)
    trafo_kw = trafo_rating_kw(net, POWER_FACTOR)
    downstream_map = build_downstream_map(net)
    feeder_idx = select_feeder(net, downstream_map, {"feeder_id": FEEDER_ID})

    # Ratings keyed line:{idx} / transformer:{idx} (matches constraints.py).
    ratings = {
        **{
            f"line:{int(idx)}": round(float(kw), ROUND_DECIMALS)
            for idx, kw in zip(net.line.index, line_kw)
        },
        **{
            f"transformer:{int(idx)}": round(float(kw), ROUND_DECIMALS)
            for idx, kw in zip(net.trafo.index, trafo_kw)
        },
    }

    # Downstream map: frozensets serialized to SORTED lists (D-07 determinism).
    downstream_serialized = {
        key: sorted(int(bus) for bus in members)
        for key, members in sorted(downstream_map.items())
    }

    load_by_bus = net.load.groupby("bus")["p_mw"].sum()

    # Phase-9 sidecars (GUARD-02): expose per-bus nameplate kW + building count
    # as JSON so stage 3 stays pandapower-free (never reads the pickled net).
    # Both serialized in SORTED bus order with deterministic _write_json.
    node_nameplate_kw = {
        str(int(bus)): round(float(p_mw) * 1000.0, ROUND_DECIMALS)
        for bus, p_mw in sorted(load_by_bus.items())
    }
    building_count_by_bus = net.load.groupby("bus").size()
    node_building_count = {
        str(int(bus)): int(n) for bus, n in sorted(building_count_by_bus.items())
    }

    feeder_key = f"transformer:{feeder_idx}"
    feeder_downstream = downstream_map[feeder_key]
    downstream_nameplate_kw = (
        float(load_by_bus.reindex(list(feeder_downstream)).fillna(0.0).sum()) * 1000.0
    )
    selected_feeder_load_kw = round(downstream_nameplate_kw, ROUND_DECIMALS)

    # GAP 1 / CONG-03 (09-03): load-aware re-size the selected feeder SUBTREE (the
    # head transformer + every interior line whose downstream set is contained in
    # the feeder's downstream buses) to its annual winter-peak downstream base
    # demand at the 0.8 utilization margin. The "size to peak" locked decision must
    # cover the interior lines too: the binding element at 0 EVs is an interior
    # line, not the head transformer (the SDK load_aware line sizing has no concept
    # of the project's winter-peak envelope — the same mismatch the transformer
    # resize addresses). Only the feeder subtree is touched; every line:* /
    # transformer:* OUTSIDE the subtree keeps its SDK rating byte-unchanged.
    peak_factor = annual_peak_base_factor()
    nameplate_kw_by_bus = {
        int(bus): float(p_mw) * 1000.0 for bus, p_mw in load_by_bus.items()
    }
    feeder_set = set(int(b) for b in feeder_downstream)
    subtree_keys: dict[str, frozenset[int]] = {
        feeder_key: frozenset(feeder_set)
    }
    for key, members in downstream_map.items():
        if key.startswith("line:") and set(int(b) for b in members) <= feeder_set:
            subtree_keys[key] = frozenset(int(b) for b in members)

    resized_by_key = size_feeder_subtree_kw(
        subtree_keys,
        nameplate_kw_by_bus,
        peak_factor=peak_factor,
        utilization_margin=TRANSFORMER_UTILIZATION_MARGIN,
    )
    pre_resize_kw = {key: float(ratings[key]) for key in resized_by_key}
    for key, kw in resized_by_key.items():
        ratings[key] = round(float(kw), ROUND_DECIMALS)

    resized_kw = resized_by_key[feeder_key]
    feeder_transformer_sizing = {
        "mode": "load_aware_annual_peak",
        "downstream_nameplate_kw": round(downstream_nameplate_kw, ROUND_DECIMALS),
        "peak_factor": round(peak_factor, ROUND_DECIMALS),
        "utilization_margin": TRANSFORMER_UTILIZATION_MARGIN,
        "pre_resize_kw": round(float(pre_resize_kw[feeder_key]), ROUND_DECIMALS),
        "post_resize_kw": round(float(resized_kw), ROUND_DECIMALS),
        "n_subtree_elements_resized": len(resized_by_key),
    }

    ratings_path = _write_json(cache_dir / "line_transformer_ratings_kw.json", ratings)
    downstream_path = _write_json(
        cache_dir / "downstream_bus_map.json", downstream_serialized
    )
    feeder_selection = {
        "feeder_transformer_idx": feeder_idx,
        "selected_feeder_load_kw": selected_feeder_load_kw,
        "power_factor": POWER_FACTOR,
        "feeder_id_override": FEEDER_ID,
        "feeder_transformer_sizing": feeder_transformer_sizing,
    }
    feeder_path = _write_json(cache_dir / "feeder_selection.json", feeder_selection)
    nameplate_path = _write_json(
        cache_dir / "node_nameplate_kw.json", node_nameplate_kw
    )
    building_count_path = _write_json(
        cache_dir / "node_building_count.json", node_building_count
    )

    n_line_downstream = sum(1 for key in downstream_map if key.startswith("line:"))
    return {
        "artifact_paths": [
            ratings_path,
            downstream_path,
            feeder_path,
            nameplate_path,
            building_count_path,
        ],
        "summary": {
            "n_buses": int(len(net.bus)),
            "n_lines": int(len(net.line)),
            "n_transformers": int(len(net.trafo)),
            "feeder_transformer_idx": feeder_idx,
            "n_downstream_lines": int(n_line_downstream),
            "selected_feeder_load_kw": selected_feeder_load_kw,
            "n_load_buses": int(len(node_nameplate_kw)),
            "feeder_transformer_post_resize_kw": round(resized_kw, ROUND_DECIMALS),
            "annual_peak_base_factor": round(peak_factor, ROUND_DECIMALS),
        },
    }


def run_stage(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    input_file: Path | None = None,
    force_rebuild: bool = False,
) -> dict[str, object]:
    """Run the full topology-cache stage: facade build + derive + report.

    Args:
        cache_dir: Cache directory (defaults to the project cache dir).
        input_file: Building-footprint GeoJSON override (D-03).
        force_rebuild: Rebuild the facade cache even if present.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    prepare_topology_cache(
        cache_dir=cache_dir, input_file=input_file, force_rebuild=force_rebuild
    )

    script = project_script()
    effective_cache_dir = (
        script.cache_dir if cache_dir == PROJECT_CACHE_DIR else cache_dir
    )
    derived = derive_topology_artifacts(effective_cache_dir)

    artifact_paths = derived["artifact_paths"]  # type: ignore[assignment]
    summary = derived["summary"]  # type: ignore[assignment]
    return script.write_report(
        "topology_cache_report",
        artifacts=[script.file_reference(p) for p in artifact_paths],
        summary=summary,
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the topology-cache stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    report = run_stage(
        cache_dir=args.cache_dir,
        input_file=args.input_file,
        force_rebuild=args.force_rebuild,
    )
    summary = report.get("summary", {})
    print(
        "Prepared topology cache + report: "
        f"feeder_transformer_idx={summary.get('feeder_transformer_idx')}, "
        f"n_buses={summary.get('n_buses')}"
    )


if __name__ == "__main__":
    main()

"""Export the flagship's real network as a canonical gridalyn.twin NetworkModel.

Terminal, additive stage (Phase 31 / Milestone 14 / R26): reads the topology
cache's ``pp_net_cache.pkl`` / ``pg_graph_cache.pkl`` -- already produced by
``prepare_topology_cache`` -- through ``SyntheticPandapowerAdapter``'s
historical cache-adapt path (``footprints_path`` unset, so no rebuild) and
writes the 5 canonical Parquet tables plus a manifest and adapter validation
report into ``outputs/data/twin_network_model/``. This is the first path by
which ``gridalyn.twin``'s observation and semantic layers can load the
flagship's real 4,320-bus network, via
``NetworkModelRepository.from_parquet(...)``.

Read-only with respect to every existing cache/report artifact: this stage
only reads ``pp_net_cache.pkl`` / ``pg_graph_cache.pkl`` and writes new files
under its own ``twin_network_model/`` subdirectory. It does not rebuild the
topology cache, does not touch load-aware line sizing (already baked into the
cached net by the upstream facade), and nothing downstream of it depends on
its output -- so it cannot move any of the 81 regression-baseline pins.
"""

from __future__ import annotations

import argparse
from typing import Any

from gridalyn.projects.scripting import project_script
from gridalyn.twin.adapters.network import SyntheticPandapowerAdapter
from projects.ev_hosting_flex.scripts.config import GRID_CONFIG_PATH, ROOT


def run_stage() -> dict[str, Any]:
    """Export the twin-native NetworkModel from the flagship's cached net.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    script = project_script()
    out_dir = script.data_dir / "twin_network_model"

    adapter = SyntheticPandapowerAdapter(
        cache_dir=script.cache_dir, config_path=GRID_CONFIG_PATH
    )
    result = adapter.export(out_dir=out_dir, root=ROOT)

    artifacts = [script.file_reference(p) for p in result.artifact_paths.values()]
    artifacts.append(script.file_reference(result.metadata_path))
    artifacts.append(script.file_reference(result.validation_report_path))

    return script.write_report(
        "twin_network_model_report",
        artifacts=artifacts,
        summary={
            "model_id": result.identity.id,
            "model_profile": result.identity.profile,
            "counts": result.counts,
            "out_dir": str(out_dir),
        },
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the twin-network-model export stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Exported twin NetworkModel: "
        f"model={summary.get('model_id')}, counts={summary.get('counts')}"
    )


if __name__ == "__main__":
    main()

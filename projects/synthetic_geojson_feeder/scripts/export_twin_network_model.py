"""Export the synthetic feeder as a canonical gridalyn.twin NetworkModel.

Terminal, additive stage: ``build_synthetic_feeder`` already builds this
project's network through ``build_synthetic_network_from_geojson`` --
internally the same twin-layer ``build_power_grid_and_network`` that
``SyntheticPandapowerAdapter`` wraps when ``footprints_path`` is set -- but
writes only plain CSV element tables, never the 5 canonical Parquet tables.
This stage rebuilds the identical network (same persisted
``building_footprints.geojson`` + same config, both deterministic) through
the adapter itself and exports it, so ``gridalyn.twin``'s observation and
semantic layers can load this project's network for the first time via
``NetworkModelRepository.from_parquet(...)``.

Read-only with respect to every existing artifact: this stage only reads the
already-generated ``building_footprints.geojson`` and writes new files under
its own ``twin_network_model/`` subdirectory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gridalyn.projects.scripting import project_script
from gridalyn.twin.adapters.network import SyntheticPandapowerAdapter


def run_stage() -> dict[str, Any]:
    """Export the twin-native NetworkModel from the generated footprints.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    script = project_script()
    out_dir = script.data_dir / "twin_network_model"

    adapter = SyntheticPandapowerAdapter(
        cache_dir=Path("unused-footprints-path-set"),
        config_path=script.root / "inputs" / "synthetic_network_config.json",
        footprints_path=script.data_dir / "building_footprints.geojson",
    )
    result = adapter.export(out_dir=out_dir, root=script.root)

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
    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Exported twin NetworkModel: "
        f"model={summary.get('model_id')}, counts={summary.get('counts')}"
    )


if __name__ == "__main__":
    main()

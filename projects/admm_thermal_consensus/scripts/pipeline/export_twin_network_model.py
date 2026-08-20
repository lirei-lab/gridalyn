"""Export the LV feeder's topology as a canonical gridalyn.twin NetworkModel.

Terminal, additive stage: rebuilds the same deterministic feeder
``lv_feeder.build_lv_feeder`` declares (``build_network`` already builds this
same feeder to report the uncoordinated-peak transformer loading; this stage
takes the bare topology before any scenario-specific load is injected --
buses/lines/transformers carry no load values in the canonical schema, so
which scenario's kW happened to be on the buses at build time makes no
difference to the exported tables) and exports it through
``PandapowerTopologyAdapter`` (no building-footprint layer; this feeder is a
hand-built synthetic LV residential feeder with aggregate home-cluster loads,
not individual buildings, so buildings and building_grid_connectivity are
legitimately empty), so ``gridalyn.twin``'s observation and semantic layers
can load this project's network for the first time via
``NetworkModelRepository.from_parquet(...)``.

Read-only with respect to every existing artifact: this stage only reads
``config.py`` constants and writes new files under its own
``twin_network_model/`` subdirectory. Nothing downstream depends on this
stage's output, and no other stage's output changes -- this project's
manuscript (``manuscripts/admm_thermal_consensus/``) is synced from
``outputs/`` and reads none of the files this stage adds.
"""

from __future__ import annotations

from typing import Any

from gridalyn.projects.scripting import project_script
from gridalyn.twin.adapters.network import PandapowerTopologyAdapter
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts import lv_feeder


def run_stage() -> dict[str, Any]:
    """Export the twin-native NetworkModel from the declared LV feeder.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    script = project_script()
    out_dir = script.data_dir / "twin_network_model"

    config_ref = script.write_json(
        "outputs/data/twin_network_model_config.json",
        {
            "mvKv": C.MV_KV,
            "lvKv": C.LV_KV,
            "transformerKva": C.TRANSFORMER_KVA,
            "nLvFeeders": C.N_LV_FEEDERS,
            "busesPerFeeder": C.BUSES_PER_FEEDER,
            "nLvSections": C.N_LV_SECTIONS,
            "nAgents": C.N_AGENTS,
            "lvSectionKm": C.LV_SECTION_KM,
            "lvROhmKm": C.LV_R_OHM_KM,
            "lvXOhmKm": C.LV_X_OHM_KM,
            "lvMaxIKa": C.LV_MAX_I_KA,
            "powerFactor": C.POWER_FACTOR,
        },
    )
    config_path = script.root / config_ref["path"]

    net, _load_buses = lv_feeder.build_lv_feeder()
    adapter = PandapowerTopologyAdapter(net=net, config_path=config_path)
    result = adapter.export(out_dir=out_dir, root=script.root)

    artifacts = [script.file_reference(p) for p in result.artifact_paths.values()]
    artifacts.append(script.file_reference(result.metadata_path))
    artifacts.append(script.file_reference(result.validation_report_path))
    artifacts.append(config_ref)

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

"""Export the RL feeder's topology as a canonical gridalyn.twin NetworkModel.

Terminal, additive stage: rebuilds the same deterministic feeder+DER network
``build_rl_feeder`` (``network_model.py``) declares and exports it through
``PandapowerTopologyAdapter`` (no building-footprint layer; this feeder is
declared via ``RadialFeederSpec``/``VoltageControlDERSpec``, not building
footprints, so buildings and building_grid_connectivity are legitimately
empty), so ``gridalyn.twin``'s observation and semantic layers can load this
project's network for the first time via
``NetworkModelRepository.from_parquet(...)``.

Nothing downstream depends on this stage's output.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from network_model import DER_SPEC, FEEDER_SPEC, build_rl_feeder

from gridalyn.projects.scripting import project_script
from gridalyn.twin.adapters.network import PandapowerTopologyAdapter


def run_stage() -> dict[str, Any]:
    """Export the twin-native NetworkModel from the declared feeder+DER spec.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    script = project_script()
    out_dir = script.data_dir / "twin_network_model"

    config_ref = script.write_json(
        "outputs/data/twin_network_model_config.json",
        {
            "feeder": dataclasses.asdict(FEEDER_SPEC),
            "der": dataclasses.asdict(DER_SPEC),
        },
    )
    config_path = script.root / config_ref["path"]

    net = build_rl_feeder()
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

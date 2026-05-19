"""Orchestrate reproducible digital-twin artifact generation."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _step(name: str, command: list[str], *, heavy: bool = False, optional: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "heavy": heavy,
        "optional": optional,
    }


def build_digital_twin_steps(
    *,
    skip_heavy: bool = False,
    include_network_impact: bool = False,
) -> list[dict[str, Any]]:
    """Return the ordered digital-twin build plan."""
    steps = [
        _step("export_base", ["-m", "gridalyn.interfaces.cli.digital_twin", "base"]),
        _step("generate_building_models", ["-m", "gridalyn.interfaces.cli.digital_twin", "building-models"]),
        _step("generate_scenarios", ["-m", "gridalyn.interfaces.cli.digital_twin", "scenarios"]),
        _step("generate_ev_timeseries", ["-m", "gridalyn.interfaces.cli.digital_twin", "timeseries"]),
        _step("run_powerflow", ["-m", "gridalyn.interfaces.cli.digital_twin", "powerflow"], heavy=True),
        _step("report_transformer_overloads", ["-m", "gridalyn.interfaces.cli.digital_twin", "overload-report"]),
        _step("generate_asset_registry", ["-m", "gridalyn.interfaces.cli.digital_twin", "asset-registry"]),
        _step("generate_scenario_models", ["-m", "gridalyn.interfaces.cli.digital_twin", "scenario-models"]),
        _step("generate_flexibility_providers", ["-m", "gridalyn.interfaces.cli.flexibility", "providers"]),
        _step("generate_semantic_graph", ["-m", "gridalyn.interfaces.cli.semantic", "build"]),
        _step("validate_semantics", ["-m", "gridalyn.interfaces.cli.semantic", "validate"]),
        _step("generate_canonical_reports", ["-m", "gridalyn.reporting.digital_twin"]),
    ]

    if include_network_impact:
        steps.extend(
            [
                _step("generate_network_impact_surrogate", ["-m", "gridalyn.interfaces.cli.flexibility", "surrogate"]),
                _step(
                    "generate_locational_flexibility_clearing",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "locational-clearing"],
                ),
                _step(
                    "generate_locational_clearing_verification_report",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "verify-clearing"],
                    heavy=True,
                    optional=True,
                ),
                _step(
                    "generate_network_impact_perturbation_samples",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "perturbation-samples"],
                    heavy=True,
                    optional=True,
                ),
                _step(
                    "train_network_impact_physics_surrogate",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "train-physics-surrogate"],
                    optional=True,
                ),
                _step(
                    "generate_network_impact_verification_report",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "verify-network-impact"],
                    heavy=True,
                    optional=True,
                ),
                _step(
                    "generate_network_impact_physics_verification_report",
                    [
                        "-m",
                        "gridalyn.interfaces.cli.flexibility",
                        "verify-network-impact",
                        "--predictions-path",
                        "digital_twin/flexibility/network_impact_physics_predictions.parquet",
                        "--out-path",
                        "digital_twin/flexibility/network_impact_physics_verification_report.json",
                    ],
                    heavy=True,
                    optional=True,
                ),
                _step(
                    "generate_network_impact_dashboard_catalog",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "network-impact-catalog"],
                ),
                _step(
                    "generate_flexibility_clearing_scorecard",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "scorecard"],
                    optional=True,
                ),
            ]
        )

    steps.append(_step("generate_dashboard_catalog", ["-m", "gridalyn.interfaces.cli.dashboard", "catalog"]))
    if skip_heavy:
        steps = [step for step in steps if not step["heavy"]]
    return steps


def build_manifest(
    steps: list[dict[str, Any]],
    *,
    root: Path,
    dry_run: bool,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "digital_twin_build_manifest",
        "schema_version": "1.0",
        "dry_run": dry_run,
        "step_count": len(steps),
        "steps": steps,
        "results": results,
        "artifacts": {
            "dashboard_catalog": "digital_twin/dashboard/catalog.json",
            "building_model_manifest": "digital_twin/models/building_model_manifest.json",
            "scenario_model_manifest": "digital_twin/models/scenarios/scenario_model_manifest.json",
            "semantic_manifest": "digital_twin/semantic/graph_manifest.json",
            "canonical_report_manifest": "digital_twin/reports/canonical/digital_twin_report_manifest.json",
        },
        "root": ".",
    }


def write_build_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path


def run_digital_twin_build(
    *,
    root: Path,
    skip_heavy: bool = False,
    include_network_impact: bool = False,
    dry_run: bool = False,
    continue_on_error: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Execute or describe the digital-twin build plan."""
    steps = build_digital_twin_steps(
        skip_heavy=skip_heavy,
        include_network_impact=include_network_impact,
    )
    results: list[dict[str, Any]] = []
    for step in steps:
        display_command = ["python", *step["command"]]
        command = [sys.executable, *step["command"]]
        if dry_run:
            results.append({"name": step["name"], "status": "planned", "command": display_command})
            continue

        completed = subprocess.run(command, cwd=root, check=False)
        result = {
            "name": step["name"],
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "command": display_command,
        }
        results.append(result)
        if completed.returncode != 0 and not (continue_on_error or step["optional"]):
            manifest = build_manifest(steps, root=root, dry_run=dry_run, results=results)
            write_build_manifest(
                manifest_path or root / "digital_twin" / "reports" / "digital_twin_build_manifest.json",
                manifest,
            )
            raise RuntimeError(f"Digital twin build step failed: {step['name']} ({completed.returncode})")

    manifest = build_manifest(steps, root=root, dry_run=dry_run, results=results)
    write_build_manifest(
        manifest_path or root / "digital_twin" / "reports" / "digital_twin_build_manifest.json",
        manifest,
    )
    return manifest

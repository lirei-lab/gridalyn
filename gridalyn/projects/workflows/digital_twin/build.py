"""Orchestrate reproducible digital-twin artifact generation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.foundation import ArtifactLayout


def _step(name: str, command: list[str], *, heavy: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "heavy": heavy,
    }


def build_digital_twin_steps(
    *,
    skip_heavy: bool = False,
    include_network_impact: bool = False,
    capabilities: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the ordered digital-twin build plan.

    Phase 21 re-layering (2026-08-17): the build is model-first by declared
    capability. ``None`` preserves the pre-Phase-21 build (the ``ev-hosting``
    and ``flexibility`` layers are assumed, so existing callers stay
    identical); an explicit set builds the model-first core plus the declared
    capability layers — e.g. ``set()`` for a pure generic build
    (base + building models + semantic core + reports) or
    ``{"ev-hosting", "flexibility"}`` for the full legacy build.
    """
    # ``None`` preserves the pre-Phase-21 build for existing callers.
    capabilities = (
        {"ev-hosting", "flexibility"} if capabilities is None else set(capabilities)
    )
    steps = [
        _step("export_base", ["-m", "gridalyn.interfaces.cli.digital_twin", "base"]),
        _step(
            "generate_building_models",
            ["-m", "gridalyn.interfaces.cli.digital_twin", "building-models"],
        ),
    ]

    if "ev-hosting" in capabilities:
        steps.extend(
            [
                _step(
                    "generate_scenarios",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "scenarios"],
                ),
                _step(
                    "generate_ev_timeseries",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "timeseries"],
                ),
                _step(
                    "run_powerflow",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "powerflow"],
                    heavy=True,
                ),
                _step(
                    "report_transformer_overloads",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "overload-report"],
                ),
                _step(
                    "generate_asset_registry",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "asset-registry"],
                ),
                _step(
                    "generate_scenario_models",
                    ["-m", "gridalyn.interfaces.cli.digital_twin", "scenario-models"],
                ),
            ]
        )

    if "flexibility" in capabilities:
        steps.append(
            _step(
                "generate_flexibility_providers",
                ["-m", "gridalyn.interfaces.cli.flexibility", "providers"],
            )
        )

    steps.extend(
        [
            _step(
                "generate_semantic_graph",
                ["-m", "gridalyn.interfaces.cli.semantic", "build"],
            ),
            _step(
                "validate_semantics",
                ["-m", "gridalyn.interfaces.cli.semantic", "validate"],
            ),
            _step(
                "generate_canonical_reports",
                ["-m", "gridalyn.interfaces.reporting.digital_twin"],
            ),
        ]
    )

    if include_network_impact and "flexibility" in capabilities:
        steps.extend(
            [
                _step(
                    "generate_network_impact_surrogate",
                    ["-m", "gridalyn.interfaces.cli.flexibility", "surrogate"],
                ),
                _step(
                    "generate_locational_flexibility_clearing",
                    [
                        "-m",
                        "gridalyn.interfaces.cli.flexibility",
                        "locational-clearing",
                    ],
                ),
                # Five steps were RETIRED here on 2026-08-06 --
                # generate_locational_clearing_verification_report,
                # generate_network_impact_perturbation_samples,
                # generate_network_impact_verification_report,
                # generate_network_impact_physics_verification_report and
                # generate_flexibility_clearing_scorecard. A sixth,
                # train_network_impact_physics_surrogate, followed on the same
                # day: its labels parquet had no writer once
                # perturbation-samples was gone. Each invoked a
                # command that reads
                # flexibility/market_dispatch_timeseries.parquet with no
                # argument, and no command in this repository writes that file
                # -- it came from a study that was consolidated away. They
                # were marked optional=True, so all five failed on every run
                # while the build still exited 0 -- a green exit on an
                # incomplete build. See
                # docs/development/instruction-verification.md.
                # The ``optional`` failure-swallowing mechanism itself was
                # removed on 2026-08-06; a failing step now always fails the
                # build.
                _step(
                    "generate_network_impact_dashboard_catalog",
                    [
                        "-m",
                        "gridalyn.interfaces.cli.flexibility",
                        "network-impact-catalog",
                    ],
                ),
            ]
        )

    steps.append(
        _step(
            "generate_dashboard_catalog",
            ["-m", "gridalyn.interfaces.cli.dashboard", "catalog"],
        )
    )
    if skip_heavy:
        steps = [step for step in steps if not step["heavy"]]
    return steps


def build_manifest(
    steps: list[dict[str, Any]],
    *,
    root: Path,
    dry_run: bool,
    results: list[dict[str, Any]],
    instance: str = "default",
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "digital_twin_build_manifest",
        "schema_version": "1.0",
        "dry_run": dry_run,
        "step_count": len(steps),
        "steps": steps,
        "results": results,
        "instance": instance,
        "artifacts": {
            "dashboard_catalog": (
                f"instances/{instance}/digital_twin/dashboard/catalog.json"
            ),
            "building_model_manifest": (
                f"instances/{instance}/digital_twin/models/"
                "building_model_manifest.json"
            ),
            "scenario_model_manifest": (
                f"instances/{instance}/digital_twin/models/scenarios/"
                "scenario_model_manifest.json"
            ),
            "semantic_manifest": (
                f"instances/{instance}/digital_twin/semantic/graph_manifest.json"
            ),
            "canonical_report_manifest": (
                f"instances/{instance}/digital_twin/reports/canonical/"
                "digital_twin_report_manifest.json"
            ),
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
    instance: str = "default",
    capabilities: set[str] | None = None,
) -> dict[str, Any]:
    """Execute or describe the digital-twin build plan.

    ``instance`` selects the named twin under ``<root>/instances/<instance>``
    to build; ``capabilities`` declares which capability layers to include
    (``None`` keeps the legacy ``ev-hosting`` + ``flexibility`` build, an
    explicit set builds the model-first core plus exactly those layers). Both
    are threaded into the layer scripts via ``GRIDALYN_INSTANCE`` and
    ``GRIDALYN_WORKSPACE_ROOT`` so every step materializes on the selected
    instance.
    """
    steps = build_digital_twin_steps(
        skip_heavy=skip_heavy,
        include_network_impact=include_network_impact,
        capabilities=capabilities,
    )
    layout = ArtifactLayout(root, instance=instance)
    results: list[dict[str, Any]] = []
    for step in steps:
        display_command = ["python", *step["command"]]
        command = [sys.executable, *step["command"]]
        env = os.environ.copy()
        env["GRIDALYN_INSTANCE"] = instance
        env["GRIDALYN_WORKSPACE_ROOT"] = str(root)
        if dry_run:
            results.append(
                {"name": step["name"], "status": "planned", "command": display_command}
            )
            continue

        completed = subprocess.run(command, cwd=root, env=env, check=False)
        result = {
            "name": step["name"],
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "command": display_command,
        }
        results.append(result)
        if completed.returncode != 0 and not continue_on_error:
            manifest = build_manifest(
                steps,
                root=root,
                dry_run=dry_run,
                results=results,
                instance=instance,
            )
            write_build_manifest(
                manifest_path or layout.reports / "digital_twin_build_manifest.json",
                manifest,
            )
            raise RuntimeError(
                f"Digital twin build step failed: {step['name']} ({completed.returncode})"
            )

    manifest = build_manifest(
        steps, root=root, dry_run=dry_run, results=results, instance=instance
    )
    write_build_manifest(
        manifest_path or layout.reports / "digital_twin_build_manifest.json",
        manifest,
    )
    return manifest

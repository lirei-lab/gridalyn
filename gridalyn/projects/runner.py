from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.governance import build_study_run
from gridalyn.projects.models import StudyProject, WorkflowStage


def plan_stages(project: StudyProject) -> list[WorkflowStage]:
    stages = {stage.id: stage for stage in project.workflow.stages}
    indegree = {stage_id: 0 for stage_id in stages}
    children: dict[str, list[str]] = defaultdict(list)
    for stage in project.workflow.stages:
        for dependency in stage.needs:
            children[dependency].append(stage.id)
            indegree[stage.id] += 1

    ready = deque(stage_id for stage_id, count in indegree.items() if count == 0)
    ordered: list[WorkflowStage] = []
    while ready:
        stage_id = ready.popleft()
        ordered.append(stages[stage_id])
        for child in children[stage_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered) != len(stages):
        raise ValueError("workflow contains a dependency cycle")
    return ordered


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def default_manifest_path(project: StudyProject) -> Path:
    return project.root / "outputs" / "manifests" / "project_run_manifest.json"


def select_stages(project: StudyProject, requested: list[str]) -> list[WorkflowStage]:
    """Return requested stages plus their transitive dependencies, in run order."""
    stages = {stage.id: stage for stage in project.workflow.stages}
    unknown = sorted(set(requested) - set(stages))
    if unknown:
        available = ", ".join(sorted(stages))
        raise ValueError(
            f"unknown workflow stage(s): {', '.join(unknown)} (available: {available})"
        )
    selected: set[str] = set()
    pending = list(requested)
    while pending:
        stage_id = pending.pop()
        if stage_id in selected:
            continue
        selected.add(stage_id)
        pending.extend(stages[stage_id].needs)
    return [stage for stage in plan_stages(project) if stage.id in selected]


def _echo(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run_project(
    project: StudyProject,
    dry_run: bool = False,
    manifest_path: Path | str | None = None,
    echo: bool = False,
    stages: list[str] | None = None,
) -> list[str]:
    started_at = _utc_now()
    git_commit = _git_commit(project.base_dir)
    manifest = {
        "project": {
            "name": project.name,
            "version": project.version,
            "path": str(project.path),
        },
        "workflow": {
            "name": project.workflow.name,
            "path": str(project.workflow.path),
        },
        "dry_run": dry_run,
        "git_commit": git_commit,
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "stages": [],
    }
    output_path = Path(manifest_path) if manifest_path else default_manifest_path(project)
    planned = select_stages(project, stages) if stages else plan_stages(project)
    if stages:
        manifest["stage_filter"] = sorted({stage.id for stage in planned})
    total = len(planned)
    executed: list[str] = []
    try:
        for index, stage in enumerate(planned, start=1):
            executed.append(stage.id)
            record = {
                "id": stage.id,
                "command": stage.command,
                "status": "planned" if dry_run else "running",
                "started_at": None if dry_run else _utc_now(),
                "ended_at": None,
                "exit_code": None,
            }
            manifest["stages"].append(record)
            if dry_run:
                if echo:
                    _echo(f"[{index}/{total}] {stage.id} (planned): {stage.command}")
                continue

            if echo:
                _echo(f"[{index}/{total}] {stage.id}: {stage.command}")
            stage_started = time.monotonic()
            result = subprocess.run(
                stage.command,
                cwd=project.base_dir,
                shell=True,
                check=False,
            )
            elapsed = time.monotonic() - stage_started
            record["ended_at"] = _utc_now()
            record["exit_code"] = result.returncode
            if result.returncode != 0:
                record["status"] = "failed"
                manifest["status"] = "failed"
                if echo:
                    _echo(f"[{index}/{total}] {stage.id} FAILED (exit {result.returncode}) after {elapsed:.1f}s")
                    _echo(f"Inspect the run manifest: {output_path}")
                    _echo(f"Re-run just this stage with: gridalyn project run {project.root} --stage {stage.id}")
                raise subprocess.CalledProcessError(result.returncode, stage.command)
            record["status"] = "completed"
            if echo:
                _echo(f"[{index}/{total}] {stage.id} completed in {elapsed:.1f}s")
    except Exception:
        if manifest["status"] == "running":
            manifest["status"] = "failed"
        raise
    finally:
        if manifest["status"] == "running":
            manifest["status"] = "planned" if dry_run else "completed"
        manifest["ended_at"] = _utc_now()
        manifest["study_run"] = build_study_run(
            project_id=project.name,
            project_version=project.version,
            workflow_id=project.workflow.name,
            dry_run=dry_run,
            status=str(manifest["status"]),
            started_at=started_at,
            ended_at=str(manifest["ended_at"]) if manifest["ended_at"] else None,
            git_commit=git_commit,
            stages=list(manifest["stages"]),
            lineage={
                "project_path": str(project.path),
                "project_root": str(project.root),
                "workflow_path": str(project.workflow.path),
            },
        ).to_dict()
        _write_manifest(output_path, manifest)
        if echo and manifest["status"] != "failed":
            label = "planned" if dry_run else "completed"
            _echo(f"{label} {len(executed)}/{total} stage(s); manifest: {output_path}")
    return executed

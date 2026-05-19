from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from gridalyn.foundation.platform.workspace import find_workspace_root
from gridalyn.projects.models import StudyProject, WorkflowSpec, WorkflowStage


def read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_workflow(path: Path | str) -> WorkflowSpec:
    workflow_path = Path(path).resolve()
    raw = read_yaml(workflow_path)
    stages = []
    for item in raw["spec"]["stages"]:
        stages.append(
            WorkflowStage(
                id=item["id"],
                command=item["command"],
                needs=tuple(item.get("needs", [])),
                inputs=tuple(item.get("inputs", [])),
                outputs=tuple(item.get("outputs", [])),
            )
        )
    return WorkflowSpec(
        name=raw["metadata"]["name"],
        path=workflow_path,
        stages=tuple(stages),
    )


def find_repo_root(start: Path) -> Path:
    return find_workspace_root(start)


def project_base_dir(project_path: Path, raw: dict[str, Any]) -> tuple[Path, str]:
    path_base = raw["spec"].get("pathBase", "project")
    if path_base == "repo":
        return find_repo_root(project_path.parent), path_base
    if path_base == "project":
        return project_path.parent, path_base
    raise ValueError(f"unsupported pathBase: {path_base}")


def load_project(path: Path | str) -> StudyProject:
    project_path = Path(path).resolve()
    raw = read_yaml(project_path)
    root = project_path.parent
    base_dir, path_base = project_base_dir(project_path, raw)
    workflow_path = (base_dir / raw["spec"]["workflow"]["file"]).resolve()
    workflow = load_workflow(workflow_path)
    return StudyProject(
        name=raw["metadata"]["name"],
        version=raw["metadata"]["version"],
        path=project_path,
        root=root,
        base_dir=base_dir,
        path_base=path_base,
        raw=raw,
        workflow=workflow,
    )

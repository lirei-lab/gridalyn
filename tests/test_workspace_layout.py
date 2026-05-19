from pathlib import Path

from gridalyn.foundation import ArtifactLayout, GridalynWorkspace, workspace_from_path


def test_artifact_layout_defines_platform_roots(tmp_path: Path) -> None:
    layout = ArtifactLayout(tmp_path)

    assert layout.configs == tmp_path / "configs"
    assert layout.instances == tmp_path / "instances"
    assert layout.default_instance == tmp_path / "instances" / "default"
    assert layout.digital_twin == tmp_path / "instances" / "default" / "digital_twin"
    assert layout.cache == tmp_path / "instances" / "default" / "digital_twin" / "cache"
    assert layout.base == tmp_path / "instances" / "default" / "digital_twin" / "base"
    assert (
        layout.flexibility
        == tmp_path / "instances" / "default" / "digital_twin" / "flexibility"
    )
    assert (
        layout.operations
        == tmp_path / "instances" / "default" / "digital_twin" / "operations"
    )
    assert layout.project("demo") == tmp_path / "projects" / "demo"
    assert layout.project_outputs("demo") == tmp_path / "projects" / "demo" / "outputs"


def test_workspace_discovers_project_manifests(tmp_path: Path) -> None:
    (tmp_path / "projects" / "alpha").mkdir(parents=True)
    (tmp_path / "projects" / "alpha" / "project.yaml").write_text("metadata: {}\n")
    (tmp_path / "projects" / "notes").mkdir()

    workspace = GridalynWorkspace(tmp_path)

    assert workspace.project_paths() == [tmp_path / "projects" / "alpha"]
    assert workspace.project_path("alpha") == tmp_path / "projects" / "alpha"


def test_workspace_discovers_root_from_nested_project_archive(tmp_path: Path) -> None:
    workspace_root = tmp_path / "archive"
    project_root = workspace_root / "projects" / "demo" / "scripts"
    project_root.mkdir(parents=True)
    (workspace_root / "pyproject.toml").write_text("[project]\nname = \"gridalyn\"\n")
    (workspace_root / "gridalyn").mkdir()
    (workspace_root / "projects" / "demo" / "project.yaml").write_text("metadata: {}\n")

    workspace = workspace_from_path(project_root)

    assert workspace.root == workspace_root
    assert workspace.layout.projects == workspace_root / "projects"


def test_workspace_discovery_falls_back_to_start_path(tmp_path: Path) -> None:
    workspace = workspace_from_path(tmp_path)

    assert workspace.root == tmp_path

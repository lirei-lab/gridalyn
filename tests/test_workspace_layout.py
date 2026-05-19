from pathlib import Path

from gridalyn.foundation import ArtifactLayout, GridalynWorkspace


def test_artifact_layout_defines_platform_roots(tmp_path: Path) -> None:
    layout = ArtifactLayout(tmp_path)

    assert layout.digital_twin == tmp_path / "digital_twin"
    assert layout.cache == tmp_path / "digital_twin" / "cache"
    assert layout.base == tmp_path / "digital_twin" / "base"
    assert layout.flexibility == tmp_path / "digital_twin" / "flexibility"
    assert layout.operations == tmp_path / "digital_twin" / "operations"
    assert layout.project("demo") == tmp_path / "projects" / "demo"
    assert layout.project_outputs("demo") == tmp_path / "projects" / "demo" / "outputs"


def test_workspace_discovers_project_manifests(tmp_path: Path) -> None:
    (tmp_path / "projects" / "alpha").mkdir(parents=True)
    (tmp_path / "projects" / "alpha" / "project.yaml").write_text("metadata: {}\n")
    (tmp_path / "projects" / "notes").mkdir()

    workspace = GridalynWorkspace(tmp_path)

    assert workspace.project_paths() == [tmp_path / "projects" / "alpha"]
    assert workspace.project_path("alpha") == tmp_path / "projects" / "alpha"

import tomllib
from pathlib import Path


def _pyproject() -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


def test_cim_graph_is_optional_not_core_dependency() -> None:
    pyproject = _pyproject()
    dependencies = pyproject["project"]["dependencies"]
    dependency_text = "\n".join(dependencies)
    fork_url_token = "CIM-" + "Graph.git"

    assert "cim-graph" not in dependency_text
    assert fork_url_token not in dependency_text
    assert any(item.startswith("rdflib") for item in dependencies)


def test_optional_cim_extra_uses_published_distribution_not_git_fork() -> None:
    pyproject = _pyproject()
    cim_extra = pyproject["project"]["optional-dependencies"]["cim"]
    extra_text = "\n".join(cim_extra)
    fork_url_token = "CIM-" + "Graph.git"

    assert any(item.startswith("cim-graph") for item in cim_extra)
    assert "git+" not in extra_text
    assert fork_url_token not in extra_text

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
    # rdflib left the base dependency set with the dead io/cim.py exporter
    # (2026-08-07, Phase 9); a base dep with no consumer is dead weight.
    assert not any(item.startswith("rdflib") for item in dependencies)


def test_optional_cim_extra_uses_published_distribution_not_git_fork() -> None:
    pyproject = _pyproject()
    cim_extra = pyproject["project"]["optional-dependencies"]["cim"]
    extra_text = "\n".join(cim_extra)
    fork_url_token = "CIM-" + "Graph.git"

    assert any(item.startswith("cim-graph") for item in cim_extra)
    assert "git+" not in extra_text
    assert fork_url_token not in extra_text


def test_no_rdflib_consumer_under_gridalyn() -> None:
    """No gridalyn module may import rdflib.

    The only rdflib consumer was the dead RDF/XML exporter
    ``gridalyn/twin/io/cim.py``, removed in Phase 9 (2026-08-07). A base or
    extra dependency with no importer is dead weight, so the tree must stay
    rdflib-free until a real consumer appears.
    """
    repo_root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in (repo_root / "gridalyn").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import rdflib" in text or "from rdflib" in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"rdflib consumers remain: {offenders}"

import ast
import tomllib
from pathlib import Path


def _pyproject() -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


def _imports_rdflib(node: ast.AST) -> bool:
    """Report whether one AST node is a real ``rdflib`` import statement."""
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] == "rdflib" for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "rdflib"
    return False


def _rdflib_import_sites(package_dir: Path) -> list[str]:
    """Return ``path:line`` for every real ``rdflib`` import under a package."""
    sites = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sites.extend(
            f"{path.relative_to(package_dir.parent)}:{node.lineno}"
            for node in ast.walk(tree)
            if _imports_rdflib(node)
        )
    return sites


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
    rdflib-free until a real consumer appears. Phase 11 adopts CGMES
    **semantics** over parquet (``gridalyn/twin/adapters/cim.py``) precisely so
    that this stays 0 -- which makes this the gate that tells approach C apart
    from a Phase-9 reversal.

    This is an **AST** scan, not a text scan. Retro item #3: a substring search
    for ``"import rdflib"`` matches the prose that documents the removal --
    including this docstring -- so it goes red on documentation and can never
    be written honestly.
    """
    repo_root = Path(__file__).resolve().parents[1]

    offenders = _rdflib_import_sites(repo_root / "gridalyn")

    assert not offenders, f"rdflib consumers remain: {offenders}"


def test_rdflib_scan_reads_imports_not_text() -> None:
    """The scan must catch a real import and ignore prose that names one.

    Both halves matter. Catching ``import rdflib`` only at module scope would
    miss a deferred import inside a function, which is exactly how an optional
    dependency sneaks back in; matching the text would make the docstring above
    -- which contains the literal phrase -- a permanent false positive.
    """
    real_import = ast.parse("def f():\n    import rdflib.plugins\n")
    aliased = ast.parse("from rdflib import Graph\n")
    unrelated = ast.parse("import rdflib_is_not_this\n")
    prose = ast.parse('"""documents that import rdflib was removed."""\n')

    assert any(_imports_rdflib(node) for node in ast.walk(real_import))
    assert any(_imports_rdflib(node) for node in ast.walk(aliased))
    assert not any(_imports_rdflib(node) for node in ast.walk(unrelated))
    assert not any(_imports_rdflib(node) for node in ast.walk(prose))

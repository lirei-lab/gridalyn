"""Gates for extensions that contribute a semantic capability (bd 4ky.8).

Finding H7 (2026-09-10): ``ExtensionRegistry.resolve`` had no caller in
gridalyn, ``resolve_declared_extensions`` had none outside tests, no project
declared an extension, and the runner only snapshotted the registry into
provenance. The acceptance, each pinned here:

* an example extension under ``examples/extensions`` registers a capability that
  a project declares, and the semantic build uses it -- run for real, through
  the runner and a stage subprocess, not a dry run;
* removing the declaration makes the build fail loudly, not silently -- with
  the extension still installed, which is what proves it is never loaded
  ambiently.

The routing rules are pinned in-process against private registries, so no test
leaves a capability behind in the shared defaults.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from gridalyn.foundation.platform.extensions import ExtensionRegistry
from gridalyn.projects.extension_roles import (
    register_declared_extensions,
    register_extension_contribution,
)
from gridalyn.twin.semantic.mappings import build_semantic_graph
from gridalyn.twin.semantic.profile import profile_with_capabilities
from gridalyn.twin.semantic.registry import SemanticCapabilityRegistry
from gridalyn.twin.semantic.validation import validate_semantic_graph

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "extensions" / "feeder_criticality"
RUN_EXAMPLE = EXAMPLE_DIR / "run_example.py"


def _example() -> ModuleType:
    """Import the example extension module without touching ``sys.path``."""
    name = "feeder_criticality_example_under_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, EXAMPLE_DIR / "feeder_criticality.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _registered(role: str = "semantic_capability", factory=None) -> tuple:
    """A private engine holding one extension, as the entry-point loader leaves it."""
    example = _example()
    engine = ExtensionRegistry()
    descriptor = replace(example.descriptor, role=role, source="entry_point")
    engine.register(factory or example.factory, descriptor=descriptor)
    return engine, engine.get_descriptor(descriptor.extension_id)


def _network() -> dict[str, pd.DataFrame]:
    raw = json.loads((EXAMPLE_DIR / "study" / "inputs" / "network.json").read_text())
    return {name: pd.DataFrame(rows) for name, rows in raw.items()}


# ─── Routing, in-process ─────────────────────────────────────────────────


def test_a_semantic_capability_extension_is_contributed_under_its_provenance() -> None:
    engine, descriptor = _registered()
    capabilities = SemanticCapabilityRegistry()
    assert register_extension_contribution(
        descriptor, registry=engine, capability_registry=capabilities
    )
    assert list(capabilities.list_ids()) == ["feeder_criticality"]
    assert capabilities.registration_source("feeder_criticality") == "entry_point"
    assert capabilities.registration_version("feeder_criticality") == "0.1.0"


def test_contributing_the_same_extension_twice_is_a_no_op() -> None:
    engine, descriptor = _registered()
    capabilities = SemanticCapabilityRegistry()
    assert register_extension_contribution(
        descriptor, registry=engine, capability_registry=capabilities
    )
    assert not register_extension_contribution(
        descriptor, registry=engine, capability_registry=capabilities
    )


def test_a_capability_id_held_by_another_declaration_is_refused() -> None:
    engine, descriptor = _registered()
    capabilities = SemanticCapabilityRegistry()
    capabilities.register(_example().CAPABILITY, source="host", version="0.0.1")
    with pytest.raises(ValueError, match="already registered by 'host'"):
        register_extension_contribution(
            descriptor, registry=engine, capability_registry=capabilities
        )


def test_a_factory_returning_the_wrong_type_is_refused() -> None:
    engine, descriptor = _registered(factory=lambda: "not a capability")
    with pytest.raises(TypeError, match="returned str"):
        register_extension_contribution(
            descriptor,
            registry=engine,
            capability_registry=SemanticCapabilityRegistry(),
        )


def test_an_interaction_protocol_extension_is_refused_loudly() -> None:
    def never_called() -> None:
        raise AssertionError("a refused role must not be instantiated")

    engine, descriptor = _registered(role="interaction_protocol", factory=never_called)
    capabilities = SemanticCapabilityRegistry()
    with pytest.raises(ValueError, match="closed set"):
        register_extension_contribution(
            descriptor, registry=engine, capability_registry=capabilities
        )
    assert list(capabilities.list_ids()) == []


def test_other_roles_stay_in_the_generic_registry() -> None:
    engine, descriptor = _registered(role="data_source")
    capabilities = SemanticCapabilityRegistry()
    assert not register_extension_contribution(
        descriptor, registry=engine, capability_registry=capabilities
    )
    assert list(capabilities.list_ids()) == []
    assert engine.get_descriptor(descriptor.extension_id).role == "data_source"


def test_a_project_that_declares_nothing_contributes_nothing() -> None:
    assert (
        register_declared_extensions(REPO_ROOT / "projects" / "minimal_grid_project")
        == []
    )


def test_the_contributed_capability_builds_and_validates() -> None:
    engine, descriptor = _registered()
    capabilities = SemanticCapabilityRegistry()
    register_extension_contribution(
        descriptor, registry=engine, capability_registry=capabilities
    )
    declared = {"feeder_criticality"}
    nodes, edges, manifest = build_semantic_graph(
        capabilities=declared, registry=capabilities, **_network()
    )
    assessments = nodes.loc[nodes["semantic_type"] == "crit:CriticalityAssessment"]
    assert sorted(assessments["source_id"]) == ["transformer:0", "transformer:1"]
    criticality = {
        row["source_id"]: json.loads(row["properties"])["criticality"]
        for _, row in assessments.iterrows()
    }
    assert criticality == {"transformer:0": "high", "transformer:1": "normal"}
    assesses = edges.loc[edges["relationship_type"] == "ASSESSES_CRITICALITY"]
    assert sorted(assesses["target_id"]) == ["transformer:0", "transformer:1"]
    assert manifest["capabilities"] == ["feeder_criticality"]
    report = validate_semantic_graph(
        nodes, edges, profile_with_capabilities(declared, registry=capabilities)
    )
    assert report["valid"], report["errors"]


# ─── The example, run for real ───────────────────────────────────────────


def _run_example(*arguments: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(RUN_EXAMPLE), *arguments],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_the_example_study_builds_its_graph_with_the_declared_capability() -> None:
    result = _run_example()
    assert result.returncode == 0, result.stderr[-2000:]
    summary = json.loads(result.stdout)
    assert summary["status"] == "completed"
    assert summary["valid"] is True
    graph = summary["graph"]
    assert graph["capabilities"] == ["feeder_criticality"]
    assert graph["contributed_extensions"] == ["feeder_criticality"]
    assert graph["criticality_assessments"] == 2
    assert {
        "extension_id": "feeder_criticality",
        "role": "semantic_capability",
        "source": "entry_point",
        "version": "0.1.0",
    } in summary["extensions"]


def test_removing_the_declaration_fails_the_build_loudly() -> None:
    """The extension stays installed; undeclared, it is never loaded."""
    result = _run_example("--without-declaration")
    assert result.returncode != 0
    assert "UnknownSemanticCapabilityError" in result.stderr
    assert "'feeder_criticality'" in result.stderr
    assert result.stdout.strip() == ""

"""Tests for the declared-extensions project input loaders (Phase 15, 15-04).

``spec.inputs.extensions`` declares which extension IDs a project resolves on
demand. The loader must be R7-safe: a project that declares nothing loads
nothing, so its runs stay byte-identical.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gridalyn.projects.loader import load_project
from gridalyn.projects.model_inputs import (
    DeclaredExtension,
    load_declared_extensions,
    resolve_declared_extensions,
)

_PROJECT_TEMPLATE = """\
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: extension_fixture
  version: 0.1.0
  description: fixture
spec:
  pathBase: project
  problem:
    type: powerflow_validation
    dataset: test_dataset
    environment: test_environment
    objective: test declared extensions loader
    model:
      type: simulation_model
      name: sample
    scenarios:
      - id: baseline
        role: deterministic_baseline
  experiments: []
  inputs: {inputs}
  artifacts: {{}}
  workflow:
    file: workflow.yaml
  validation: {{}}
"""

_WORKFLOW = """\
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: sample_workflow
spec:
  stages:
    - id: build
      command: echo build
"""


def _load(tmp: str, inputs_yaml: str) -> Path:
    root = Path(tmp)
    (root / "workflow.yaml").write_text(_WORKFLOW, encoding="utf-8")
    (root / "project.yaml").write_text(
        _PROJECT_TEMPLATE.format(inputs=inputs_yaml), encoding="utf-8"
    )
    return root / "project.yaml"


class LoadDeclaredExtensionsTest(unittest.TestCase):
    def test_absent_extensions_declare_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{}"))
            self.assertEqual((), load_declared_extensions(project))

    def test_string_declarations_parse_with_default_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(
                _load(tmp, "{extensions: ['acme-backend', 'data-producer']}")
            )
            declared = load_declared_extensions(project)
        self.assertEqual(
            (
                DeclaredExtension(extension_id="acme-backend"),
                DeclaredExtension(extension_id="data-producer"),
            ),
            declared,
        )
        self.assertEqual("gridalyn.extensions", declared[0].group)

    def test_mapping_declarations_parse_with_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(
                _load(tmp, "{extensions: [{id: probe-ext, group: custom.group}]}")
            )
            declared = load_declared_extensions(project)
        self.assertEqual(
            (DeclaredExtension(extension_id="probe-ext", group="custom.group"),),
            declared,
        )

    def test_non_list_extensions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{extensions: 'oops'}"))
            with self.assertRaisesRegex(ValueError, "must be a list"):
                load_declared_extensions(project)

    def test_entry_without_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{extensions: [{name: probe}]}"))
            with self.assertRaisesRegex(ValueError, "'id'"):
                load_declared_extensions(project)

    def test_non_string_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{extensions: [42]}"))
            with self.assertRaisesRegex(ValueError, "extension ID string"):
                load_declared_extensions(project)


class ResolveDeclaredExtensionsTest(unittest.TestCase):
    def test_resolve_groups_by_entry_point_and_loads_only_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(
                _load(
                    tmp,
                    "{extensions: ['acme-backend', 'custom-ext']}",
                )
            )
            calls: list[tuple[str, list[str]]] = []

            def _fake_load(group: str, declared_ids: list[str]) -> list[object]:
                calls.append((group, list(declared_ids)))
                return [
                    mock.Mock(extension_id=extension_id, source="entry_point")
                    for extension_id in declared_ids
                ]

            with mock.patch(
                "gridalyn.foundation.platform.extensions.load_entry_point_extensions",
                side_effect=_fake_load,
            ):
                resolved = resolve_declared_extensions(project)

        self.assertEqual(1, len(calls))
        self.assertEqual("gridalyn.extensions", calls[0][0])
        self.assertEqual(["acme-backend", "custom-ext"], calls[0][1])
        self.assertEqual(
            ["acme-backend", "custom-ext"],
            [descriptor.extension_id for descriptor in resolved],
        )

    def test_resolve_nothing_when_no_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{}"))
            with mock.patch(
                "gridalyn.foundation.platform.extensions.load_entry_point_extensions"
            ) as loader:
                resolved = resolve_declared_extensions(project)
        self.assertEqual([], resolved)
        loader.assert_not_called()

    def test_resolve_propagates_unready_extension_error(self) -> None:
        """The programmatic path enforces capability readiness (never silent)."""
        from gridalyn.foundation.platform.capabilities import MissingCapabilityError

        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_load(tmp, "{extensions: ['acme-backend']}"))
            with (
                mock.patch(
                    "gridalyn.foundation.platform.extensions.load_entry_point_extensions",
                    return_value=[mock.Mock(extension_id="acme-backend")],
                ),
                mock.patch(
                    "gridalyn.foundation.platform.capabilities.require_extension_capabilities",
                    side_effect=MissingCapabilityError("needs the 'sim' extra"),
                ),
            ):
                with self.assertRaisesRegex(MissingCapabilityError, "sim"):
                    resolve_declared_extensions(project)

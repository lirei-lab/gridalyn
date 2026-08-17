"""Tests for the declared project-development binding surface."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandapower as pp
import yaml

from gridalyn.projects import (
    ProjectComponents,
    bind_project_components,
    init_project,
    project_script,
)


class TestBindProjectComponents(unittest.TestCase):
    def test_binds_declared_components_from_real_project(self) -> None:
        # The minimal project declares sourceNetwork + loadGeneration; the
        # default backend resolves. This exercises the REAL typed loaders.
        script = project_script(Path("projects/minimal_grid_project"))
        components = bind_project_components(script)

        self.assertIsInstance(components, ProjectComponents)
        self.assertIsNotNone(components.feeder_spec)
        self.assertIsNotNone(components.load_profiles)
        self.assertIsNotNone(components.backend)
        # Core backends are never recorded as project components.
        self.assertNotIn("backend", components.registered)

    def test_empty_bind_is_valid(self) -> None:
        # A project with no declared inputs yields a minimal-but-valid bundle.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bare"
            init_project(target, name="bare")
            script = project_script(target)

            components = bind_project_components(script)

            self.assertIsNone(components.feeder_spec)
            self.assertIsNone(components.load_profiles)
            self.assertIsNotNone(components.backend)  # registry default

    def test_build_feeder_constructs_net(self) -> None:
        script = project_script(Path("projects/minimal_grid_project"))
        components = bind_project_components(script)

        net = components.build_feeder()

        self.assertIsInstance(net, pp.pandapowerNet)
        self.assertGreaterEqual(len(net.bus), 2)

    def test_build_feeder_without_spec_raises_located(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bare"
            init_project(target, name="bare")
            script = project_script(target)
            components = bind_project_components(script)

            with self.assertRaises(ValueError) as ctx:
                components.build_feeder()
            self.assertIn("sourceNetwork", str(ctx.exception))

    def test_to_dict_is_json_native(self) -> None:
        script = project_script(Path("projects/minimal_grid_project"))
        components = bind_project_components(script)

        payload = components.to_dict()
        json.dumps(payload)  # must not raise
        self.assertIn("feeder_spec", payload)
        self.assertIn("has_load_profiles", payload)
        self.assertIn("backend_id", payload)

    def test_declared_but_malformed_input_raises_not_swallowed(self) -> None:
        # A declared-but-malformed sourceNetwork is a contract violation: the
        # loader's located ValueError must propagate, NOT be silently converted
        # to feeder_spec=None (which would mis-report "no sourceNetwork").
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bare"
            init_project(target, name="bare")
            project_yaml = target / "project.yaml"
            raw = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
            raw.setdefault("spec", {}).setdefault("inputs", {})["sourceNetwork"] = {
                # A mapping with the WRONG model.type — the loader rejects it
                # with a located error naming the key.
                "model": {"type": "not_a_feeder", "name": "broken"}
            }
            project_yaml.write_text(yaml.safe_dump(raw), encoding="utf-8")
            script = project_script(target)

            with self.assertRaises(ValueError) as ctx:
                bind_project_components(script)
            # The loader's located error names the key, not a generic message.
            self.assertIn("sourceNetwork", str(ctx.exception))

    def test_non_mapping_spec_inputs_raises_located(self) -> None:
        # spec.inputs present but not a mapping is declared-but-malformed: it
        # must raise, not silently bind every component to None.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bare"
            init_project(target, name="bare")
            project_yaml = target / "project.yaml"
            raw = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
            raw.setdefault("spec", {})["inputs"] = "not-a-mapping"
            project_yaml.write_text(yaml.safe_dump(raw), encoding="utf-8")
            script = project_script(target)

            with self.assertRaises(ValueError) as ctx:
                bind_project_components(script)
            self.assertIn("spec.inputs", str(ctx.exception))


class TestRegisteredComponents(unittest.TestCase):
    def test_consume_unknown_role_raises_located(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bare"
            init_project(target, name="bare")
            script = project_script(target)
            components = bind_project_components(script)

            with self.assertRaises(ValueError) as ctx:
                components.consume("backend", "nope")
            self.assertIn("registered", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

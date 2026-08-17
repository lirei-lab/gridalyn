"""Tests for the declared project-development binding surface."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandapower as pp

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

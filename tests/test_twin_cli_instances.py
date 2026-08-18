"""The twin CLI is a general mechanism for any project's twin.

Phase 21 made the twin model-first in semantics; this module proves the same
generalization reaches the CLI/build surface. A twin is materialized at a
**named instance** under ``<root>/instances/<instance>/digital_twin`` with a
**declared capability set**, so ``gridalyn twin`` is not hard-wired to the
legacy ``default`` instance or to the EV/flexibility layers of one study:

* ``--instance`` selects which twin to build/inspect (any project's twin);
* ``--capabilities`` declares which on-demand layers to include (``""`` is a
  generic model-first build, ``flexibility``/``ev-hosting`` opt in);
* layer subcommands thread the selection to their scripts via
  ``GRIDALYN_INSTANCE``/``GRIDALYN_WORKSPACE_ROOT``.

All defaults are backward compatible: omitting both flags keeps the legacy
``default`` instance + ``ev-hosting,flexibility`` build exactly as before.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gridalyn.foundation import ArtifactLayout
from gridalyn.interfaces.cli import digital_twin
from gridalyn.projects.workflows.digital_twin.build import (
    build_digital_twin_steps,
    run_digital_twin_build,
)


class TwinInstanceTest(unittest.TestCase):
    def test_named_instance_layout_points_at_selected_twin(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = ArtifactLayout(root, instance="proj_x")
            self.assertEqual(
                layout.digital_twin,
                root / "instances" / "proj_x" / "digital_twin",
            )
            # The legacy alias still names the canonical instance.
            self.assertEqual(layout.default_instance, root / "instances" / "default")

    def test_generic_capability_set_plans_no_ev_or_flex_steps(self) -> None:
        names = {step["name"] for step in build_digital_twin_steps(capabilities=set())}
        self.assertNotIn("generate_scenarios", names)
        self.assertNotIn("generate_ev_timeseries", names)
        self.assertNotIn("run_powerflow", names)
        self.assertNotIn("generate_flexibility_providers", names)
        # The generic core is always present.
        self.assertIn("export_base", names)
        self.assertIn("generate_building_models", names)
        self.assertIn("generate_semantic_graph", names)

    def test_declared_capability_builds_core_plus_that_layer(self) -> None:
        names = {
            step["name"]
            for step in build_digital_twin_steps(capabilities={"flexibility"})
        }
        self.assertIn("generate_flexibility_providers", names)
        self.assertNotIn("generate_scenarios", names)
        self.assertNotIn("run_powerflow", names)

    def test_dry_run_build_on_named_instance_writes_to_that_instance(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = run_digital_twin_build(
                root=root,
                skip_heavy=True,
                dry_run=True,
                instance="alt",
                capabilities=set(),
            )
            self.assertEqual(manifest["instance"], "alt")
            self.assertEqual(manifest["step_count"], 6)
            self.assertIn(
                "instances/alt/digital_twin/dashboard/catalog.json",
                manifest["artifacts"]["dashboard_catalog"],
            )
            written = (
                root
                / "instances"
                / "alt"
                / "digital_twin"
                / "reports"
                / "digital_twin_build_manifest.json"
            )
            self.assertTrue(written.exists())
            on_disk = json.loads(written.read_text())
            self.assertEqual(on_disk["instance"], "alt")

    def test_cli_build_parses_instance_and_capabilities(self) -> None:
        parser = digital_twin.build_parser()
        args = parser.parse_args(
            ["build", "--instance", "alt", "--capabilities", "flexibility"]
        )
        self.assertEqual(args.instance, "alt")
        caps = digital_twin._parse_capabilities(args.capabilities)
        self.assertEqual(caps, {"flexibility"})

    def test_cli_build_empty_capabilities_is_generic_model_first(self) -> None:
        parser = digital_twin.build_parser()
        args = parser.parse_args(["build", "--instance", "alt", "--capabilities", ""])
        self.assertEqual(digital_twin._parse_capabilities(args.capabilities), set())

    def test_layer_subcommand_threads_instance_into_script_env(self) -> None:
        with TemporaryDirectory() as tmpdir:
            args, _ = digital_twin.parse_args(
                ["building-models", "--instance", "alt", "--root", tmpdir]
            )
            with mock.patch.object(
                digital_twin, "run_module_as_script", return_value=0
            ) as runner:
                args.handler(args)
                runner.assert_called_once()
            self.assertEqual(os.environ["GRIDALYN_INSTANCE"], "alt")
            self.assertEqual(
                os.environ["GRIDALYN_WORKSPACE_ROOT"], str(Path(tmpdir).resolve())
            )

    def test_cli_build_handler_plans_generic_alt_instance(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parser = digital_twin.build_parser()
            args = parser.parse_args(
                [
                    "build",
                    "--root",
                    str(root),
                    "--instance",
                    "alt",
                    "--capabilities",
                    "",
                    "--dry-run",
                    "--skip-heavy",
                ]
            )
            with mock.patch.object(
                digital_twin,
                "_display_path",
                side_effect=lambda p: str(p),
            ):
                rc = args.handler(args)
            self.assertEqual(rc, 0)
            manifest_path = (
                root
                / "instances"
                / "alt"
                / "digital_twin"
                / "reports"
                / "digital_twin_build_manifest.json"
            )
            self.assertTrue(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()

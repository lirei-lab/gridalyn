"""Unit tests for the flagship shape-covering subset runner.

These tests exercise the tool's decision logic (stage enumeration,
topological ordering, heavy-skip, fail-loud, per-stage record shape) with
synthetic stage lists. They never run the real study, so the suite stays fast
and hermetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL_PATH = _REPO_ROOT / "tools" / "flagship_verify.py"


def _load_tool() -> ModuleType:
    """Import ``tools/flagship_verify.py`` without touching ``sys.path``."""
    spec = importlib.util.spec_from_file_location("flagship_verify", _TOOL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {_TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _stage(sid: str, needs: list[str] | None = None) -> dict:
    return {"id": sid, "needs": needs or [], "command": f"{sid} --noop"}


class FlagshipVerifyTests(unittest.TestCase):
    """The decision logic is correct and the CLI shape is stable."""

    def test_topo_sort_respects_needs(self) -> None:
        stages = [
            _stage("c", ["b"]),
            _stage("b", ["a"]),
            _stage("a"),
        ]
        ordered = [s["id"] for s in tool.topo_sort(stages)]
        self.assertLess(ordered.index("a"), ordered.index("b"))
        self.assertLess(ordered.index("b"), ordered.index("c"))

    def test_topo_sort_detects_cycles(self) -> None:
        stages = [_stage("a", ["b"]), _stage("b", ["a"])]
        with self.assertRaises(RuntimeError):
            tool.topo_sort(stages)

    def test_heavy_stage_is_skipped_by_default_with_reason(self) -> None:
        stages = tool.topo_sort(
            [
                _stage("prepare"),
                {
                    "id": "generate_annual_mc",
                    "needs": ["prepare"],
                    "command": "heavy --noop",
                },
                _stage("after", ["generate_annual_mc"]),
            ]
        )
        decisions = tool.classify_runs(stages)
        by_id = {s["id"]: (action, reason) for s, action, reason in decisions}
        self.assertEqual("skipped", by_id["generate_annual_mc"][0])
        self.assertIn("heavy", by_id["generate_annual_mc"][1])
        # A stage depending on a skipped stage is skipped with a reason too.
        self.assertEqual("skipped", by_id["after"][0])
        self.assertIn("depends on skipped", by_id["after"][1])

    def test_include_heavy_runs_the_heavy_stage(self) -> None:
        stages = tool.topo_sort([_stage("a"), _stage("generate_annual_mc", ["a"])])
        decisions = tool.classify_runs(stages, include_heavy=True)
        by_id = {s["id"]: action for s, action, _ in decisions}
        self.assertEqual("run", by_id["generate_annual_mc"])

    def test_per_stage_record_shape(self) -> None:
        from unittest import mock

        stages = tool.topo_sort([_stage("a"), _stage("generate_annual_mc", ["a"])])
        with mock.patch.object(tool, "load_stages", return_value=stages):
            result = tool.run_subset(
                Path("."), include_heavy=False, dry_run=True, run_baselines_check=False
            )
        records = result["stages"]
        self.assertTrue(records)
        for record in records:
            self.assertEqual({"name", "status", "duration_s", "reason"}, set(record))
            self.assertIn(record["status"], {"run", "skipped", "ok", "failed"})
        by_name = {r["name"]: r for r in records}
        self.assertEqual("skipped", by_name["generate_annual_mc"]["status"])

    def test_failing_non_heavy_stage_raises(self) -> None:
        from unittest import mock

        stages = tool.topo_sort([_stage("boom")])
        with (
            mock.patch.object(tool, "load_stages", return_value=stages),
            mock.patch(
                "subprocess.run",
                return_value=mock.Mock(returncode=1),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                tool.run_subset(
                    Path("."), include_heavy=False, run_baselines_check=False
                )
        self.assertIn("boom", str(ctx.exception))

    def test_real_workflow_parses_and_enumerates_stages(self) -> None:
        stages = tool.topo_sort(tool.load_stages(_REPO_ROOT))
        self.assertEqual(23, len(stages))
        self.assertIn("generate_annual_mc", tool.HEAVY_STAGES)

    # -- R7 baseline check (review fix: was untested) -------------------------

    def test_check_baselines_pass(self) -> None:
        from unittest import mock

        with mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ):
            status, detail = tool.check_baselines(_REPO_ROOT)
        self.assertEqual("PASS", status)
        self.assertIn("byte-identical", detail)

    def test_check_baselines_warning_never_raises(self) -> None:
        from unittest import mock

        with mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=1, stdout="", stderr=""),
        ):
            status, detail = tool.check_baselines(_REPO_ROOT)
        self.assertEqual("WARNING", status)
        self.assertTrue(detail)

    def test_run_subset_populates_baselines_when_requested(self) -> None:
        from unittest import mock

        stages = tool.topo_sort([_stage("a")])
        with (
            mock.patch.object(tool, "load_stages", return_value=stages),
            mock.patch(
                "subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ),
        ):
            result = tool.run_subset(
                Path("."), include_heavy=False, run_baselines_check=True
            )
        self.assertEqual("PASS", result["baselines"]["status"])
        self.assertEqual("ok", result["stages"][0]["status"])

    # -- CLI surface (review fix: was untested) -------------------------------

    def test_main_dry_run_writes_out_json(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "records.json"
            code = tool.main(
                [
                    "--dry-run",
                    "--no-check-baselines",
                    "--workspace",
                    str(_REPO_ROOT),
                    "--out-json",
                    str(out),
                ]
            )
            self.assertEqual(0, code)
            self.assertTrue(out.exists())
            payload = json.loads(out.read_text())
            self.assertEqual(23, len(payload["stages"]))

    def test_main_list_stages_exits_zero(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = tool.main(["--list-stages", "--workspace", str(_REPO_ROOT)])
        self.assertEqual(0, code)
        self.assertEqual(23, len(buffer.getvalue().splitlines()))

    def test_main_usage_error_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            tool.main(["--bogus-flag"])
        self.assertEqual(2, ctx.exception.code)

    # -- load_stages error branches (review suggestion) -----------------------

    def test_load_stages_missing_workflow_raises_located_error(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError) as ctx:
                tool.load_stages(Path(tmpdir))
        self.assertIn("workflow.yaml", str(ctx.exception))

    def test_load_stages_empty_stages_raises_located_error(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "projects").mkdir(parents=True)
            (Path(tmpdir) / "projects" / "ev_hosting_flex").mkdir()
            (Path(tmpdir) / tool.WORKFLOW_PATH).write_text(
                "spec:\n  stages: []\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError) as ctx:
                tool.load_stages(Path(tmpdir))
        self.assertIn("spec.stages", str(ctx.exception))

    # -- remaining decision-logic pins (review suggestions) -------------------

    def test_cycle_error_names_the_stuck_stages(self) -> None:
        stages = [_stage("a", ["b"]), _stage("b", ["a"])]
        with self.assertRaises(RuntimeError) as ctx:
            tool.topo_sort(stages)
        message = str(ctx.exception)
        self.assertIn("a", message)
        self.assertIn("b", message)

    def test_command_resolves_the_python_placeholder(self) -> None:
        stage = {"id": "x", "needs": [], "command": "{python} -m gridalyn foo"}
        resolved = tool._command(stage)
        self.assertNotIn("{python}", resolved)
        self.assertTrue(resolved.startswith(sys.executable))

    def test_failed_stage_exception_carries_the_audit_trail(self) -> None:
        from unittest import mock

        stages = tool.topo_sort([_stage("a"), _stage("boom", ["a"])])
        fake = mock.Mock(returncode=0, stdout="", stderr="")
        fake.returncode = 0
        with (
            mock.patch.object(tool, "load_stages", return_value=stages),
            mock.patch("subprocess.run", return_value=fake) as runner,
        ):
            runner.side_effect = [
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=1, stdout="", stderr=""),
            ]
            with self.assertRaises(tool.FlagshipSubsetError) as ctx:
                tool.run_subset(
                    Path("."), include_heavy=False, run_baselines_check=False
                )
        names = [r["name"] for r in ctx.exception.records]
        self.assertEqual(["a", "boom"], names)
        self.assertEqual("failed", ctx.exception.records[-1]["status"])

    def test_main_persists_out_json_and_exits_one_on_failure(self) -> None:
        """A failed run still writes its audit trail and returns exit 1."""
        from tempfile import TemporaryDirectory
        from unittest import mock

        stages = tool.topo_sort([_stage("a"), _stage("boom", ["a"])])
        with TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "records.json"
            with (
                mock.patch.object(tool, "load_stages", return_value=stages),
                mock.patch(
                    "subprocess.run",
                    side_effect=[
                        mock.Mock(returncode=0, stdout="", stderr=""),
                        mock.Mock(returncode=1, stdout="", stderr=""),
                    ],
                ),
            ):
                code = tool.main(
                    [
                        "--no-check-baselines",
                        "--workspace",
                        str(_REPO_ROOT),
                        "--out-json",
                        str(out),
                    ]
                )
            self.assertEqual(1, code)
            self.assertTrue(out.exists())
            payload = json.loads(out.read_text())
            self.assertEqual(1, payload["exit_code"])
            self.assertEqual("failed", payload["stages"][-1]["status"])


if __name__ == "__main__":
    unittest.main()

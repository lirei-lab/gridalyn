"""Unit tests for the flagship shape-covering subset runner.

These tests exercise the tool's decision logic (stage enumeration,
topological ordering, heavy-skip, fail-loud, per-stage record shape) with
synthetic stage lists. They never run the real study, so the suite stays fast
and hermetic.
"""

from __future__ import annotations

import importlib.util
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
                Path("."), include_heavy=False, dry_run=True, check_baselines=False
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
                tool.run_subset(Path("."), include_heavy=False, check_baselines=False)
        self.assertIn("boom", str(ctx.exception))

    def test_real_workflow_parses_and_enumerates_stages(self) -> None:
        stages = tool.topo_sort(tool.load_stages(_REPO_ROOT))
        self.assertEqual(22, len(stages))
        self.assertIn("generate_annual_mc", tool.HEAVY_STAGES)


if __name__ == "__main__":
    unittest.main()

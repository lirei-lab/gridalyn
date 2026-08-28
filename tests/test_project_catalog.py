"""Describing a study's artifacts so a viewer needs no per-study code.

The dashboard carried a component dedicated to one study because it knew that
study's artifact shape. These tests pin what replaced it: the declaration is
the one already in ``project.yaml``, a governed report is confirmed against the
contract rather than assumed from its name, and a study that ships nothing
renderable says so instead of vanishing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS
from gridalyn.projects.project_catalog import (
    KIND_GOVERNED_REPORT,
    KIND_TABLE,
    KIND_UNKNOWN,
    build_project_catalog,
    classify_artifact,
    describe_artifact,
)


@dataclass(frozen=True)
class _Project:
    """Minimal stand-in carrying the attributes the catalog reads."""

    name: str
    base_dir: Path
    raw: dict[str, Any]


def _governed_report(report_id: str, **overrides: Any) -> dict[str, Any]:
    payload = {field: None for field in REQUIRED_REPORT_FIELDS}
    payload.update(
        {
            "report_id": report_id,
            "schema_version": "1.0",
            "source_domain": "demo_study",
            "summary": {"min_voltage_pu": 0.95, "converged": True},
            "validation": {"valid": True},
            "artifacts": [],
            "inputs": {},
            "created_at": "2026-08-28T00:00:00+00:00",
        }
    )
    payload.update(overrides)
    return payload


class ClassifyArtifactTest(unittest.TestCase):
    def test_json_under_reports_is_a_candidate_governed_report(self):
        self.assertEqual(
            classify_artifact("outputs/reports/x_report.json"), KIND_GOVERNED_REPORT
        )

    def test_tabular_artifacts_are_tables_wherever_they_live(self):
        for relative in (
            "outputs/data/buses.csv",
            "outputs/operations/q_table.csv",
            "outputs/data/frame.parquet",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(classify_artifact(relative), KIND_TABLE)

    def test_anything_else_is_unknown_rather_than_guessed_at(self):
        self.assertEqual(classify_artifact("outputs/figures/plot.png"), KIND_UNKNOWN)
        self.assertEqual(classify_artifact("outputs/data/config.json"), KIND_UNKNOWN)


class DescribeArtifactTest(unittest.TestCase):
    def test_a_governed_report_contributes_its_identity_and_summary_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "outputs" / "reports" / "demo_report.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps(_governed_report("demo_report")))
            described = describe_artifact(
                "outputs/reports/demo_report.json",
                project_dir=root,
                served_prefix="/projects/demo",
            )
        self.assertEqual(described["kind"], KIND_GOVERNED_REPORT)
        self.assertEqual(described["report_id"], "demo_report")
        self.assertEqual(described["source_domain"], "demo_study")
        self.assertEqual(described["valid"], True)
        self.assertEqual(described["summary_keys"], ["converged", "min_voltage_pu"])
        self.assertEqual(
            described["path"], "/projects/demo/outputs/reports/demo_report.json"
        )

    def test_the_catalog_indexes_summary_keys_not_summary_values(self):
        """Two copies of a number drift the moment one is regenerated."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "outputs" / "reports" / "demo_report.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps(_governed_report("demo_report")))
            described = describe_artifact(
                "outputs/reports/demo_report.json",
                project_dir=root,
                served_prefix="/projects/demo",
            )
        self.assertNotIn("summary", described)
        self.assertNotIn(0.95, described.values())

    def test_json_in_reports_that_is_not_a_governed_report_is_demoted(self):
        """Named like a report, shaped like a domain payload.

        `synthetic_geojson_feeder` ships exactly this: a
        `synthetic_network_validation_report.json` carrying eight domain keys
        and none of the required report fields. Calling it a governed report
        because of its name and folder would hand the viewer a payload it
        cannot render.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "outputs" / "reports" / "domain_report.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({"report_id": "x", "valid": True}))
            described = describe_artifact(
                "outputs/reports/domain_report.json",
                project_dir=root,
                served_prefix="/projects/demo",
            )
        self.assertEqual(described["kind"], KIND_UNKNOWN)
        self.assertIn("does not carry the required report fields", described["note"])

    def test_an_absent_artifact_is_declared_absent_not_dropped(self):
        """The two heavy studies gitignore their outputs and must still appear."""
        with tempfile.TemporaryDirectory() as tmp:
            described = describe_artifact(
                "outputs/reports/never_run_report.json",
                project_dir=Path(tmp),
                served_prefix="/projects/demo",
            )
        self.assertFalse(described["exists"])
        self.assertEqual(described["kind"], KIND_GOVERNED_REPORT)

    def test_unreadable_json_is_demoted_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "outputs" / "reports" / "broken_report.json"
            report.parent.mkdir(parents=True)
            report.write_text("{not json")
            described = describe_artifact(
                "outputs/reports/broken_report.json",
                project_dir=root,
                served_prefix="/projects/demo",
            )
        self.assertEqual(described["kind"], KIND_UNKNOWN)


class BuildProjectCatalogTest(unittest.TestCase):
    def _project(self, tmp: str, artifacts: list[str], name: str = "demo_study"):
        root = Path(tmp) / "projects" / name
        root.mkdir(parents=True)
        return _Project(
            name,
            root,
            {
                "metadata": {"description": "A demo study."},
                "spec": {"validation": {"objectiveArtifacts": artifacts}},
            },
        )

    def test_the_declaration_read_is_the_one_already_in_project_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, ["outputs/data/buses.csv"])
            entries = build_project_catalog([project], root=Path(tmp))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["project_id"], "demo_study")
        self.assertEqual(entries[0]["description"], "A demo study.")
        self.assertEqual(entries[0]["base_path"], "/projects/demo_study")
        self.assertEqual(entries[0]["artifacts"][0]["kind"], KIND_TABLE)

    def test_a_project_declaring_nothing_is_listed_with_an_empty_list(self):
        """So a viewer can say "declares nothing to show", not omit it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects" / "bare"
            root.mkdir(parents=True)
            entries = build_project_catalog(
                [_Project("bare", root, {"spec": {}})], root=Path(tmp)
            )
        self.assertEqual(entries[0]["artifacts"], [])
        self.assertEqual(entries[0]["label"], "Bare")

    def test_projects_are_sorted_so_the_catalog_is_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = [
                self._project(tmp, [], name="zeta"),
                self._project(tmp, [], name="alpha"),
            ]
            entries = build_project_catalog(projects, root=Path(tmp))
        self.assertEqual([entry["project_id"] for entry in entries], ["alpha", "zeta"])


class ShippedStudiesTest(unittest.TestCase):
    """The eight shipped studies must all be describable without study code."""

    def test_every_shipped_study_declares_result_artifacts(self):
        from gridalyn.projects.loader import load_project

        root = Path(__file__).resolve().parents[1]
        manifests = sorted((root / "projects").glob("*/project.yaml"))
        self.assertGreaterEqual(len(manifests), 6)
        entries = build_project_catalog(
            [load_project(path) for path in manifests], root=root
        )
        for entry in entries:
            with self.subTest(project=entry["project_id"]):
                self.assertTrue(
                    entry["artifacts"],
                    f"{entry['project_id']} declares no objectiveArtifacts, so a "
                    "generic viewer has nothing to render for it",
                )


if __name__ == "__main__":
    unittest.main()

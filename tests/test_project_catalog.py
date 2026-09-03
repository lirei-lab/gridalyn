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
from types import SimpleNamespace
from typing import Any

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS
from gridalyn.projects.project_catalog import (
    KIND_GOVERNED_REPORT,
    KIND_TABLE,
    KIND_UNKNOWN,
    _problem_objective,
    build_project_catalog,
    classify_artifact,
    describe_artifact,
    describe_experiments,
    describe_governed_metrics,
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

        `synthetic_geojson_feeder` shipped exactly this until 2026-09-02: a
        `synthetic_network_validation_report.json` in `outputs/reports/`,
        carrying eight domain keys and none of the required report fields.
        Calling it a governed report because of its name and folder would hand
        the viewer a payload it cannot render. That file has since been renamed
        to `outputs/data/synthetic_network_validation.json` so it stops
        claiming to be one -- but the demotion this test pins is what has to
        keep working, because the next such payload will not be renamed in
        advance.
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


class DeclaredResultHierarchyTest(unittest.TestCase):
    """A study says which of its numbers are the result; the catalog publishes it.

    Every summary value used to reach the viewer at equal weight, so a headline
    result and a bus count rendered identically -- about thirty tiles on the
    widest shipped study. The hierarchy was declared all along:
    ``spec.experiments[].metrics`` is what the study set out to measure, and a
    baseline pin is what a re-run is checked against.
    """

    def _project(self, spec: dict, name: str = "demo"):
        return SimpleNamespace(name=name, raw={"spec": spec}, base_dir=Path("/tmp"))

    def test_the_question_the_study_asks_is_published(self) -> None:
        project = self._project({"problem": {"objective": "Ask something."}})
        self.assertEqual("Ask something.", _problem_objective(project))

    def test_a_study_without_a_problem_block_yields_an_empty_objective(self) -> None:
        self.assertEqual("", _problem_objective(self._project({})))
        self.assertEqual("", _problem_objective(SimpleNamespace(name="x", raw=None)))

    def test_declared_metrics_reach_the_catalog(self) -> None:
        described = describe_experiments(
            self._project(
                {
                    "experiments": [
                        {
                            "id": "run",
                            "objective": "Measure it.",
                            "metrics": ["min_voltage_pu", "objective_value"],
                            "scenario": "baseline",
                        }
                    ]
                }
            )
        )
        self.assertEqual(1, len(described))
        self.assertEqual(["min_voltage_pu", "objective_value"], described[0]["metrics"])
        self.assertEqual("Measure it.", described[0]["objective"])

    def test_both_scenario_spellings_normalize_to_a_list(self) -> None:
        """The shipped studies use `scenario` and `scenarios`; a consumer
        should read one shape, not two."""
        single = describe_experiments(
            self._project({"experiments": [{"id": "a", "scenario": "baseline"}]})
        )
        plural = describe_experiments(
            self._project({"experiments": [{"id": "b", "scenarios": ["x", "y"]}]})
        )
        self.assertEqual(["baseline"], single[0]["scenarios"])
        self.assertEqual(["x", "y"], plural[0]["scenarios"])

    def test_a_study_declaring_no_experiments_yields_none(self) -> None:
        """Two shipped studies declare no metrics; their viewer must fall back
        to showing everything as supporting detail rather than promoting by a
        guess."""
        self.assertEqual([], describe_experiments(self._project({})))

    def test_baseline_pins_resolve_to_report_and_summary_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "baselines").mkdir()
            (root / "baselines" / "results_baseline.json").write_text(
                json.dumps(
                    {
                        "metrics": [
                            {
                                "id": "summary.total_pv_dispatch_mw",
                                "source": "outputs/reports/r.json",
                                "json_path": ["summary", "total_pv_dispatch_mw"],
                                "tolerance": 0.001,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pins = describe_governed_metrics(root)
        self.assertEqual(1, len(pins))
        self.assertEqual("total_pv_dispatch_mw", pins[0]["key"])
        self.assertEqual("summary", pins[0]["block"])
        self.assertEqual("outputs/reports/r.json", pins[0]["source"])

    def test_a_study_with_no_baseline_is_not_a_defect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], describe_governed_metrics(Path(tmp)))

    def test_an_unreadable_baseline_is_skipped_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "baselines").mkdir()
            (root / "baselines" / "results_baseline.json").write_text("{oops", "utf-8")
            self.assertEqual([], describe_governed_metrics(root))


class ShippedStudyHierarchyTest(unittest.TestCase):
    """The two signals are distinct in the shipped studies, not merged."""

    def test_declared_and_governed_are_not_the_same_set(self) -> None:
        import yaml

        root = Path(__file__).resolve().parent.parent / "projects"
        study = root / "der_voltage_optimization"
        spec = yaml.safe_load((study / "project.yaml").read_text("utf-8"))["spec"]
        declared = {
            metric
            for experiment in describe_experiments(
                SimpleNamespace(name="x", raw={"spec": spec})
            )
            for metric in experiment["metrics"]
        }
        governed = {pin["key"] for pin in describe_governed_metrics(study)}
        self.assertTrue(declared, "the study declares metrics")
        self.assertTrue(governed, "the study pins metrics")
        # They genuinely disagree. Conflating them would lose the distinction
        # between what a study set out to measure and what guards a re-run.
        self.assertNotEqual(declared, governed)


if __name__ == "__main__":
    unittest.main()

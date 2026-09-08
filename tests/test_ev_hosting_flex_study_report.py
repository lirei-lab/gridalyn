"""The study-level report: the artifact the stub stage promised for ten weeks.

`build_study_reports` was `echo "STUB ..."` from the 2026-06-22 scaffold until
2026-09-04, completing in 0.0 s while the manifest counted it (bd eei.9).
These tests pin what the real stage must say, because the failure mode is not a
crash -- it is a report that reads as authoritative while quoting one rating
convention, or claiming an attestation it cannot make from inside its own run.

Tiers: (1) the index-to-cell mapping and the markdown, from config and a
synthetic payload; (3) governed reproduce-and-pin against the emitted report.
"""

from __future__ import annotations

import json

import pytest

from projects.ev_hosting_flex.scripts.config import (
    PROJECT_OUTPUTS_DIR,
    TRIAGE_HEADLINE_RATING_CONVENTION,
    TRIAGE_RATING_CONVENTIONS,
)
from projects.ev_hosting_flex.scripts.pipeline.build_study_reports import (
    HEADLINE_ADOPTION,
    headline_index,
    render_markdown,
)

# ─── 1. Mapping and rendering, from config alone ────────────────────────────


def test_headline_index_agrees_with_the_pinned_baseline_indices() -> None:
    """The stage and the fleet.* pins must address the same cells.

    tests/test_ev_hosting_flex_fleet_triage.py pins triage[16]/triage[40] for
    the baseline; if this stage computed a different index the report and the
    pins would quote different numbers from the same artifact.
    """
    from tests.test_ev_hosting_flex_fleet_triage import PINNED_HEADLINE_INDEX

    for convention, pinned in PINNED_HEADLINE_INDEX.items():
        assert headline_index(convention) == pinned, convention


def test_the_markdown_states_both_conventions_and_marks_the_declared_one() -> None:
    """Quoting one convention would re-hide the 6.7x the study just exposed."""
    summary = {
        "fleet_headline": {
            "declared_convention": TRIAGE_HEADLINE_RATING_CONVENTION,
            "n_transformers": 540,
            "k_base": 3,
            "adoption_ev_per_home": HEADLINE_ADOPTION,
            "dispersion": 0.7,
            "by_convention": {
                conv: {
                    "n_at_risk": 1,
                    "flex_defers": 2,
                    "needs_steel": 3,
                    "base_constrained": 4,
                    "never_binds": 5,
                    "deferred_fraction_of_at_risk": 0.5,
                    "deferred_capex_usd": 6.0,
                }
                for conv in TRIAGE_RATING_CONVENTIONS
            },
        },
        "run": {
            "git_commit": "abc123",
            "started_at": "2026-09-07T00:00:00+00:00",
            "stage_filter": None,
            "partial_run": False,
            "artifact_fingerprints": "pending: recorded at run close",
        },
        "reports": {
            "aggregated": 2,
            "invalid": 0,
            "with_uncertainty": 1,
            "warnings": 7,
        },
    }
    text = render_markdown(summary, {"a_report.json": {}, "b_report.json": {}})
    for convention in TRIAGE_RATING_CONVENTIONS:
        assert f"`{convention}`" in text
    assert f"`{TRIAGE_HEADLINE_RATING_CONVENTION}` *(declared)*" in text
    # the two things a reader must not have to dig for
    assert "No uncertainty interval is carried on the primary result" in text
    assert "abc123" in text and "pending: recorded at run close" in text


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ────────────────

_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "study_report.json"
_MARKDOWN = PROJECT_OUTPUTS_DIR / "reports" / "study_report.md"
_SKIP = "study_report.json not present; run build_study_reports.py first"


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_study_report_contract() -> None:
    """It is a platform report, not hand-written JSON, and both files exist."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field in REQUIRED_REPORT_FIELDS:
        assert field in report, f"missing {field}"
    assert _MARKDOWN.is_file()


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_study_report_carries_both_conventions_and_the_run() -> None:
    """The summary must be quotable on its own: result, footing, provenance."""
    summary = json.loads(_REPORT.read_text())["summary"]
    fleet = summary["fleet_headline"]
    assert set(fleet["by_convention"]) == set(TRIAGE_RATING_CONVENTIONS)
    assert fleet["declared_convention"] in fleet["by_convention"]
    assert fleet["n_transformers"] > 0
    run = summary["run"]
    assert run["git_commit"] and run["started_at"]
    assert run["partial_run"] is False, "the report describes a partial run"
    assert summary["reports"]["aggregated"] >= 20


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_study_report_does_not_overclaim_its_attestation() -> None:
    """It runs inside the run it describes, and must say what that costs.

    The artifact fingerprints are recorded by the runner AFTER the last stage,
    so this report cannot attest that the outputs on disk are the ones the run
    produced. Claiming otherwise would be exactly the false assurance the
    2026-09 provenance work removed.
    """
    report = json.loads(_REPORT.read_text())
    assert report["summary"]["run"]["artifact_fingerprints"].startswith("pending")
    warnings = " ".join(report["validation"]["warnings"])
    assert "fingerprints" in warnings and "cannot attest" in warnings

"""The shared report tail: it must forward, never decide.

``emit_stage_report`` replaced eighteen hand-rolled copies of the same
``script.write_report`` call (bd qgr.5.1). A helper that quietly normalises what
those copies did would move the study's reports without moving a single number
in a stage, and the baselines would not catch it: they pin ``summary`` values,
not the report envelope around them.

So these tests assert the boring properties -- order preserved, records passed
through untouched, absent optionals stay absent -- because those are exactly the
ones a "harmless" future edit to the helper would break for all eighteen stages
at once.
"""

from __future__ import annotations

import pytest

from projects.ev_hosting_flex.scripts._report import emit_stage_report


class _RecordingScript:
    """A stand-in for ``ProjectScript`` that records the call it received."""

    def __init__(self) -> None:
        self.call: dict[str, object] = {}

    def file_reference(self, path: str) -> dict[str, object]:
        """Return a marker record so a converted path is distinguishable."""
        return {"path": path, "sha256": f"sha-of-{path}"}

    def write_report(self, report_id: str, **kwargs: object) -> dict[str, object]:
        """Record the report id and every keyword the helper forwarded."""
        self.call = {"report_id": report_id, **kwargs}
        return self.call


def test_artifact_order_survives_and_records_pass_through_untouched() -> None:
    """Order is load-bearing: the pins address artifacts positionally."""
    script = _RecordingScript()
    already = {"path": "outputs/json/from_another_stage.json", "sha256": "pinned"}
    derived = {
        "artifact_paths": ["outputs/json/a.json", already, "outputs/figures/b.pdf"],
        "summary": {"headline": 1.0},
    }

    emit_stage_report(script, "some_report", derived)

    artifacts = script.call["artifacts"]
    assert [a["path"] for a in artifacts] == [
        "outputs/json/a.json",
        "outputs/json/from_another_stage.json",
        "outputs/figures/b.pdf",
    ]
    # The dict entry is the SAME object, not a re-hashed copy: a stage handing on
    # another stage's reference must not have its digest recomputed here.
    assert artifacts[1] is already


def test_absent_warnings_become_an_empty_list_not_a_missing_key() -> None:
    """Every site this replaced wrote ``[]``; the helper must match them."""
    script = _RecordingScript()
    emit_stage_report(script, "r", {"artifact_paths": [], "summary": {}})
    assert script.call["validation"] == {"valid": True, "errors": [], "warnings": []}


def test_warnings_are_copied_so_a_caller_cannot_mutate_the_report() -> None:
    """The report is written from a snapshot of what the stage passed."""
    script = _RecordingScript()
    caveats = ["a lower bound"]
    emit_stage_report(
        script, "r", {"artifact_paths": [], "summary": {}}, warnings=caveats
    )
    caveats.append("added after the fact")
    assert script.call["validation"]["warnings"] == ["a lower bound"]


def test_optionals_stay_none_when_the_stage_does_not_pass_them() -> None:
    """``uncertainty`` is the caller's declaration, never inferred from derived.

    ``analyze_credibility`` is the one stage of eighteen that reports an
    interval. If the helper sniffed ``derived["uncertainty"]`` instead, adding
    that key anywhere else would silently start emitting an uncertainty block
    that the report contract then validates against the summary.
    """
    script = _RecordingScript()
    derived = {
        "artifact_paths": [],
        "summary": {},
        "uncertainty": {"headline": {"method": "mc"}},
    }

    emit_stage_report(script, "r", derived)

    assert script.call["uncertainty"] is None
    assert script.call["inputs"] is None


def test_a_derived_missing_its_contract_keys_fails_loudly() -> None:
    """A stage that forgot a key gets a named KeyError, not a silent empty report."""
    script = _RecordingScript()
    with pytest.raises(KeyError, match="artifact_paths"):
        emit_stage_report(script, "r", {"summary": {}})
    with pytest.raises(KeyError, match="summary"):
        emit_stage_report(script, "r", {"artifact_paths": []})

"""The report tail every governed analysis stage of this study shares.

Eighteen stages ended with the same seven lines: turn ``artifact_paths`` into
provenance records, pass ``summary`` through, and declare a valid run carrying a
warnings list. The uniformity was real -- every analysis stage here computes
``derived = derive_<x>(script)`` returning those two keys -- but it was copied
rather than shared, so a change to the artifact convention meant eighteen edits.

Measured 2026-09-08 (bd qgr.5.1): of 39 distinct six-line blocks duplicated
across three or more stages, this tail was the largest single cluster.

What this deliberately does NOT do
----------------------------------
It does not compute, validate, or infer. ``uncertainty`` is passed by the caller
rather than sniffed out of ``derived``, so a stage reporting an interval says so
at its own call site. A stage whose validation is not "valid, no errors" keeps
calling :meth:`ProjectScript.write_report` directly: that is a real difference
between stages, and defaulting it away would hide more than the duplication cost.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from gridalyn.projects.scripting import ProjectScript


def emit_stage_report(
    script: ProjectScript,
    report_id: str,
    derived: Mapping[str, Any],
    *,
    warnings: Sequence[str] | None = None,
    inputs: list[dict[str, Any]] | None = None,
    uncertainty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the platform report for a stage that derived paths and a summary.

    Artifact order is preserved exactly as ``derived["artifact_paths"]`` lists
    it, because :func:`file_reference` records ``bytes`` and ``sha256`` per
    entry and the report is compared byte for byte against a pinned baseline.
    Entries already in record form are passed through untouched, which is how a
    stage hands on a reference another stage produced.

    Args:
        script: The project workspace handle.
        report_id: Report identifier, also the report's file name.
        derived: The stage's own result, carrying ``artifact_paths`` (paths or
            already-built reference records) and ``summary``.
        warnings: Caveats the stage wants carried into ``validation``; omitted
            means none.
        inputs: Input provenance records, when the stage records any.
        uncertainty: Intervals qualifying entries of ``summary``, for a stage
            that samples a distribution it can defend.

    Returns:
        The written report payload.

    Raises:
        KeyError: If ``derived`` lacks ``artifact_paths`` or ``summary``.
    """
    return script.write_report(
        report_id,
        inputs=inputs,
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        uncertainty=uncertainty,
        validation={
            "valid": True,
            "errors": [],
            "warnings": list(warnings) if warnings is not None else [],
        },
    )

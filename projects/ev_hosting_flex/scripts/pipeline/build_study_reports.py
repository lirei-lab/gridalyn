"""Assemble the study-level report: what the run concluded, and on what footing.

From the 2026-06-22 scaffold until 2026-09-04 this stage was
``echo "STUB build_study_reports — canonical study report pending"``. It
completed in 0.0 s on every run and the manifest counted it, so the study
reported 23 of 23 stages while producing no study-level artifact (bd eei.9;
the stub was removed in 81c5c915). This is the stage it was standing in for.

WHAT THIS IS FOR. Every other stage answers one question and writes its own
report. Nothing said what the STUDY concluded, under which convention, with
what uncertainty, from which run — so a reader had to assemble that from 22
files and a manifest, and the two people who tried this month each assembled it
differently. This stage does it once, deterministically, through the report
contract.

READING REPORTS HERE IS THE LEGITIMATE CASE, and worth saying because
``bd eei.10`` just removed the illegitimate one. Three stages had been
taking a *data value* (``n_homes``) out of ``annual_mc_report.json``, coupling
themselves to a report's shape instead of to the artifact the number comes
from. Aggregating reports INTO a study report is the opposite: the reports are
being read as reports. A future reader should not "fix" this by re-pointing it
at the data.

WHAT IT DELIBERATELY DOES NOT CLAIM. It runs inside the run it describes, so
the manifest it reads is still ``running``: it can record the run's identity
(commit, start, whether a stage filter narrowed it) and the stages completed
before it, but not the run's end, and not the artifact fingerprints the runner
records at close (4b77004d). Those are stated as pending rather than guessed.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, cast

from gridalyn.projects.scripting import ProjectScript, project_script
from projects.ev_hosting_flex.scripts.config import (
    TRIAGE_ADOPTION_GRID,
    TRIAGE_BASE_DISPERSION,
    TRIAGE_DISPERSION_GRID,
    TRIAGE_HEADLINE_RATING_CONVENTION,
    TRIAGE_RATING_CONVENTIONS,
)

#: The adoption level the study quotes its fleet headline at (EV per home).
HEADLINE_ADOPTION = 1.0

#: Reports whose absence makes the study report meaningless rather than thin.
REQUIRED_REPORTS = (
    "fleet_triage_report.json",
    "annual_mc_report.json",
    "topology_cache_report.json",
)


def headline_index(convention: str) -> int:
    """Return where ``analyze_fleet_triage`` places a convention's headline cell.

    Mirrors that stage's construction order — convention-major, then
    dispersion, then adoption — rather than hardcoding an index, so a reordered
    or resized grid moves this with it.

    Args:
        convention: One of ``TRIAGE_RATING_CONVENTIONS``.

    Returns:
        The zero-based index into the emitted ``triage`` list.
    """
    conv = list(TRIAGE_RATING_CONVENTIONS).index(convention)
    disp = [float(x) for x in TRIAGE_DISPERSION_GRID].index(
        cast(float, TRIAGE_BASE_DISPERSION)
    )
    adopt = [float(x) for x in TRIAGE_ADOPTION_GRID].index(HEADLINE_ADOPTION)
    return (conv * len(TRIAGE_DISPERSION_GRID) + disp) * len(
        TRIAGE_ADOPTION_GRID
    ) + adopt


def fleet_headline(script: ProjectScript) -> dict[str, Any]:
    """Return the primary result under every evaluated rating convention.

    Both conventions, never only the declared one: they differ by 6.7x on the
    deferred fraction, and quoting one without the other is the positional
    accident ``bd eei.1`` removed.

    Args:
        script: The project workspace handle.

    Returns:
        Mapping with ``declared_convention``, ``n_transformers``, ``k_base``
        and a ``by_convention`` block carrying each convention's counts.

    Raises:
        ValueError: If a convention's headline cell is not where the config
            grids say it is — the artifact and the config disagree, and a
            silently wrong cell is worse than a stopped run.
    """
    payload = script.read_json("outputs/json/fleet_triage.json")
    triage = payload["triage"]
    by_convention: dict[str, Any] = {}
    for convention in TRIAGE_RATING_CONVENTIONS:
        cell = triage[headline_index(convention)]
        if cell["rating_convention"] != convention or cell[
            "adoption_ev_per_home"
        ] != float(HEADLINE_ADOPTION):
            raise ValueError(
                f"fleet_triage.json: the cell at the index the config grids give "
                f"for {convention!r} at {HEADLINE_ADOPTION} EV/home holds "
                f"{cell['rating_convention']!r} at "
                f"{cell['adoption_ev_per_home']} instead. Remediation: the "
                f"triage grids in config.py and the emitted artifact disagree; "
                f"re-run analyze_fleet_triage."
            )
        by_convention[convention] = {
            key: cell[key]
            for key in (
                "n_at_risk",
                "flex_defers",
                "needs_steel",
                "base_constrained",
                "never_binds",
                "deferred_fraction_of_at_risk",
                "deferred_capex_usd",
            )
        }
    return {
        "declared_convention": str(TRIAGE_HEADLINE_RATING_CONVENTION),
        "n_transformers": payload["n_transformers"],
        "k_base": payload["k_base"],
        "adoption_ev_per_home": HEADLINE_ADOPTION,
        "dispersion": cast(float, TRIAGE_BASE_DISPERSION),
        "by_convention": by_convention,
    }


def collect_reports(script: ProjectScript) -> dict[str, Any]:
    """Return every stage report's validity, warnings and uncertainty status.

    Args:
        script: The project workspace handle.

    Returns:
        Mapping of report file name to its ``valid``, error/warning counts and
        whether it carries an ``uncertainty`` block.

    Raises:
        FileNotFoundError: If a report in :data:`REQUIRED_REPORTS` is absent.
    """
    directory = script.reports_dir
    present = {path.name for path in directory.glob("*_report.json")}
    missing = [name for name in REQUIRED_REPORTS if name not in present]
    if missing:
        raise FileNotFoundError(
            f"{directory}: the study report needs {', '.join(missing)}, which "
            "no stage has written. Remediation: run the full workflow; this "
            "stage runs last for that reason."
        )
    collected: dict[str, Any] = {}
    for name in sorted(present):
        payload = json.loads((directory / name).read_text(encoding="utf-8"))
        validation = payload.get("validation") or {}
        collected[name] = {
            "valid": bool(validation.get("valid", True)),
            "errors": len(validation.get("errors") or []),
            "warnings": len(validation.get("warnings") or []),
            "uncertainty": "uncertainty" in payload,
        }
    return collected


def run_identity(script: ProjectScript) -> dict[str, Any]:
    """Return which run produced this, as far as it is knowable from inside it.

    Args:
        script: The project workspace handle.

    Returns:
        The run's commit, start, stage filter and completed-stage count, plus
        ``artifact_fingerprints`` — always ``"pending: recorded at run close"``,
        because the runner writes them after the last stage. Every field is
        ``None`` when no manifest exists (this stage run outside a workflow).
    """
    path = script.manifests_dir / "project_run_manifest.json"
    if not path.is_file():
        return {"manifest": None, "note": "no run manifest; stage run standalone"}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    stages = manifest.get("stages") or []
    return {
        "git_commit": manifest.get("git_commit"),
        "started_at": manifest.get("started_at"),
        "stage_filter": manifest.get("stage_filter"),
        "partial_run": bool(manifest.get("stage_filter")),
        "stages_completed_before_this": sum(
            1 for stage in stages if stage.get("status") == "completed"
        ),
        "artifact_fingerprints": "pending: recorded at run close",
    }


def render_markdown(summary: dict[str, Any], reports: dict[str, Any]) -> str:
    """Return the human-readable rendering of the study report.

    Args:
        summary: The payload written into the report's ``summary``.
        reports: The per-report collection from :func:`collect_reports`.

    Returns:
        Markdown text: the primary result under both conventions first, then
        what qualifies it, then the run it came from.
    """
    fleet = summary["fleet_headline"]
    run = summary["run"]
    lines = [
        "# ev_hosting_flex — study report",
        "",
        f"Fleet of **{fleet['n_transformers']}** pole transformers at "
        f"**{fleet['adoption_ev_per_home']} EV/home**, clustered adoption "
        f"dispersion {fleet['dispersion']}.",
        "",
        "## Primary result — fleet triage, under both rating conventions",
        "",
        "| Rating convention | At risk | Flexibility defers | Needs steel | "
        "Base-constrained | Deferred fraction |",
        "|---|---|---|---|---|---|",
    ]
    for convention, cell in fleet["by_convention"].items():
        mark = " *(declared)*" if convention == fleet["declared_convention"] else ""
        lines.append(
            f"| `{convention}`{mark} | {cell['n_at_risk']} | "
            f"{cell['flex_defers']} | {cell['needs_steel']} | "
            f"{cell['base_constrained']} | "
            f"{cell['deferred_fraction_of_at_risk']:.3f} |"
        )
    lines += [
        "",
        "Both conventions are reported because they disagree by roughly 6.7x on "
        "the deferred fraction; the study declares "
        f"`{fleet['declared_convention']}` and the other is not a correction to "
        "it but a different question about the same fleet.",
        "",
        "## What qualifies it",
        "",
        f"- Sampling depth of the triage medians: `k_base = {fleet['k_base']}`.",
        "- **No uncertainty interval is carried on the primary result, on "
        "purpose.** The allocation axis is characterised and independent; the "
        "base-MC axis at this `k_base` is uncharacterised and non-independent "
        "by construction (transformers of equal home count share a realization "
        "family). An interval is carried where it can be defended and is "
        "absent rather than faked where it cannot — see `CALIBRATION.md`.",
        f"- Stage reports aggregated: **{len(reports)}**, of which "
        f"**{summary['reports']['with_uncertainty']}** carry an uncertainty "
        f"block and **{summary['reports']['invalid']}** report themselves "
        "invalid.",
        f"- Stage warnings across the study: **{summary['reports']['warnings']}**. "
        "They are where each stage states its own limits; read them before "
        "quoting a number.",
        "",
        "## The run this came from",
        "",
        f"- commit `{run.get('git_commit')}`",
        f"- started `{run.get('started_at')}`",
        f"- partial run: **{run.get('partial_run')}**"
        + (f" (stages: {run['stage_filter']})" if run.get("stage_filter") else ""),
        f"- artifact fingerprints: {run.get('artifact_fingerprints')}",
        "",
        "Pinned values live in `baselines/results_baseline.json`; the gated "
        "headline table is in `CALIBRATION.md`. This document is generated — "
        "edit the stage, not the file.",
        "",
    ]
    return "\n".join(lines)


def derive_study_report(script: ProjectScript) -> dict[str, Any]:
    """Build the study report payload and write its markdown rendering.

    Args:
        script: The project workspace handle.

    Returns:
        Dict with ``summary``, ``validation`` and ``artifact_paths``.
    """
    reports = collect_reports(script)
    fleet = fleet_headline(script)
    run = run_identity(script)
    invalid = sorted(name for name, meta in reports.items() if not meta["valid"])
    summary = {
        "fleet_headline": fleet,
        "run": run,
        "reports": {
            "aggregated": len(reports),
            "invalid": len(invalid),
            "with_uncertainty": sum(1 for m in reports.values() if m["uncertainty"]),
            "warnings": sum(m["warnings"] for m in reports.values()),
            "by_report": reports,
        },
    }
    markdown = script.path("outputs/reports/study_report.md")
    markdown.write_text(render_markdown(summary, reports), encoding="utf-8")
    return {
        "summary": summary,
        "artifact_paths": [markdown],
        "validation": {
            "valid": not invalid,
            "errors": [f"{name} reports itself invalid" for name in invalid],
            "warnings": [
                "The primary result carries no uncertainty interval; the reason "
                "is recorded in CALIBRATION.md and is the base-MC axis, not an "
                "oversight.",
                "Artifact fingerprints are recorded by the runner AFTER this "
                "stage, so this report cannot attest that the outputs on disk "
                "are still the ones this run produced. Read the manifest's "
                "`artifacts` map, or `tools/stage_profile.py`, for that.",
            ],
        },
    }


def run_stage() -> dict[str, Any]:
    """Run the study-report stage and emit the platform report.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    script = project_script()
    derived = derive_study_report(script)
    return script.write_report(
        "study_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation=derived["validation"],
    )


def main() -> None:
    """CLI entry point for the study-report stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    fleet = report["summary"]["fleet_headline"]
    declared = fleet["by_convention"][fleet["declared_convention"]]
    print(
        f"Study report: {fleet['n_transformers']} transformers, "
        f"{len(report['summary']['reports']['by_report'])} stage reports; "
        f"headline ({fleet['declared_convention']}) "
        f"{declared['n_at_risk']} at risk, {declared['flex_defers']} deferred"
    )


if __name__ == "__main__":
    main()

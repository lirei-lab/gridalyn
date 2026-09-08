"""Per-stage wall-time profile of a governed study, read from its run manifest.

``gridalyn/projects/runner.py`` already records ``started_at``, ``ended_at``
and ``exit_code`` for every stage it runs. A completed run therefore *already*
carries its own profile — no instrumentation, no timing code, no second
execution. This tool reads that record and answers the only question that
decides whether parallelising the runner is worth anything: **is the time
spread across independent stages, or concentrated in one?**

It reports three things per study:

* the per-stage wall time and its share of the run;
* the wave each stage sits in, derived from the workflow's ``needs:`` edges
  (wave = longest dependency depth, i.e. the earliest wave a stage could run);
* the speedup a concurrent runner could actually reach *on the measured
  costs* — the critical path through the DAG weighted by real time, not the
  uniform-cost ``stages / waves`` figure, which assumes every stage costs the
  same and is therefore an upper bound nobody will observe.

**Staleness is reported, not assumed away.** A manifest describes the workflow
as it stood when the run happened. If stages have since been added, or the run
was a partial ``--stage`` invocation, the profile covers less than the current
contract and every derived figure is a lower bound. Both conditions are
detected and stated rather than silently folded into the totals.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Study directories live here; each holds ``workflow.yaml`` and, once it has
#: been run, ``outputs/manifests/project_run_manifest.json``.
PROJECTS_DIR = REPO_ROOT / "projects"

MANIFEST_RELATIVE = Path("outputs") / "manifests" / "project_run_manifest.json"


class ProfileUnavailableError(RuntimeError):
    """A study carries no run record this tool can profile."""


def load_declared_stages(project_dir: Path) -> dict[str, list[str]]:
    """Return the workflow's declared stages mapped to their dependencies.

    Args:
        project_dir: Study directory holding ``workflow.yaml``.

    Returns:
        Mapping of stage id to the list of stage ids it declares under
        ``needs:``. Insertion order follows the workflow file.

    Raises:
        ProfileUnavailableError: If the study declares no workflow file.
    """
    workflow_path = project_dir / "workflow.yaml"
    if not workflow_path.exists():
        raise ProfileUnavailableError(
            f"{project_dir}: no workflow.yaml "
            f"(not a governed study, or run from the wrong directory)"
        )
    document = yaml.safe_load(workflow_path.read_text())
    stages = document.get("spec", {}).get("stages") or []
    return {stage["id"]: list(stage.get("needs") or []) for stage in stages}


def load_run_manifest(project_dir: Path) -> dict[str, Any]:
    """Return the study's run manifest.

    Args:
        project_dir: Study directory whose ``outputs/`` holds the manifest.

    Returns:
        The parsed manifest payload.

    Raises:
        ProfileUnavailableError: If the study has never been run, so no
            manifest exists to profile.
    """
    manifest_path = project_dir / MANIFEST_RELATIVE
    if not manifest_path.exists():
        raise ProfileUnavailableError(
            f"{project_dir.name}: no run manifest at {MANIFEST_RELATIVE} — "
            f"run the study first (gridalyn project run {project_dir})"
        )
    return dict(json.loads(manifest_path.read_text()))


def assign_waves(dependencies: dict[str, list[str]]) -> dict[str, int]:
    """Return each stage's wave, the earliest step it could run at.

    A stage's wave is its longest dependency depth: wave 0 stages need
    nothing, and a stage sits one wave after the latest stage it needs. Stages
    sharing a wave are mutually independent and could run concurrently.

    Args:
        dependencies: Stage id mapped to the ids it declares under ``needs:``.

    Returns:
        Stage id mapped to its zero-based wave index.

    Raises:
        ValueError: If the declared edges contain a cycle, or name a stage
            that the workflow does not declare.
    """
    waves: dict[str, int] = {}
    resolving: set[str] = set()

    def depth(stage_id: str) -> int:
        if stage_id in waves:
            return waves[stage_id]
        if stage_id in resolving:
            raise ValueError(f"workflow contains a dependency cycle at {stage_id!r}")
        if stage_id not in dependencies:
            raise ValueError(
                f"stage {stage_id!r} is declared as a dependency but not as a stage "
                f"(declared stages: {', '.join(sorted(dependencies)) or 'none'})"
            )
        resolving.add(stage_id)
        parents = dependencies[stage_id]
        waves[stage_id] = 0 if not parents else 1 + max(depth(p) for p in parents)
        resolving.discard(stage_id)
        return waves[stage_id]

    for stage_id in dependencies:
        depth(stage_id)
    return waves


def _parse_timestamp(value: Any) -> datetime | None:
    """Return an ISO-8601 manifest timestamp as a datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def measure_stage_seconds(manifest: dict[str, Any]) -> dict[str, float | None]:
    """Return measured wall time per recorded stage.

    Args:
        manifest: The parsed run manifest.

    Returns:
        Stage id mapped to elapsed seconds, or ``None`` where the record
        carries no usable pair of timestamps (a dry run, or a stage that never
        started).
    """
    measured: dict[str, float | None] = {}
    for record in manifest.get("stages") or []:
        started = _parse_timestamp(record.get("started_at"))
        ended = _parse_timestamp(record.get("ended_at"))
        if started is None or ended is None:
            measured[str(record["id"])] = None
        else:
            measured[str(record["id"])] = (ended - started).total_seconds()
    return measured


def drifted_artifacts(
    manifest: dict[str, Any], project_dir: Path
) -> tuple[list[str], list[str], int]:
    """Return which recorded artifacts no longer match the run that recorded them.

    Args:
        manifest: A run manifest carrying an ``artifacts`` fingerprint map.
        project_dir: The study directory the manifest's paths are relative to.

    Returns:
        ``(changed, missing, total)`` -- paths whose current ``sha256`` differs
        from the recorded one, paths that no longer exist, and how many were
        recorded. All empty/zero when the manifest carries no fingerprints
        (runs recorded before 2026-09-04 do not).
    """
    import hashlib

    recorded = manifest.get("artifacts") or {}
    changed: list[str] = []
    missing: list[str] = []
    for rel, ref in sorted(recorded.items()):
        path = project_dir / rel
        if not path.is_file():
            missing.append(rel)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ref.get("sha256"):
            changed.append(rel)
    return changed, missing, len(recorded)


def compute_critical_path(
    dependencies: dict[str, list[str]], seconds: dict[str, float]
) -> tuple[float, list[str]]:
    """Return the measured critical path: its duration and the stages on it.

    This is the wall time a perfect scheduler with unlimited workers would
    reach — the real ceiling on any concurrency the runner could add, because
    no schedule can finish faster than its longest dependency chain.

    Args:
        dependencies: Stage id mapped to the ids it needs.
        seconds: Measured wall time per stage. Stages absent from this mapping
            are treated as costing nothing.

    Returns:
        Tuple of the path's total seconds and the stage ids along it, ordered
        from the first stage to the last.
    """
    finish: dict[str, float] = {}
    predecessor: dict[str, str | None] = {}

    def resolve(stage_id: str) -> float:
        if stage_id in finish:
            return finish[stage_id]
        best_parent: str | None = None
        best_start = 0.0
        for parent in dependencies.get(stage_id, []):
            parent_finish = resolve(parent)
            if parent_finish > best_start or best_parent is None:
                best_start, best_parent = parent_finish, parent
        predecessor[stage_id] = best_parent
        finish[stage_id] = best_start + seconds.get(stage_id, 0.0)
        return finish[stage_id]

    for stage_id in dependencies:
        resolve(stage_id)
    if not finish:
        return 0.0, []

    last = max(finish, key=lambda stage_id: finish[stage_id])
    path: list[str] = []
    cursor: str | None = last
    while cursor is not None:
        path.append(cursor)
        cursor = predecessor.get(cursor)
    return finish[last], list(reversed(path))


def simulate_wave_schedule(
    dependencies: dict[str, list[str]], seconds: dict[str, float], workers: int
) -> float:
    """Return the wall time a wave-barrier scheduler would reach at a cap.

    Models the scheduler this repository would most plausibly build: run each
    wave's stages concurrently, at most ``workers`` at once, and wait for the
    wave to drain before starting the next. Within a wave the stages are
    list-scheduled longest-first, which is what a pool does in practice.

    This is deliberately more pessimistic than :func:`compute_critical_path`:
    the barrier makes every wave cost at least its slowest stage even when a
    later stage's own dependencies were satisfied earlier.

    Args:
        dependencies: Stage id mapped to the ids it needs.
        seconds: Measured wall time per stage.
        workers: Maximum stages running at once. Values below 1 are treated
            as 1, which reproduces sequential execution.

    Returns:
        Total wall time in seconds.
    """
    capacity = max(1, workers)
    waves = assign_waves(dependencies)
    by_wave: dict[int, list[float]] = defaultdict(list)
    for stage_id, wave in waves.items():
        by_wave[wave].append(seconds.get(stage_id, 0.0))

    total = 0.0
    for wave in sorted(by_wave):
        busy = [0.0] * capacity
        for cost in sorted(by_wave[wave], reverse=True):
            busy[busy.index(min(busy))] += cost
        total += max(busy)
    return total


def profile_project(project_dir: Path, workers: int) -> dict[str, Any]:
    """Return the full profile of one study.

    Args:
        project_dir: Study directory.
        workers: Worker cap for the modelled wave schedule.

    Returns:
        A profile payload: run identity, coverage flags, per-stage rows, and
        the speedups the measured costs allow.

    Raises:
        ProfileUnavailableError: If the study has no workflow or no manifest.
    """
    dependencies = load_declared_stages(project_dir)
    manifest = load_run_manifest(project_dir)
    waves = assign_waves(dependencies)
    measured = measure_stage_seconds(manifest)

    timed = {
        stage_id: value
        for stage_id, value in measured.items()
        if value is not None and stage_id in dependencies
    }
    total = sum(timed.values())

    rows = [
        {
            "stage": stage_id,
            "wave": waves[stage_id],
            "seconds": timed.get(stage_id),
            "share_pct": (
                round(timed[stage_id] / total * 100.0, 2)
                if total > 0 and stage_id in timed
                else None
            ),
            "recorded": stage_id in measured,
        }
        for stage_id in sorted(dependencies, key=lambda s: (waves[s], s))
    ]

    missing = sorted(set(dependencies) - set(measured))
    changed_files, missing_files, recorded_files = drifted_artifacts(
        manifest, project_dir
    )
    critical_seconds, critical_path = compute_critical_path(dependencies, timed)
    wave_seconds = simulate_wave_schedule(dependencies, timed, workers)

    return {
        "project": project_dir.name,
        "run": {
            "status": manifest.get("status"),
            "git_commit": manifest.get("git_commit"),
            "started_at": manifest.get("started_at"),
            "ended_at": manifest.get("ended_at"),
            "stage_filter": manifest.get("stage_filter"),
            "partial_runs_since": manifest.get("partial_runs_since") or [],
        },
        "coverage": {
            "declared_stages": len(dependencies),
            "recorded_stages": len(measured),
            "timed_stages": len(timed),
            "missing_stages": missing,
            "partial_run": bool(manifest.get("stage_filter")),
            "stale_manifest": bool(missing) and not manifest.get("stage_filter"),
            "complete": not missing,
            "artifacts_recorded": recorded_files,
            "artifacts_changed": changed_files,
            "artifacts_missing": missing_files,
        },
        "waves": {
            "count": (max(waves.values()) + 1) if waves else 0,
            "max_width": (
                max(
                    sum(1 for depth in waves.values() if depth == wave)
                    for wave in set(waves.values())
                )
                if waves
                else 0
            ),
        },
        "stages": rows,
        "totals": {
            "sequential_seconds": round(total, 3),
            "critical_path_seconds": round(critical_seconds, 3),
            "critical_path": critical_path,
            "wave_schedule_seconds": round(wave_seconds, 3),
            "workers": max(1, workers),
            "ceiling_speedup": (
                round(total / critical_seconds, 3) if critical_seconds > 0 else None
            ),
            "wave_speedup": (
                round(total / wave_seconds, 3) if wave_seconds > 0 else None
            ),
            "uniform_cost_speedup": (
                round(len(dependencies) / (max(waves.values()) + 1), 3)
                if waves
                else None
            ),
        },
    }


def _format_duration(seconds: float | None) -> str:
    """Return a compact human duration for a measured stage cost."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m{remainder:04.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h{minutes:02d}m"


def format_profile(profile: dict[str, Any]) -> str:
    """Return the human-readable rendering of one study's profile.

    Args:
        profile: A payload from :func:`profile_project`.

    Returns:
        A multi-line report: coverage caveats first, then the per-stage table,
        then the speedups the measured costs allow.
    """
    coverage = profile["coverage"]
    totals = profile["totals"]
    lines = [
        f"{profile['project']}  —  {coverage['timed_stages']}/"
        f"{coverage['declared_stages']} stages timed, "
        f"{profile['waves']['count']} waves, max width "
        f"{profile['waves']['max_width']}",
        f"  run {profile['run']['started_at']}  status={profile['run']['status']}"
        f"  commit={(profile['run']['git_commit'] or 'none')[:12]}",
    ]
    if coverage["partial_run"]:
        lines.append(
            f"  PARTIAL RUN — manifest records a --stage filter "
            f"({', '.join(profile['run']['stage_filter'])}); every figure below "
            f"covers only those stages."
        )
    if coverage["artifacts_changed"] or coverage["artifacts_missing"]:
        n_changed = len(coverage["artifacts_changed"])
        n_missing = len(coverage["artifacts_missing"])
        first = (coverage["artifacts_changed"] or coverage["artifacts_missing"])[0]
        lines.append(
            f"  ARTIFACTS DRIFTED — {n_changed} changed and {n_missing} missing of "
            f"{coverage['artifacts_recorded']} files this run fingerprinted at "
            f"close (first: {first}); the outputs on disk are no longer the set "
            f"this manifest describes."
        )
    since = profile["run"].get("partial_runs_since") or []
    if since:
        rewritten = sorted({st for run in since for st in run.get("stages", [])})
        lines.append(
            f"  PARTIAL RUNS SINCE — {len(since)} --stage run(s) rewrote "
            f"{len(rewritten)} stage(s)' artifacts after this run "
            f"({', '.join(rewritten)}); the timings below are this run's, the "
            f"artifacts on disk for those stages may not be."
        )
    if coverage["stale_manifest"]:
        lines.append(
            f"  STALE MANIFEST — the run claims no --stage filter, yet the "
            f"workflow declares stages it never recorded "
            f"({', '.join(coverage['missing_stages'])}). The workflow changed "
            f"after this run; figures below are a lower bound."
        )
    lines.append("")
    lines.append(f"  {'wave':>4}  {'stage':<40} {'time':>10} {'share':>7}")
    for row in profile["stages"]:
        share = "—" if row["share_pct"] is None else f"{row['share_pct']:.1f}%"
        lines.append(
            f"  {row['wave']:>4}  {row['stage']:<40} "
            f"{_format_duration(row['seconds']):>10} {share:>7}"
        )
    lines.append("")
    sequential = _format_duration(totals["sequential_seconds"])
    lines.append(f"  sequential (measured)   {sequential}")
    lines.append(
        f"  critical path           "
        f"{_format_duration(totals['critical_path_seconds'])}"
        f"   ceiling {totals['ceiling_speedup']}x  (unlimited workers)"
    )
    lines.append(
        f"  wave schedule @{totals['workers']:<2}      "
        f"{_format_duration(totals['wave_schedule_seconds'])}"
        f"   {totals['wave_speedup']}x  (wave barrier)"
    )
    lines.append(
        f"  uniform-cost estimate   {totals['uniform_cost_speedup']}x"
        f"   — what the DAG shape alone suggests, if every stage cost the same"
    )
    if totals["critical_path"]:
        chain = " -> ".join(totals["critical_path"])
        lines.append(f"  on the critical path:   {chain}")
    return "\n".join(lines)


def _discover_projects(names: list[str]) -> list[Path]:
    """Return the study directories to profile, defaulting to all of them."""
    if names:
        return [
            Path(name) if Path(name).is_dir() else PROJECTS_DIR / name for name in names
        ]
    return sorted(p for p in PROJECTS_DIR.iterdir() if (p / "workflow.yaml").exists())


def main(argv: list[str] | None = None) -> int:
    """Profile one or more studies from their run manifests.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 when at least one study was profiled, 1 when
        none could be.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "projects",
        nargs="*",
        help="study names or directories (default: every study under projects/)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="worker cap for the modelled wave schedule (default: 4)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write the machine-readable profiles to this path",
    )
    args = parser.parse_args(argv)

    profiles: list[dict[str, Any]] = []
    for project_dir in _discover_projects(args.projects):
        try:
            profiles.append(profile_project(project_dir, args.workers))
        except ProfileUnavailableError as error:
            print(f"skipped: {error}", file=sys.stderr)
            continue

    for profile in profiles:
        print(format_profile(profile))
        print()

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(profiles, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.json}", file=sys.stderr)

    return 0 if profiles else 1


if __name__ == "__main__":
    raise SystemExit(main())

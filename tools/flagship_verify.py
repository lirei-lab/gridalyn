"""Shape-covering verification subset for the flagship ``ev_hosting_flex`` study.

The flagship study's reproduce-and-pin tests pass against a cached tree, but a
full source regeneration takes hours across 23 stages. This tool makes that
verification *source-proven by protocol*: it runs the pipeline's non-heavy
stages end to end (the "shape" of the pipeline), records a per-stage result for
every stage — run, skipped, or failed — and reports the R7 baseline check. The
stages measured to dominate a cold run are skipped by default with a recorded
reason; pass ``--include-heavy`` for the full operator-scheduled regeneration.

**The heavy set is measured, not assumed.** Until 2026-09-04 it was
``{generate_annual_mc}`` on the belief that the annual Monte-Carlo base took
hours. It takes five minutes, and because every analysis stage depends on it,
skipping it skipped 20 of 23 stages: the "shape-covering subset" ran three
setup stages in a tenth of a minute. The set below is the four stages a clean
23-stage run timed above ten minutes; with them skipped the subset runs 16 of
23 stages in about 24 minutes (syntgrid-zpz).

Per-stage records are the payload for a verification-receipt entry's optional
``stages`` field (see ``docs/development/verification-receipts.json``), so a
partial regeneration is auditable.

**What it is not.** A substitute for running the full study in CI. The heavy
stage is exactly the work CI cannot host, and its results are recorded in the
receipt ledger rather than fabricated here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: Stages that dominate a cold full regeneration, from the first clean
#: 23-stage run (2026-09-04, seconds): analyze_congestion_risk 4556 — it
#: generates the shared base-MC cache, ~25 s when that cache is warm —
#: analyze_credibility 3141 and analyze_cold_insurance 3013 (K=50 each),
#: analyze_voltage_risk_network 1068. Everything else is under seven minutes;
#: generate_annual_mc, the previous sole member, is 295. Skipped by the
#: shape-covering subset unless ``--include-heavy`` is passed. Because
#: congestion_risk is here, the three stages that need it — fleet_triage,
#: nonwires_value, locational_contracts, the study's primary-result chain —
#: are skipped by dependency; a warm-cache tier that runs them when
#: base_mc_by_size.npz already matches is the natural follow-up.
HEAVY_STAGES: frozenset[str] = frozenset(
    {
        "analyze_congestion_risk",
        "analyze_credibility",
        "analyze_cold_insurance",
        "analyze_voltage_risk_network",
    }
)

#: Workflow contract, read-only, relative to the workspace root.
WORKFLOW_PATH = "projects/ev_hosting_flex/workflow.yaml"


class FlagshipSubsetError(RuntimeError):
    """A non-heavy subset stage failed.

    Carries the per-stage records collected up to (and including) the failing
    stage, so the audit trail survives the failure and can be persisted by the
    CLI even when the run aborts.

    Attributes:
        records: Per-stage records collected before the failure.
    """

    def __init__(self, message: str, records: list[dict[str, Any]]) -> None:
        # Both args go to super() so ``args`` round-trips through copy/pickle;
        # __str__ keeps the human message rather than the args tuple.
        super().__init__(message, records)
        self.records = records

    def __str__(self) -> str:
        """Return the human-readable message, not the ``args`` tuple."""
        return str(self.args[0])


def load_stages(workspace: Path) -> list[dict[str, Any]]:
    """Read the flagship workflow's stage list from its YAML contract.

    Args:
        workspace: Repository root containing ``projects/ev_hosting_flex``.

    Returns:
        The ``spec.stages`` list as parsed from ``workflow.yaml``.

    Raises:
        FileNotFoundError: If the workflow contract is missing, naming it.
    """
    import yaml

    path = workspace / WORKFLOW_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path}: flagship workflow.yaml not found; run from the "
            "repository root (or pass --workspace)"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    stages = data.get("spec", {}).get("stages", [])
    if not stages:
        raise ValueError(f"{path}: spec.stages is empty or missing")
    return list(stages)


def topo_sort(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order stages so every ``needs`` dependency comes first.

    Args:
        stages: Raw stage list from the workflow contract.

    Returns:
        Dependency-ordered stage list.

    Raises:
        RuntimeError: On a dependency cycle, naming the stuck stages.
    """
    remaining = list(stages)
    ordered: list[dict[str, Any]] = []
    while remaining:
        done = {s["id"] for s in ordered}
        progressed = False
        for stage in list(remaining):
            if set(stage.get("needs") or []) <= done:
                ordered.append(stage)
                remaining.remove(stage)
                progressed = True
        if not progressed:
            stuck = ", ".join(s["id"] for s in remaining)
            raise RuntimeError(
                f"cycle in flagship workflow dependencies; cannot order: {stuck}"
            )
    return ordered


def _command(stage: dict[str, Any]) -> str:
    """Return the stage command with ``{python}`` resolved to this interpreter."""
    return str(stage["command"]).replace("{python}", sys.executable)


def classify_runs(
    stages: list[dict[str, Any]], *, include_heavy: bool = False
) -> list[tuple[dict[str, Any], str, str | None]]:
    """Decide, per topo-sorted stage, whether it runs, is skipped, and why.

    Args:
        stages: Topo-sorted stage list.
        include_heavy: When True, heavy stages run; otherwise they are skipped.

    Returns:
        A list of ``(stage, action, reason)`` triples where action is one of
        ``"run"``, ``"skipped"``, with a non-empty reason for skipped stages.
    """
    decided: list[tuple[dict[str, Any], str, str | None]] = []
    ran: set[str] = set()
    for stage in stages:
        sid = stage["id"]
        if sid in HEAVY_STAGES and not include_heavy:
            decided.append((stage, "skipped", "heavy — requires operator full regen"))
            continue
        missing = [need for need in (stage.get("needs") or []) if need not in ran]
        if missing:
            decided.append(
                (stage, "skipped", f"depends on skipped stage {', '.join(missing)}")
            )
            continue
        decided.append((stage, "run", None))
        ran.add(sid)
    return decided


def _run_stage(stage: dict[str, Any], workspace: Path) -> tuple[int, float]:
    """Execute one stage command in the workspace, returning exit code + seconds."""
    started = time.monotonic()
    completed = subprocess.run(_command(stage), cwd=workspace, shell=True, check=False)
    return completed.returncode, time.monotonic() - started


def check_baselines(workspace: Path) -> tuple[str, str]:
    """Run the R7 baseline regression and report PASS or WARNING.

    Args:
        workspace: Repository root.

    Returns:
        A ``(status, detail)`` pair — status is ``"PASS"`` or ``"WARNING"``.
        WARNING means the regression could not be compared (study outputs are
        absent locally); it never fails the tool.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridalyn.interfaces.cli.project",
            "regression",
            "projects/ev_hosting_flex",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return "PASS", "baselines byte-identical"
    return "WARNING", (
        "regression could not be compared (exit "
        f"{completed.returncode}); study outputs may be absent — see "
        "docs/development/verification.md"
    )


def run_subset(
    workspace: Path,
    *,
    include_heavy: bool = False,
    dry_run: bool = False,
    run_baselines_check: bool = True,
) -> dict[str, Any]:
    """Execute (or describe) the shape-covering subset.

    Args:
        workspace: Repository root.
        include_heavy: Run the heavy annual-MC stage too.
        dry_run: Describe run/skip decisions without executing anything.
        run_baselines_check: Run the R7 regression check after a real run.

    Returns:
        A result mapping with ``stages`` (per-stage records), ``baselines``
        and ``exit_code``.

    Raises:
        RuntimeError: On the first non-heavy stage that fails (fail loud).
    """
    stages = topo_sort(load_stages(workspace))
    decisions = classify_runs(stages, include_heavy=include_heavy)
    records: list[dict[str, Any]] = []
    exit_code = 0
    for stage, action, reason in decisions:
        if action == "skipped":
            records.append(
                {
                    "name": stage["id"],
                    "status": "skipped",
                    "duration_s": None,
                    "reason": reason,
                }
            )
            continue
        if dry_run:
            records.append(
                {
                    "name": stage["id"],
                    "status": "run",
                    "duration_s": None,
                    "reason": None,
                }
            )
            continue
        returncode, seconds = _run_stage(stage, workspace)
        records.append(
            {
                "name": stage["id"],
                "status": "ok" if returncode == 0 else "failed",
                "duration_s": round(seconds, 2),
                "reason": None,
            }
        )
        if returncode != 0:
            raise FlagshipSubsetError(
                f"flagship subset stage failed: {stage['id']} ({returncode})",
                records,
            )

    baselines = None
    if run_baselines_check and not dry_run:
        status, detail = check_baselines(workspace)
        baselines = {"status": status, "detail": detail}
    return {
        "stages": records,
        "baselines": baselines,
        "exit_code": exit_code,
    }


def _format_table(result: dict[str, Any]) -> str:
    lines = ["| Stage | Status | Duration | Reason |", "|---|---|---|---|"]
    for record in result["stages"]:
        duration = (
            f"{record['duration_s']}s" if record["duration_s"] is not None else "—"
        )
        lines.append(
            f"| {record['name']} | {record['status']} | {duration} | "
            f"{record['reason'] or ''} |"
        )
    if result["baselines"]:
        b = result["baselines"]
        lines.append("")
        lines.append(f"Baselines: {b['status']} — {b['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the shape-covering subset or describe it.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        0 on success or description; 1 on a failed stage; 2 on usage error.
    """
    parser = argparse.ArgumentParser(
        description="Shape-covering verification subset for the flagship study."
    )
    parser.add_argument("--list-stages", action="store_true", help="list stages")
    parser.add_argument("--dry-run", action="store_true", help="describe, don't run")
    parser.add_argument(
        "--include-heavy", action="store_true", help="run the ~6 h annual-MC stage"
    )
    parser.add_argument("--out-json", type=Path, help="write per-stage records here")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="repo root")
    parser.add_argument(
        "--no-check-baselines",
        action="store_true",
        help="skip the R7 regression check",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    if args.list_stages:
        stages = topo_sort(load_stages(workspace))
        for stage in stages:
            flag = "heavy" if stage["id"] in HEAVY_STAGES else ""
            needs = ",".join(stage.get("needs") or [])
            print(f"{stage['id']}\t{flag}\t{needs}")
        return 0

    try:
        result = run_subset(
            workspace,
            include_heavy=args.include_heavy,
            dry_run=args.dry_run,
            run_baselines_check=not args.no_check_baselines,
        )
    except FlagshipSubsetError as exc:
        # Fail loud, but persist the audit trail: the per-stage records up to
        # (and including) the failing stage are still written and reported.
        result = {
            "stages": exc.records,
            "baselines": None,
            "exit_code": 1,
            "error": str(exc),
        }
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(_format_table(result))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

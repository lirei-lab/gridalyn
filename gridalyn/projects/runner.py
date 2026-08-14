from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.governance import build_study_run
from gridalyn.foundation.platform.reports import file_reference
from gridalyn.projects.models import StudyProject, WorkflowStage

# SINGLE canonical source for the clearing-engine name recorded in run
# provenance (REPRO-04). Clearing runs on the two-stage ``engine_mode``
# (MarketSimulationEngine) path. This is the only source-literal occurrence of
# the token; the provenance test imports THIS constant (never a duplicated
# literal).
CLEARING_ENGINE_NAME = "engine_mode"

# The canonical baseline-authoring clearing-mode set, derived from the real
# submodule names under ``gridalyn.operations.clearing`` (``allocation`` is the
# spatial helper, not a baseline-authoring mode). Deriving the set — rather than
# re-stating the literals — anchors ``CLEARING_ENGINE_NAME`` to a real mode so it
# can never silently drift to a non-mode string, without duplicating the token.
_CLEARING_MODES = {CLEARING_ENGINE_NAME, "selection"}
assert CLEARING_ENGINE_NAME in _CLEARING_MODES

# Numeric stack actually on the clearing path; recorded as a version sub-mapping
# so a moved dependency is auditable. pandapower is an optional capability, so
# each lookup is guarded and records ``None`` when the package is absent.
_CLEARING_STACK = ("numpy", "scipy", "pandapower")

# Committed, pinned study inputs whose integrity is recorded in the run
# manifest. Resolved relative to ``project.root``; only existing files are
# hashed (a missing optional input is simply absent, never an error).
_PINNED_INPUTS = {
    "tmy_csv": Path("inputs") / "tmy_trois_rivieres.csv",
    "regression_baseline": Path("baselines") / "results_baseline.json",
}


def plan_stages(project: StudyProject) -> list[WorkflowStage]:
    stages = {stage.id: stage for stage in project.workflow.stages}
    indegree = {stage_id: 0 for stage_id in stages}
    children: dict[str, list[str]] = defaultdict(list)
    for stage in project.workflow.stages:
        for dependency in stage.needs:
            children[dependency].append(stage.id)
            indegree[stage.id] += 1

    ready = deque(stage_id for stage_id, count in indegree.items() if count == 0)
    ordered: list[WorkflowStage] = []
    while ready:
        stage_id = ready.popleft()
        ordered.append(stages[stage_id])
        for child in children[stage_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered) != len(stages):
        raise ValueError("workflow contains a dependency cycle")
    return ordered


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _clearing_stack_versions() -> dict[str, str | None]:
    """Return installed versions of the numeric stack on the clearing path.

    Each lookup is guarded so a missing optional capability (e.g. pandapower)
    records ``None`` rather than raising — pandapower is an optional capability.
    """
    versions: dict[str, str | None] = {}
    for name in _CLEARING_STACK:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _resolve_seeds(
    project: StudyProject, planned: list[WorkflowStage]
) -> dict[str, Any]:
    """Record the RNG seed base the study declares (REPRO-04).

    Records the declared base and says whether it was declared -- nothing more.
    That restraint is the point, and it is a correction: this function used to
    derive a per-stage ``{stage_id: seed + index}`` map from the base and the
    planned stage order. No study seeds that way. ``ev_hosting_flex`` uses a
    single ``SEED = 42`` with named offsets (``OOS_SEED_OFFSET``,
    ``ADV_SEED_OFFSET``, ``DHW_SEED_SALT``), and the per-realization ``SEED + r``
    draws live inside the stage scripts, which run as separate subprocesses and
    are genuinely unreachable from this generic runner. A map keyed by stage ID
    would therefore have asserted a derivation the stages do not perform --
    provenance that is false rather than absent, which is strictly worse in a
    repository whose baselines are the product.

    The map was also unreachable in practice until 2026-08-14: the study schema
    declared ``spec.additionalProperties: false`` without listing ``simulation``,
    so a study that declared the key failed validation, and all eight manifests
    on disk recorded ``{"base": null}``.

    Args:
        project: The loaded study, read for ``spec.simulation.seed`` (or its
            ``seed_base`` alias).
        planned: The topologically ordered stages. Accepted so the recorded
            payload can state how many stages the base covers, never to derive
            a per-stage seed from the ordering.

    Returns:
        ``base`` (the declared integer, or ``None``), ``declared`` (whether the
        study named one) and ``stage_count``. A stage that needs a distinct
        stream derives it from ``base`` itself and records that in its own
        report; the runner does not guess on its behalf.
    """
    spec = project.raw.get("spec", {}) if isinstance(project.raw, dict) else {}
    simulation = spec.get("simulation", {}) if isinstance(spec, dict) else {}
    seed_base = simulation.get("seed")
    if seed_base is None:
        seed_base = simulation.get("seed_base")
    declared = isinstance(seed_base, int)
    return {
        "base": seed_base if declared else None,
        "declared": declared,
        "stage_count": len(planned),
    }


def _input_hashes(project: StudyProject) -> dict[str, dict[str, Any]]:
    """Return ``file_reference`` records for the committed, pinned study inputs.

    Reuses :func:`file_reference` (path + bytes + sha256, repo-relative) — never
    a hand-rolled digest loop — and only records inputs that exist on disk.
    """
    records: dict[str, dict[str, Any]] = {}
    for name, relative in _PINNED_INPUTS.items():
        path = project.root / relative
        if path.is_file():
            records[name] = file_reference(path, root=project.root)
    return records


def _macro_model_provenance() -> dict[str, Any]:
    """Which macro model the load generator would use for this run.

    The packaged LightGBM weights and the analytical fallback produce different
    load profiles from the same seed, and the fallback only warns before exiting
    0 -- so a degraded run was previously indistinguishable from a good one in
    every governed artifact. This records the deciding conditions rather than
    the warning, so a manifest is enough to tell which model produced the run.

    Side-effect-free: it inspects file existence and importability, and never
    constructs the generator or draws from any RNG.
    """
    from gridalyn.assets.datagen import load_profiles

    weights_dir = Path(load_profiles.__file__).parent / "models" / "weights"
    weights = {
        name: (weights_dir / f"{name}.pkl").is_file()
        for name in ("lgbm_heating_macro", "lgbm_bg_macro")
    }
    runtime = importlib.util.find_spec("lightgbm") is not None
    trained = runtime and all(weights.values())
    return {
        "expected": "lgbm" if trained else "analytical",
        "lightgbm_runtime": runtime,
        "packaged_weights": weights,
    }


def _powerflow_backend_provenance(project: StudyProject) -> dict[str, Any]:
    """Which power-flow backend the stages of this run solve through.

    Before the backend contract existed, eleven call sites solved power flow
    with three different effective configurations and none of them reached the
    manifest -- so a run solved through lightsim2grid and a run solved through
    pandapower's own Newton-Raphson were indistinguishable in every governed
    artifact.

    This records the backend the study DECLARES in
    ``spec.simulation.powerflowBackend``, not merely the registry default, and
    ``declared_source`` says which of the two the value came from. The
    distinction matters: recording the default while a stage solved with
    something else is the failure this function exists to prevent, and it was
    the live state of the repository until the study stages were routed through
    ``ProjectScript.powerflow_backend``.

    Backends resolve by explicit ID only: there is no ``entry_points``
    discovery, so this list is exactly what the repository registers.

    Side-effect-free, following ``_macro_model_provenance``: it reads
    descriptors and checks importability, and never constructs a backend,
    never solves, and never draws from any RNG.

    Args:
        project: The loaded study, read for its declared backend ID.

    Returns:
        The declared backend's descriptor fields, where the declaration came
        from, the registered IDs, and an availability flag per backend.
    """
    from gridalyn.foundation.platform.capabilities import missing_capability_modules
    from gridalyn.projects.model_inputs import load_powerflow_backend_id
    from gridalyn.simulation.backends.contract import DEFAULT_POWERFLOW_BACKEND_ID
    from gridalyn.simulation.backends.registry import default_powerflow_backend_registry

    registry = default_powerflow_backend_registry()
    descriptors = registry.list_descriptors()
    available = {
        descriptor.backend_id: (
            not missing_capability_modules(descriptor.capability)
            if descriptor.capability
            else True
        )
        for descriptor in descriptors
    }
    backend_id = load_powerflow_backend_id(project)
    provenance = registry.get_descriptor(backend_id).as_dict()
    provenance["declared_source"] = (
        "spec.simulation.powerflowBackend"
        if backend_id != DEFAULT_POWERFLOW_BACKEND_ID
        or _declares_powerflow_backend(project)
        else "registry default (study declares none)"
    )
    provenance["registered"] = [descriptor.backend_id for descriptor in descriptors]
    provenance["available"] = available
    return provenance


def _declares_powerflow_backend(project: StudyProject) -> bool:
    """Report whether the study declares a backend rather than inheriting one.

    Args:
        project: The loaded study.

    Returns:
        True when ``spec.simulation.powerflowBackend`` is present, so a study
        that names the default explicitly is distinguishable in provenance from
        one that names nothing.
    """
    spec = project.raw.get("spec", {}) if isinstance(project.raw, dict) else {}
    simulation = spec.get("simulation", {}) if isinstance(spec, dict) else {}
    return isinstance(simulation, dict) and "powerflowBackend" in simulation


def _build_provenance(
    project: StudyProject, planned: list[WorkflowStage]
) -> dict[str, Any]:
    """Assemble the additive run-provenance block (REPRO-04).

    Side-effect-free and move-only: no RNG draw, no sort, no numeric path is
    touched, so the regression baseline cannot move.
    """
    return {
        "python_version": sys.version.split()[0],
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "clearing_engine": {
            "name": CLEARING_ENGINE_NAME,
            "version": _clearing_stack_versions(),
        },
        "seeds": _resolve_seeds(project, planned),
        "macro_model": _macro_model_provenance(),
        "powerflow_backend": _powerflow_backend_provenance(project),
        "input_hashes": _input_hashes(project),
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def default_manifest_path(project: StudyProject) -> Path:
    return project.root / "outputs" / "manifests" / "project_run_manifest.json"


def select_stages(project: StudyProject, requested: list[str]) -> list[WorkflowStage]:
    """Return requested stages plus their transitive dependencies, in run order."""
    stages = {stage.id: stage for stage in project.workflow.stages}
    unknown = sorted(set(requested) - set(stages))
    if unknown:
        available = ", ".join(sorted(stages))
        raise ValueError(
            f"unknown workflow stage(s): {', '.join(unknown)} (available: {available})"
        )
    selected: set[str] = set()
    pending = list(requested)
    while pending:
        stage_id = pending.pop()
        if stage_id in selected:
            continue
        selected.add(stage_id)
        pending.extend(stages[stage_id].needs)
    return [stage for stage in plan_stages(project) if stage.id in selected]


def _echo(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# The token a workflow declares to mean "the interpreter running this study".
# Stage commands go through ``shell=True``, where a bare ``python`` resolves
# against ``PATH`` — and on a venv or a ``python3``-only system there is no such
# executable, so every stage dies with exit 127. Workflows declare
# ``{python}`` instead and the runner substitutes ``sys.executable``.
_INTERPRETER_PLACEHOLDER = "{python}"

# The bare token rewritten by the compatibility fallback, for workflows
# authored before the placeholder existed (including the ones ``templates.py``
# still generates and any user-authored contract).
_BARE_INTERPRETER_TOKEN = "python"


def _resolve_interpreter(command: str) -> str:
    """Bind a stage command to the interpreter running this process.

    Two independent mechanisms, in precedence order:

    1. *Explicit form* — every occurrence of ``{python}`` is replaced with
       :data:`sys.executable`.
    2. *Fallback form* — otherwise, if the command's **leading** whitespace
       delimited token is exactly ``python``, that one token is replaced. A
       ``python`` appearing later (as an argument, inside a path such as
       ``scripts/python_helper.py``, or after a launcher such as ``uv run``) is
       never touched.

    The two mechanisms are mutually exclusive by construction: a command
    carrying the placeholder never reaches the fallback, and the fallback never
    inspects the placeholder. Neither can mask a defect in the other.

    Args:
        command: The stage command exactly as the workflow contract declares it.

    Returns:
        The command with the interpreter bound, or the input unchanged when
        neither mechanism applies.
    """
    # ``shell=True`` re-parses the string, and ``sys.executable`` may contain
    # spaces (e.g. a venv under "Application Support"), so it must be quoted.
    interpreter = shlex.quote(sys.executable)

    if _INTERPRETER_PLACEHOLDER in command:
        return command.replace(_INTERPRETER_PLACEHOLDER, interpreter)

    stripped = command.lstrip()
    leading_whitespace = command[: len(command) - len(stripped)]
    head = stripped.split(None, 1)
    if head and head[0] == _BARE_INTERPRETER_TOKEN:
        # Slice rather than re-join so the original inter-token spacing and any
        # trailing whitespace survive verbatim.
        remainder = stripped[len(_BARE_INTERPRETER_TOKEN) :]
        return f"{leading_whitespace}{interpreter}{remainder}"

    return command


def _execute_stage(
    stage: WorkflowStage,
    record: dict[str, Any],
    *,
    project: StudyProject,
    index: int,
    total: int,
    output_path: Path,
    echo: bool,
) -> None:
    """Run one stage as a subprocess and record its outcome into ``record``.

    Deliberately does not touch the run-level manifest status. On failure it
    raises, and ``run_project``'s ``except`` clause promotes the run from
    ``running`` to ``failed`` -- which is what it already did for every other
    exception, so the single-stage path and the unexpected-error path now agree
    instead of setting the same field from two places.

    Args:
        stage: The workflow stage to run.
        record: The stage's manifest entry, mutated in place.
        project: The owning project, supplying the subprocess working directory.
        index: 1-based position of this stage, for progress output.
        total: Number of stages planned, for progress output.
        output_path: Manifest location, echoed on failure so it can be inspected.
        echo: Whether to write progress lines to stderr.

    Raises:
        subprocess.CalledProcessError: If the stage exits non-zero.
    """
    if echo:
        _echo(f"[{index}/{total}] {stage.id}: {stage.command}")
    stage_started = time.monotonic()
    # The manifest and the echoed lines keep ``stage.command`` verbatim, so a
    # run record still shows what the contract declared; only the string handed
    # to the shell is interpreter-bound.
    result = subprocess.run(
        _resolve_interpreter(stage.command),
        cwd=project.base_dir,
        shell=True,
        check=False,
    )
    elapsed = time.monotonic() - stage_started
    record["ended_at"] = _utc_now()
    record["exit_code"] = result.returncode
    if result.returncode != 0:
        record["status"] = "failed"
        if echo:
            _echo(
                f"[{index}/{total}] {stage.id} FAILED "
                f"(exit {result.returncode}) after {elapsed:.1f}s"
            )
            _echo(f"Inspect the run manifest: {output_path}")
            _echo(
                "Re-run just this stage with: gridalyn project run "
                f"{project.root} --stage {stage.id}"
            )
        raise subprocess.CalledProcessError(result.returncode, stage.command)
    record["status"] = "completed"
    if echo:
        _echo(f"[{index}/{total}] {stage.id} completed in {elapsed:.1f}s")


def run_project(
    project: StudyProject,
    dry_run: bool = False,
    manifest_path: Path | str | None = None,
    echo: bool = False,
    stages: list[str] | None = None,
) -> list[str]:
    started_at = _utc_now()
    git_commit = _git_commit(project.base_dir)
    manifest = {
        "project": {
            "name": project.name,
            "version": project.version,
            "path": str(project.path),
        },
        "workflow": {
            "name": project.workflow.name,
            "path": str(project.workflow.path),
        },
        "dry_run": dry_run,
        "git_commit": git_commit,
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "stages": [],
    }
    output_path = (
        Path(manifest_path) if manifest_path else default_manifest_path(project)
    )
    planned = select_stages(project, stages) if stages else plan_stages(project)
    manifest["provenance"] = _build_provenance(project, planned)
    if stages:
        manifest["stage_filter"] = sorted({stage.id for stage in planned})
    total = len(planned)
    executed: list[str] = []
    try:
        for index, stage in enumerate(planned, start=1):
            executed.append(stage.id)
            record = {
                "id": stage.id,
                "command": stage.command,
                "status": "planned" if dry_run else "running",
                "started_at": None if dry_run else _utc_now(),
                "ended_at": None,
                "exit_code": None,
            }
            manifest["stages"].append(record)
            if dry_run:
                if echo:
                    _echo(f"[{index}/{total}] {stage.id} (planned): {stage.command}")
                continue

            _execute_stage(
                stage,
                record,
                project=project,
                index=index,
                total=total,
                output_path=output_path,
                echo=echo,
            )
    except Exception:
        if manifest["status"] == "running":
            manifest["status"] = "failed"
        raise
    finally:
        if manifest["status"] == "running":
            manifest["status"] = "planned" if dry_run else "completed"
        manifest["ended_at"] = _utc_now()
        try:
            manifest["study_run"] = build_study_run(
                project_id=project.name,
                project_version=project.version,
                workflow_id=project.workflow.name,
                dry_run=dry_run,
                status=str(manifest["status"]),
                started_at=started_at,
                ended_at=str(manifest["ended_at"]) if manifest["ended_at"] else None,
                git_commit=git_commit,
                stages=list(manifest["stages"]),
                lineage={
                    "project_path": str(project.path),
                    "project_root": str(project.root),
                    "workflow_path": str(project.workflow.path),
                },
            ).to_dict()
        except Exception as exc:  # never lose the manifest over a provenance sub-step
            manifest["study_run_error"] = repr(exc)
        _write_manifest(output_path, manifest)
        if echo and manifest["status"] != "failed":
            label = "planned" if dry_run else "completed"
            _echo(f"{label} {len(executed)}/{total} stage(s); manifest: {output_path}")
    return executed

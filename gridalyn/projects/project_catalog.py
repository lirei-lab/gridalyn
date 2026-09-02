"""Describe a study's result artifacts so a viewer needs no per-study code.

The dashboard carried a 131-line component dedicated to one study, because it
knew that study's artifact *shape*: four file names and the column names inside
them. Making the study name configurable was never enough -- the shape was the
coupling.

**What replaces it is already declared.** Every study's ``project.yaml`` names
``spec.validation.objectiveArtifacts``: the artifacts that carry that study's
result, 34 of them across the eight shipped studies. This module classifies
that declared list rather than introducing a second one. That choice is not
stylistic: :mod:`gridalyn.projects.sense_checks` records that its predecessor
kept *two* dicts keyed by project name which had to stay in sync by hand, and
repairing that is why the declaration moved into ``project.yaml`` at all.
Adding a parallel ``dashboardArtifacts`` would rebuild the defect.

**Governed reports are the uniform shape.** 22 of those 34 artifacts are
platform reports, and every platform report carries the same eight required
fields. A viewer that renders ``summary``, ``artifacts`` and ``validation``
therefore renders *any* study's reports with no study-specific code. The
remaining 12 are tabular (CSV under ``data/`` or ``operations/``) and carry no
declared column contract, so they are catalogued as tables to link rather than
charts to draw -- an honest limit, not a gap to paper over.

This module sits in the ``projects`` layer and imports only downward, which is
what makes describing both a twin and a study legitimate here: the dashboard
catalog is written by ``projects``, not by ``twin``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS
from gridalyn.projects.scenario_catalog import (
    ScenarioContract,
    ScenarioContractError,
    read_scenario_contract,
    read_scenario_index,
)

KIND_GOVERNED_REPORT = "governed_report"
KIND_TABLE = "table"
KIND_UNKNOWN = "unknown"

_TABLE_SUFFIXES = frozenset({".csv", ".parquet"})


def classify_artifact(relative: str) -> str:
    """Classify a declared artifact by what a viewer can do with it.

    Args:
        relative: Project-relative artifact path, e.g.
            ``"outputs/reports/minimal_grid_report.json"``.

    Returns:
        :data:`KIND_GOVERNED_REPORT` for a JSON artifact under ``reports/``,
        :data:`KIND_TABLE` for a CSV or parquet, :data:`KIND_UNKNOWN`
        otherwise. The report classification is provisional -- it says the
        artifact is *shaped* like a governed report by location and suffix;
        :func:`describe_artifact` confirms it against the actual payload,
        because a hand-written JSON file in ``reports/`` is exactly the
        anti-pattern the report contract exists to catch.
    """
    path = Path(relative)
    suffix = path.suffix.lower()
    if suffix in _TABLE_SUFFIXES:
        return KIND_TABLE
    if suffix == ".json" and "reports" in path.parts:
        return KIND_GOVERNED_REPORT
    return KIND_UNKNOWN


def _read_report_fields(path: Path) -> dict[str, Any] | None:
    """Return the identifying fields of a governed report, or ``None``.

    ``None`` means the file is absent, unreadable, or does not carry every
    field in ``REQUIRED_REPORT_FIELDS`` -- i.e. it is not a governed report,
    whatever its name and location suggest.
    """
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if not set(REQUIRED_REPORT_FIELDS).issubset(payload):
        return None
    summary = payload.get("summary")
    validation = payload.get("validation")
    return {
        "report_id": payload.get("report_id"),
        "source_domain": payload.get("source_domain"),
        "schema_version": payload.get("schema_version"),
        # Only the KEYS, not the values. The catalog is an index of what is
        # available; duplicating every summary into it would give a reader two
        # copies of the same number that drift apart the moment one is
        # regenerated. The viewer fetches the report for the values.
        "summary_keys": sorted(summary) if isinstance(summary, Mapping) else [],
        "valid": (validation.get("valid") if isinstance(validation, Mapping) else None),
    }


def describe_artifact(
    relative: str,
    *,
    project_dir: Path,
    served_prefix: str,
) -> dict[str, Any]:
    """Describe one declared artifact for the catalog.

    Args:
        relative: Project-relative path as declared in ``project.yaml``.
        project_dir: Directory the project's outputs live under, used to check
            existence and read a report's identifying fields.
        served_prefix: URL prefix the artifact is served from.

    Returns:
        A JSON-native description carrying the served path, the resolved kind,
        whether the artifact is present, and -- for a confirmed governed
        report -- its report id, source domain and summary keys.
    """
    kind = classify_artifact(relative)
    path = project_dir / relative
    exists = path.is_file()
    described: dict[str, Any] = {
        "path": f"{served_prefix.rstrip('/')}/{relative.lstrip('/')}",
        "relative": relative,
        "kind": kind,
        "exists": exists,
    }
    if kind == KIND_GOVERNED_REPORT and exists:
        fields = _read_report_fields(path)
        if fields is None:
            # Shaped like a report, is not one. Said plainly rather than
            # rendered as a report the viewer then fails to read.
            described["kind"] = KIND_UNKNOWN
            described["note"] = (
                "JSON under reports/ that does not carry the required report "
                "fields; not a governed report"
            )
        else:
            described.update(fields)
    return described


def build_project_catalog(
    projects: Iterable[Any],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    """Describe every project's declared result artifacts.

    Args:
        projects: Loaded ``StudyProject`` objects. Each contributes its
            ``spec.validation.objectiveArtifacts``; a project that declares
            none contributes an empty artifact list rather than being dropped,
            so a viewer can say "this study declares nothing to show" instead
            of silently omitting it.
        root: Workspace root the served paths are expressed relative to.

    Returns:
        One entry per project, sorted by name, each with ``project_id``,
        ``label``, the served ``base_path`` and the described ``artifacts``.
    """
    entries: list[dict[str, Any]] = []
    for project in sorted(projects, key=lambda item: str(getattr(item, "name", ""))):
        project_dir = Path(getattr(project, "base_dir", getattr(project, "root", root)))
        try:
            relative_dir = project_dir.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            relative_dir = project_dir
        served_prefix = "/" + str(relative_dir).replace("\\", "/").lstrip("/")
        declared = _declared_objective_artifacts(project)
        entries.append(
            {
                "project_id": project.name,
                "label": _label(project),
                "description": _metadata_text(project, "description"),
                "base_path": served_prefix,
                "artifacts": [
                    describe_artifact(
                        relative,
                        project_dir=project_dir,
                        served_prefix=served_prefix,
                    )
                    for relative in declared
                ],
                # What the study SAYS matters, so a viewer never guesses.
                # Presentation follows declaration or it becomes per-study code.
                "objective": _problem_objective(project),
                "experiments": describe_experiments(project),
                "governed_metrics": describe_governed_metrics(project_dir),
                "scenarios": describe_scenarios(
                    project,
                    project_dir=project_dir,
                    served_prefix=served_prefix,
                ),
            }
        )
    return entries


def _problem_objective(project: Any) -> str:
    """Return the question this study asks, or an empty string.

    ``spec.problem.objective`` is declared by all eight shipped studies and was
    read by nothing. A viewer that opens a study and cannot say what it is FOR
    is showing numbers without their question.
    """
    raw = getattr(project, "raw", None)
    if not isinstance(raw, Mapping):
        return ""
    problem = (raw.get("spec") or {}).get("problem")
    if not isinstance(problem, Mapping):
        return ""
    objective = problem.get("objective")
    return str(objective).strip() if isinstance(objective, str) else ""


def describe_experiments(project: Any) -> list[dict[str, Any]]:
    """Describe each declared experiment: what it is for, and what it measures.

    ``spec.experiments[].metrics`` is the study's own statement of which
    numbers are the result and which are context -- six of the eight shipped
    studies declare it. Rendering every summary key at equal weight throws that
    statement away, which is what made a bus count look like a headline.

    Args:
        project: Loaded ``StudyProject``.

    Returns:
        One entry per experiment, in declaration order. A study that declares
        none yields an empty list and its viewer falls back to showing the
        summary undifferentiated -- honest, because nothing said otherwise.
    """
    raw = getattr(project, "raw", None)
    if not isinstance(raw, Mapping):
        return []
    experiments = (raw.get("spec") or {}).get("experiments")
    if not isinstance(experiments, list):
        return []
    described: list[dict[str, Any]] = []
    for entry in experiments:
        if not isinstance(entry, Mapping):
            continue
        # Both spellings are declared in the shipped studies: a single
        # `scenario` and a list of `scenarios`. Normalized to a list here so a
        # consumer reads one shape.
        scenarios = entry.get("scenarios")
        if not isinstance(scenarios, list):
            single = entry.get("scenario")
            scenarios = [single] if isinstance(single, str) else []
        described.append(
            {
                "id": str(entry.get("id") or ""),
                "objective": str(entry.get("objective") or "").strip(),
                "metrics": [
                    str(metric)
                    for metric in (entry.get("metrics") or [])
                    if isinstance(metric, str)
                ],
                "scenarios": [str(name) for name in scenarios],
            }
        )
    return described


def describe_governed_metrics(project_dir: Path) -> list[dict[str, Any]]:
    """Resolve which of a study's numbers are regression-pinned.

    Declared and governed are two different statements and this catalog keeps
    them apart. ``spec.experiments[].metrics`` is what the study set out to
    measure; a baseline pin is what a re-run is checked against. They do not
    have to agree, and in ``der_voltage_optimization`` they do not -- it
    declares three metrics and pins four other values. A value that is both is
    the strongest claim this contract can make about a result, and conflating
    them would throw that away.

    Args:
        project_dir: The study's directory on disk.

    Returns:
        One entry per pin, naming the report it lives in and the summary key it
        addresses. Empty when the study carries no baseline, which is not a
        defect: a study can be governed by its sense checks alone.
    """
    path = project_dir / "baselines" / "results_baseline.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pins: list[dict[str, Any]] = []
    for metric in payload.get("metrics") or []:
        if not isinstance(metric, Mapping):
            continue
        json_path = metric.get("json_path")
        if not isinstance(json_path, list) or not json_path:
            continue
        pins.append(
            {
                "id": str(metric.get("id") or ""),
                "source": str(metric.get("source") or ""),
                # The final segment is the summary key a viewer displays; the
                # leading segments say which block of the report it sits in.
                "block": str(json_path[0]),
                "key": str(json_path[-1]),
                "tolerance": metric.get("tolerance"),
            }
        )
    return pins


def describe_scenarios(
    project: Any,
    *,
    project_dir: Path,
    served_prefix: str,
) -> list[dict[str, Any]]:
    """Describe a study's scenarios in the shape the twin's already use.

    One shape for both sources is the point: the client should not have a twin
    code path and a study code path, because the moment it does, a study's
    scenarios are second-class and the assumptions the twin's shape carries get
    written into the client again.

    Args:
        project: Loaded ``StudyProject``.
        project_dir: The study's directory on disk.
        served_prefix: URL prefix the study's files are served under.

    Returns:
        One entry per scenario, each carrying ``scenario_id``, ``label`` and
        ``paths`` keyed by the DECLARED kinds. Empty when the study declares no
        contract, or when its index has not been produced -- a study whose
        outputs are absent is not a broken study, the same reading
        :func:`describe_artifact` gives a missing file.
    """
    contract = _scenario_contract(project)
    if contract is None:
        return []
    index = read_scenario_index(
        project_dir / contract.index,
        id_column=contract.id_column,
        label_column=contract.label_column,
    )
    described: list[dict[str, Any]] = []
    for row in index:
        scenario_id = str(row["scenario_id"])
        paths: dict[str, str] = {}
        for artifact in contract.artifacts:
            relative = artifact.resolve(scenario_id)
            if not (project_dir / relative).is_file():
                continue
            paths[artifact.kind] = f"{served_prefix.rstrip('/')}/{relative}"
        described.append(
            {
                "scenario_id": scenario_id,
                "label": row.get("label") or scenario_id,
                "description": row.get("label") or "",
                "paths": paths,
                # How a consumer must READ each kind. Without this a client
                # holding only the paths would have to guess whether a file is
                # this scenario's alone or every scenario's, and guessing wrong
                # renders another scenario's rows as this one's.
                "partitioning": {
                    artifact.kind: artifact.to_dict()
                    for artifact in contract.artifacts
                    if artifact.kind in paths
                },
            }
        )
    return described


def _scenario_contract(project: Any) -> ScenarioContract | None:
    """Return a study's declared scenario contract, or ``None``.

    A malformed contract is reported on stderr and treated as absent rather
    than taking the whole catalog down: the twin's scenarios and every other
    study are unrelated to one study's bad declaration. That is the same
    posture the catalog generator takes toward a study whose project.yaml will
    not parse.
    """
    raw = getattr(project, "raw", None)
    spec = (raw or {}).get("spec") if isinstance(raw, Mapping) else None
    path = Path(getattr(project, "path", "project.yaml"))
    try:
        return read_scenario_contract(spec, path=path)
    except ScenarioContractError as error:
        print(f"warning: {error}", file=sys.stderr, flush=True)
        return None


def _label(project: Any) -> str:
    """Return a human label for a project, falling back to its directory name.

    No shipped ``project.yaml`` declares a display name today, so the fallback
    is the normal path rather than the exception; it is kept ahead of the
    fallback so a study can name itself without a code change.
    """
    for key in ("displayName", "title", "label"):
        value = _metadata_text(project, key)
        if value:
            return value
    return str(project.name).replace("_", " ").title()


def _metadata_text(project: Any, key: str) -> str | None:
    """Return a non-empty string from the project's ``metadata`` block."""
    raw = getattr(project, "raw", None)
    if not isinstance(raw, Mapping):
        return None
    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _declared_objective_artifacts(project: Any) -> tuple[str, ...]:
    """Return the artifacts a project declares as carrying its result."""
    raw = getattr(project, "raw", None)
    if not isinstance(raw, Mapping):
        return ()
    spec = raw.get("spec")
    if not isinstance(spec, Mapping):
        return ()
    validation = spec.get("validation")
    if not isinstance(validation, Mapping):
        return ()
    declared = validation.get("objectiveArtifacts")
    if not isinstance(declared, (list, tuple)):
        return ()
    return tuple(str(item) for item in declared if isinstance(item, str))

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

from pathlib import Path
from typing import Any, Iterable, Mapping

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

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
            }
        )
    return entries


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

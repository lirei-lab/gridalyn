"""What a scenario IS, declared once, for a twin and for a study alike.

The dashboard could show one source's scenarios and only one: the twin's. It
wrote the set of per-scenario artifact kinds -- ``nodes``, ``lines``,
``power``, ``transformers`` -- into three separate files, and synthesized
``timeseries/{id}_{suffix}.parquet`` in the *client*, which is the twin's
on-disk layout asserted by a consumer that is supposed to be told it.

The reason that could not simply be widened is that the two shapes genuinely
differ, and neither is more correct:

===================  =======================================================
Partitioning         What it means
===================  =======================================================
:data:`BY_FILE`      One artifact per (scenario, kind). The twin: five
                     scenarios times four kinds, ``S0_powerflow_nodes.parquet``
                     and its siblings. The scenario id is in the *path*.
:data:`BY_COLUMN`    One artifact for every scenario, discriminated by a
                     column. ``ieee_33_bus_demo``:
                     ``scenario_voltage_profiles.csv`` is 165 rows, 33 buses
                     times 5 scenarios, and the scenario id is in the *rows*.
===================  =======================================================

So the declaration names the partitioning rather than assuming either. That is
the load-bearing part; a contract that picked one would have moved the
hardcoding rather than removed it.

**Reusing the declaration that exists.** ``spec.experiments`` already names
scenarios in every shipped study. This module reads it for labels and never
introduces a second list of scenario names --
:mod:`gridalyn.projects.project_catalog` records why: its predecessor kept two
dicts keyed by project name that had to agree by hand, and repairing that is
the reason study declarations moved into ``project.yaml`` at all.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

#: One artifact per (scenario, kind); the scenario id appears in the path.
BY_FILE = "file"

#: One artifact for all scenarios; the scenario id appears in a column.
BY_COLUMN = "column"

PARTITIONINGS: tuple[str, ...] = (BY_FILE, BY_COLUMN)

#: Placeholder a ``BY_FILE`` path template must carry.
SCENARIO_TOKEN = "{scenario_id}"

#: Column an indexer defaults to, and the one every shipped producer writes.
DEFAULT_ID_COLUMN = "scenario_id"

#: Suffixes :func:`read_scenario_index` can enumerate scenarios from.
INDEX_SUFFIXES: tuple[str, ...] = (".csv", ".json")


class ScenarioContractError(ValueError):
    """A declared scenario contract could not be read.

    A ``ValueError`` because it is a contract violation, matching how
    :mod:`gridalyn.projects.model_inputs` reports a malformed input.
    """


@dataclass(frozen=True)
class ScenarioArtifact:
    """One kind of data a scenario carries, and how to reach it.

    Attributes:
        kind: Name the consumer asks for this data by. Free-form and declared:
            the point of the contract is that no consumer holds a fixed set.
        template: Project-relative path. Carries :data:`SCENARIO_TOKEN` when
            ``partitioning`` is :data:`BY_FILE`, and is a plain path when it is
            :data:`BY_COLUMN`.
        partitioning: :data:`BY_FILE` or :data:`BY_COLUMN`.
        id_column: Column carrying the scenario id, for :data:`BY_COLUMN`.
            ``None`` for :data:`BY_FILE`, where the id is in the path instead.
    """

    kind: str
    template: str
    partitioning: str
    id_column: str | None = None

    def resolve(self, scenario_id: str) -> str:
        """Return the project-relative path holding ``scenario_id``'s data."""
        if self.partitioning == BY_FILE:
            return self.template.replace(SCENARIO_TOKEN, scenario_id)
        return self.template

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native rendering for a catalog."""
        return {
            "kind": self.kind,
            "partitioning": self.partitioning,
            "id_column": self.id_column,
        }


@dataclass(frozen=True)
class ScenarioContract:
    """How a study says its scenarios may be enumerated and read.

    Attributes:
        index: Project-relative path of the artifact that ENUMERATES the
            scenarios -- the indexer. Reading ids from it rather than from a
            directory listing is what lets a study add a scenario without any
            consumer changing.
        id_column: Column or key in the indexer carrying each scenario id.
        label_column: Column or key carrying a human label, or ``None``.
        artifacts: The kinds each scenario carries, in declared order.
    """

    index: str
    id_column: str
    label_column: str | None
    artifacts: tuple[ScenarioArtifact, ...]

    @property
    def kinds(self) -> tuple[str, ...]:
        """Return the declared kind names, in declaration order."""
        return tuple(artifact.kind for artifact in self.artifacts)


def _require_mapping(value: Any, where: str, path: Path) -> Mapping[str, Any]:
    """Return ``value`` as a mapping, or raise a located contract error."""
    if not isinstance(value, Mapping):
        raise ScenarioContractError(
            f"{path}: {where} must be a mapping, found {type(value).__name__}"
        )
    return value


def read_scenario_contract(
    spec: Mapping[str, Any] | None,
    *,
    path: Path,
) -> ScenarioContract | None:
    """Read ``spec.scenarios`` from a study's declaration.

    Args:
        spec: The study's ``spec`` block, or ``None``.
        path: The ``project.yaml``, named in every error.

    Returns:
        The declared contract, or ``None`` when the study declares none. A
        study without scenarios is the normal case, not a defect.

    Raises:
        ScenarioContractError: If the block is present but malformed. Every
            message names the file, the key and the remedy.
    """
    declared = (spec or {}).get("scenarios")
    if declared is None:
        return None
    block = _require_mapping(declared, "spec.scenarios", path)

    index = block.get("index")
    if not isinstance(index, str) or not index.strip():
        raise ScenarioContractError(
            f"{path}: spec.scenarios.index must name the artifact that "
            f"enumerates this study's scenarios (supported suffixes: "
            f"{', '.join(INDEX_SUFFIXES)}); found {index!r}"
        )

    raw_artifacts = block.get("artifacts")
    if not isinstance(raw_artifacts, Mapping) or not raw_artifacts:
        available = ", ".join(sorted(str(key) for key in block)) or "none declared"
        raise ScenarioContractError(
            f"{path}: spec.scenarios.artifacts must be a non-empty mapping of "
            f"kind -> declaration (present keys: {available}); a contract that "
            "names no artifact tells a consumer nothing it can read"
        )

    artifacts = tuple(
        _read_artifact(kind, value, path=path) for kind, value in raw_artifacts.items()
    )
    return ScenarioContract(
        index=index.strip(),
        id_column=str(block.get("idColumn") or DEFAULT_ID_COLUMN),
        label_column=block.get("labelColumn") or None,
        artifacts=artifacts,
    )


def _read_artifact(kind: str, value: Any, *, path: Path) -> ScenarioArtifact:
    """Read one ``spec.scenarios.artifacts`` entry, or raise a located error."""
    where = f"spec.scenarios.artifacts.{kind}"
    block = _require_mapping(value, where, path)

    template = block.get("path")
    if not isinstance(template, str) or not template.strip():
        raise ScenarioContractError(f"{path}: {where}.path must name a file")

    partitioning = str(block.get("partitioning") or BY_FILE)
    if partitioning not in PARTITIONINGS:
        raise ScenarioContractError(
            f"{path}: {where}.partitioning is {partitioning!r}; it must be one "
            f"of {', '.join(PARTITIONINGS)} -- {BY_FILE!r} when the scenario "
            f"id is in the path, {BY_COLUMN!r} when it is in a column"
        )

    id_column: str | None = None
    if partitioning == BY_FILE:
        if SCENARIO_TOKEN not in template:
            raise ScenarioContractError(
                f"{path}: {where}.path is {template!r} but declares "
                f"partitioning {BY_FILE!r}, so it must carry {SCENARIO_TOKEN} "
                "-- otherwise every scenario would resolve to one file"
            )
    else:
        id_column = str(block.get("idColumn") or DEFAULT_ID_COLUMN)
        if SCENARIO_TOKEN in template:
            raise ScenarioContractError(
                f"{path}: {where}.path carries {SCENARIO_TOKEN} but declares "
                f"partitioning {BY_COLUMN!r}; a column-partitioned artifact "
                "holds every scenario, so its path takes no scenario id"
            )
    return ScenarioArtifact(
        kind=str(kind),
        template=template.strip(),
        partitioning=partitioning,
        id_column=id_column,
    )


def read_scenario_index(
    path: Path,
    *,
    id_column: str,
    label_column: str | None = None,
) -> tuple[dict[str, str | None], ...]:
    """Enumerate scenarios from a declared indexer.

    Args:
        path: The indexer on disk.
        id_column: Column or key holding each scenario id.
        label_column: Column or key holding a label, or ``None``.

    Returns:
        ``{"scenario_id": ..., "label": ...}`` per row, in file order,
        duplicates dropped keeping the first. Empty when the file is absent --
        a study whose outputs have not been produced is not a broken study,
        which is the same reading ``project_catalog`` gives an absent artifact.

    Raises:
        ScenarioContractError: If the suffix is unsupported, or the file
            carries no ``id_column``.
    """
    if not path.is_file():
        return ()
    suffix = path.suffix.lower()
    if suffix not in INDEX_SUFFIXES:
        raise ScenarioContractError(
            f"{path}: unsupported scenario index suffix {suffix!r} "
            f"(supported: {', '.join(INDEX_SUFFIXES)})"
        )
    rows = _index_rows(path, suffix)
    seen: dict[str, str | None] = {}
    for row in rows:
        if id_column not in row:
            raise ScenarioContractError(
                f"{path}: the scenario index carries no {id_column!r} column "
                f"(present: {', '.join(str(key) for key in row) or 'none'}); "
                "declare the right one as spec.scenarios.idColumn"
            )
        scenario_id = str(row[id_column]).strip()
        if not scenario_id or scenario_id in seen:
            continue
        label = row.get(label_column) if label_column else None
        seen[scenario_id] = str(label) if label else None
    return tuple({"scenario_id": key, "label": value} for key, value in seen.items())


def _index_rows(path: Path, suffix: str) -> Iterable[Mapping[str, Any]]:
    """Return the indexer's rows, whichever of the two formats it is in."""
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("scenarios", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    raise ScenarioContractError(
        f"{path}: a JSON scenario index must be a list of objects, or an "
        "object carrying one under 'scenarios', 'items' or 'records'"
    )


__all__ = [
    "BY_COLUMN",
    "BY_FILE",
    "DEFAULT_ID_COLUMN",
    "INDEX_SUFFIXES",
    "PARTITIONINGS",
    "SCENARIO_TOKEN",
    "ScenarioArtifact",
    "ScenarioContract",
    "ScenarioContractError",
    "read_scenario_contract",
    "read_scenario_index",
]

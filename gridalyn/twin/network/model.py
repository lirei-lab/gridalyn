"""Domain containers for the one canonical, identified network model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

BASE_TABLE_FILENAMES: dict[str, str] = {
    "grid_buses": "grid_buses.parquet",
    "grid_lines": "grid_lines.parquet",
    "grid_transformers": "grid_transformers.parquet",
    "buildings": "buildings.parquet",
    "building_grid_connectivity": "building_grid_connectivity.parquet",
}

BASE_PROFILE_ID = "gridalyn:digital-twin-base"

SCENARIO_TIME_ABSENT_REASON = (
    "no scenario clock exists in the base artifacts; CGMES scenarioTime is the "
    "instant the network state represents, which is not the instant the model "
    "was created, so it is carried as None rather than defaulted to `created`"
)

ProvenanceStatus = Literal["declared", "absent"]

PROVENANCE_DECLARED: ProvenanceStatus = "declared"
PROVENANCE_ABSENT: ProvenanceStatus = "absent"


@dataclass(frozen=True)
class ModelIdentity:
    """CGMES ``FullModel`` identity semantics for a canonical network model.

    Field names are this repository's snake_case rendering of the CGMES header
    fields; the semantics — not the RDF/XML serialization — are what is adopted
    (see the Phase 11 shadow design). The CGMES mapping is:

    ==================  ==========================================================
    CGMES header field  Source in this repository
    ==================  ==========================================================
    ``id`` (mRID)       ``metadata.json`` ``model_version_id`` (a content digest
                        produced by :func:`build_model_version`)
    ``created``         ``metadata.json`` ``created_at``
    ``scenarioTime``    **no source** — always ``None``; see
                        :data:`SCENARIO_TIME_ABSENT_REASON`
    ``version``         ``model_version.schema_version`` — the governance model
                        version contract that :func:`build_model_version` stamps
    ``profile``         :data:`BASE_PROFILE_ID` joined to the manifest's
                        ``BASE_METADATA_SCHEMA_VERSION``
    ``dependentOn``     the declared artifact paths the model is assembled from
    ==================  ==========================================================
    """

    id: str | None = None
    created: str | None = None
    scenario_time: None = None
    version: str | None = None
    profile: str | None = None
    dependent_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkModel:
    """The canonical network model: five asset tables plus its own identity.

    This is the only canonical model type. The adapter-side twin of it —
    ``NetworkSnapshot`` — was merged into it in Phase 11 (plan 11-01) because
    the two held the same five frames with byte-identical ``counts``.
    """

    buses: pd.DataFrame
    lines: pd.DataFrame
    transformers: pd.DataFrame
    buildings: pd.DataFrame
    connectivity: pd.DataFrame
    source_adapter: str | None = None
    source_standard: str | None = None
    identity: ModelIdentity | None = None
    provenance_status: ProvenanceStatus = PROVENANCE_ABSENT

    @property
    def counts(self) -> dict[str, int]:
        """Return row counts per canonical table plus the distinct load count."""
        load_count = 0
        if "load_id" in self.buildings.columns:
            load_count = int(self.buildings["load_id"].dropna().nunique())
        return {
            "buses": int(len(self.buses)),
            "lines": int(len(self.lines)),
            "transformers": int(len(self.transformers)),
            "buildings": int(len(self.buildings)),
            "loads": load_count,
            "connectivity": int(len(self.connectivity)),
        }

    @property
    def has_provenance(self) -> bool:
        """Report whether an on-disk ``metadata.json`` manifest backs this model.

        Returns:
            ``True`` only when the model was loaded from a repository whose
            metadata manifest was present and parseable. A model built in memory
            by a source adapter is ``False``: it carries ``source_adapter`` and
            ``source_standard``, but no manifest has been written for it yet.
        """
        return self.provenance_status == PROVENANCE_DECLARED

    def write_parquet(self, out_dir: Path) -> dict[str, Path]:
        """Write the model to the canonical base Parquet artifacts.

        Args:
            out_dir: Directory to write the five canonical tables into; created
                with parents if it does not exist.

        Returns:
            Mapping of canonical artifact name to the path written.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        frames = {
            "grid_buses": self.buses,
            "grid_lines": self.lines,
            "grid_transformers": self.transformers,
            "buildings": self.buildings,
            "building_grid_connectivity": self.connectivity,
        }
        artifact_paths: dict[str, Path] = {}
        for artifact_name, frame in frames.items():
            path = out_dir / BASE_TABLE_FILENAMES[artifact_name]
            frame.to_parquet(path, index=False)
            artifact_paths[artifact_name] = path
        return artifact_paths


@dataclass(frozen=True)
class DownstreamAssets:
    """Customer assets served by one upstream network element.

    Attributes:
        upstream_id: Identifier of the element the assets hang off -- a
            transformer for :meth:`NetworkModelRepository.get_downstream`, a
            feeder for :meth:`NetworkModelRepository.get_feeder`. It was called
            ``constraint_id`` until Phase 11 (plan 11-03), which was wrong twice
            over: ``get_feeder`` stored a feeder id in it, and neither query
            takes a constraint. ``constraint_zone_id`` in
            ``gridalyn/operations`` is a different, live concept -- the
            flexibility-market zone -- and is untouched.
        building_ids: Buildings served, sorted and deduplicated.
        load_ids: Loads served, sorted and deduplicated.
        bus_ids: Buses the served customers connect to, sorted and deduplicated.
    """

    upstream_id: str
    building_ids: tuple[str, ...]
    load_ids: tuple[str, ...]
    bus_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConnectedEquipment:
    """Equipment and customer assets directly connected to a bus."""

    bus_id: str
    line_ids: tuple[str, ...]
    transformer_ids: tuple[str, ...]
    building_ids: tuple[str, ...]
    load_ids: tuple[str, ...]


@dataclass(frozen=True)
class NetworkIntegrityReport:
    """Validation summary for a loaded network model."""

    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, int]

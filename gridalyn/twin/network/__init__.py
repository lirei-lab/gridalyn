"""Canonical network model repository and topology query APIs."""

from gridalyn.twin.network.metadata import build_base_metadata, write_base_metadata
from gridalyn.twin.network.model import (
    BASE_PROFILE_ID,
    BASE_TABLE_FILENAMES,
    PROVENANCE_ABSENT,
    PROVENANCE_DECLARED,
    SCENARIO_TIME_ABSENT_REASON,
    ConnectedEquipment,
    DownstreamAssets,
    ModelIdentity,
    NetworkIntegrityReport,
    NetworkModel,
)
from gridalyn.twin.network.repository import (
    MissingProvenanceWarning,
    NetworkModelRepository,
)

__all__ = [
    "BASE_PROFILE_ID",
    "BASE_TABLE_FILENAMES",
    "PROVENANCE_ABSENT",
    "PROVENANCE_DECLARED",
    "SCENARIO_TIME_ABSENT_REASON",
    "ConnectedEquipment",
    "DownstreamAssets",
    "MissingProvenanceWarning",
    "ModelIdentity",
    "NetworkIntegrityReport",
    "NetworkModel",
    "NetworkModelRepository",
    "build_base_metadata",
    "write_base_metadata",
]

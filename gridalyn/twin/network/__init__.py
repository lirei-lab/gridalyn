"""Canonical network model repository and topology query APIs."""

from gridalyn.twin.network.geography import (
    CRS_ASSUMED,
    CRS_DECLARED,
    DEFAULT_GEOGRAPHIC_CRS,
    BoundingBox,
    NetworkGeography,
    resolve_network_geography,
)
from gridalyn.twin.network.metadata import build_base_metadata, write_base_metadata
from gridalyn.twin.network.model import (
    BASE_PROFILE_ID,
    BASE_TABLE_FILENAMES,
    DEFAULT_OPERATIONAL_STATE,
    OPERATIONAL_STATE_ABSENT_REASON,
    OPERATIONAL_STATES,
    PROVENANCE_ABSENT,
    PROVENANCE_DECLARED,
    SCENARIO_TIME_ABSENT_REASON,
    ConnectedEquipment,
    DownstreamAssets,
    ModelIdentity,
    NetworkIntegrityReport,
    NetworkModel,
    OperationalState,
)
from gridalyn.twin.network.repository import (
    MissingProvenanceWarning,
    NetworkModelRepository,
)

__all__ = [
    "BASE_PROFILE_ID",
    "BASE_TABLE_FILENAMES",
    "DEFAULT_OPERATIONAL_STATE",
    "OPERATIONAL_STATE_ABSENT_REASON",
    "OPERATIONAL_STATES",
    "PROVENANCE_ABSENT",
    "CRS_ASSUMED",
    "CRS_DECLARED",
    "DEFAULT_GEOGRAPHIC_CRS",
    "PROVENANCE_DECLARED",
    "SCENARIO_TIME_ABSENT_REASON",
    "BoundingBox",
    "ConnectedEquipment",
    "DownstreamAssets",
    "MissingProvenanceWarning",
    "ModelIdentity",
    "NetworkIntegrityReport",
    "NetworkModel",
    "NetworkGeography",
    "NetworkModelRepository",
    "OperationalState",
    "build_base_metadata",
    "resolve_network_geography",
    "write_base_metadata",
]

"""Domain containers for canonical network model snapshots."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class NetworkModel:
    """A loaded network model snapshot backed by canonical asset tables."""

    buses: pd.DataFrame
    lines: pd.DataFrame
    transformers: pd.DataFrame
    buildings: pd.DataFrame
    connectivity: pd.DataFrame

    @property
    def counts(self) -> dict[str, int]:
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


@dataclass(frozen=True)
class DownstreamAssets:
    """Assets served by a network constraint such as an MV/LV transformer."""

    constraint_id: str
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

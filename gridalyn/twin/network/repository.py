"""Repository API for Parquet-backed canonical network models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from gridalyn.twin.network.model import (
    ConnectedEquipment,
    DownstreamAssets,
    NetworkIntegrityReport,
    NetworkModel,
)


@dataclass(frozen=True)
class NetworkModelRepository:
    """Read and query a canonical network model snapshot."""

    base_dir: Path

    @classmethod
    def from_parquet(cls, base_dir: Path | str) -> "NetworkModelRepository":
        return cls(base_dir=Path(base_dir))

    def load_model(self) -> NetworkModel:
        """Load available canonical network tables from the repository path."""
        return NetworkModel(
            buses=self._read_table("grid_buses.parquet"),
            lines=self._read_table("grid_lines.parquet"),
            transformers=self._read_table("grid_transformers.parquet"),
            buildings=self._read_table("buildings.parquet"),
            connectivity=self._read_table("building_grid_connectivity.parquet"),
        )

    def get_downstream(self, constraint_id: str) -> DownstreamAssets:
        """Return buildings, loads, and buses downstream of a transformer ID."""
        model = self.load_model()
        connectivity = model.connectivity
        if connectivity.empty:
            return DownstreamAssets(
                constraint_id=constraint_id,
                building_ids=(),
                load_ids=(),
                bus_ids=(),
            )

        transformer_column = self._first_existing_column(
            connectivity,
            ["lv_transformer_id", "transformer_id", "constraint_zone_id"],
        )
        if transformer_column is None:
            raise ValueError(
                "building_grid_connectivity.parquet must include one of: "
                "lv_transformer_id, transformer_id, constraint_zone_id"
            )

        rows = connectivity.loc[
            connectivity[transformer_column].astype(str) == str(constraint_id)
        ].copy()
        return DownstreamAssets(
            constraint_id=str(constraint_id),
            building_ids=self._unique_strings(rows, ["building_id"]),
            load_ids=self._unique_strings(rows, ["load_id"]),
            bus_ids=self._unique_strings(rows, ["load_bus_id", "lv_bus_id", "bus_id"]),
        )

    def get_feeder(self, feeder_id: str) -> DownstreamAssets:
        """Return customer assets served by a feeder or LV feeder bus ID."""
        model = self.load_model()
        connectivity = model.connectivity
        if connectivity.empty:
            return DownstreamAssets(
                constraint_id=str(feeder_id),
                building_ids=(),
                load_ids=(),
                bus_ids=(),
            )

        feeder_column = self._first_existing_column(
            connectivity,
            ["feeder_id", "lv_feeder_bus_id", "lv_cluster"],
        )
        if feeder_column is None:
            raise ValueError(
                "building_grid_connectivity.parquet must include one of: "
                "feeder_id, lv_feeder_bus_id, lv_cluster"
            )

        rows = connectivity.loc[
            connectivity[feeder_column].astype(str) == str(feeder_id)
        ].copy()
        return DownstreamAssets(
            constraint_id=str(feeder_id),
            building_ids=self._unique_strings(rows, ["building_id"]),
            load_ids=self._unique_strings(rows, ["load_id"]),
            bus_ids=self._unique_strings(rows, ["load_bus_id", "lv_bus_id", "bus_id"]),
        )

    def get_connected_equipment(self, bus_id: str) -> ConnectedEquipment:
        """Return lines, transformers, buildings, and loads connected to a bus."""
        model = self.load_model()
        bus_key = str(bus_id)

        connected_lines = self._matching_rows(
            model.lines,
            {"from_bus_id": bus_key, "to_bus_id": bus_key},
        )
        connected_transformers = self._matching_rows(
            model.transformers,
            {"hv_bus_id": bus_key, "lv_bus_id": bus_key},
        )
        building_rows = self._matching_rows(
            model.buildings,
            {"lv_bus_id": bus_key, "load_bus_id": bus_key, "bus_id": bus_key},
        )
        connectivity_rows = self._matching_rows(
            model.connectivity,
            {"load_bus_id": bus_key, "lv_bus_id": bus_key, "bus_id": bus_key},
        )
        customer_rows = pd.concat(
            [building_rows, connectivity_rows],
            ignore_index=True,
            sort=False,
        )

        return ConnectedEquipment(
            bus_id=bus_key,
            line_ids=self._unique_strings(connected_lines, ["line_id"]),
            transformer_ids=self._unique_strings(connected_transformers, ["transformer_id"]),
            building_ids=self._unique_strings(customer_rows, ["building_id"]),
            load_ids=self._unique_strings(customer_rows, ["load_id"]),
        )

    def validate_integrity(self) -> NetworkIntegrityReport:
        """Validate endpoint and customer-connectivity integrity."""
        model = self.load_model()
        errors: list[str] = []
        warnings: list[str] = []
        bus_ids = set(self._unique_strings(model.buses, ["bus_id"]))
        building_ids = set(self._unique_strings(model.buildings, ["building_id"]))
        load_ids = set(self._unique_strings(model.buildings, ["load_id"]))

        self._check_bus_endpoints(
            frame=model.lines,
            id_column="line_id",
            endpoint_columns=["from_bus_id", "to_bus_id"],
            bus_ids=bus_ids,
            errors=errors,
        )
        self._check_bus_endpoints(
            frame=model.transformers,
            id_column="transformer_id",
            endpoint_columns=["hv_bus_id", "lv_bus_id"],
            bus_ids=bus_ids,
            errors=errors,
        )
        self._check_bus_endpoints(
            frame=model.connectivity,
            id_column="building_id",
            endpoint_columns=["load_bus_id", "lv_bus_id", "bus_id", "lv_feeder_bus_id"],
            bus_ids=bus_ids,
            errors=errors,
            label="connectivity",
        )

        if {"building_id"}.issubset(model.connectivity.columns):
            for value in model.connectivity["building_id"].dropna().astype(str):
                if value not in building_ids:
                    errors.append(f"connectivity references missing building_id {value}")

        if {"load_id"}.issubset(model.connectivity.columns) and load_ids:
            for value in model.connectivity["load_id"].dropna().astype(str):
                if value not in load_ids:
                    errors.append(f"connectivity references missing load_id {value}")

        if building_ids and "building_id" in model.connectivity.columns:
            connected_buildings = set(
                model.connectivity["building_id"].dropna().astype(str).tolist()
            )
            missing_connectivity = sorted(building_ids - connected_buildings)
            if missing_connectivity:
                warnings.append(
                    f"{len(missing_connectivity)} buildings have no connectivity row"
                )

        summary = {
            **model.counts,
            "bus_endpoint_errors": sum("missing" in error for error in errors),
            "warning_count": len(warnings),
        }
        return NetworkIntegrityReport(
            valid=not errors,
            errors=tuple(errors),
            warnings=tuple(warnings),
            summary=summary,
        )

    def _read_table(self, filename: str) -> pd.DataFrame:
        path = self.base_dir / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    @staticmethod
    def _first_existing_column(frame: pd.DataFrame, columns: list[str]) -> str | None:
        return next((column for column in columns if column in frame.columns), None)

    @staticmethod
    def _unique_strings(frame: pd.DataFrame, columns: list[str]) -> tuple[str, ...]:
        values: list[str] = []
        for column in columns:
            if column not in frame.columns:
                continue
            values.extend(
                str(value)
                for value in frame[column].dropna().drop_duplicates().tolist()
            )
        return tuple(sorted(set(values)))

    @staticmethod
    def _matching_rows(frame: pd.DataFrame, criteria: dict[str, str]) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        mask = pd.Series(False, index=frame.index)
        for column, value in criteria.items():
            if column in frame.columns:
                mask = mask | (frame[column].astype(str) == str(value))
        return frame.loc[mask].copy()

    @staticmethod
    def _check_bus_endpoints(
        *,
        frame: pd.DataFrame,
        id_column: str,
        endpoint_columns: list[str],
        bus_ids: set[str],
        errors: list[str],
        label: str | None = None,
    ) -> None:
        if frame.empty:
            return
        entity_label = label or id_column.removesuffix("_id")
        for _, row in frame.iterrows():
            entity_id = str(row[id_column]) if id_column in frame.columns else entity_label
            for column in endpoint_columns:
                if column not in frame.columns or pd.isna(row[column]):
                    continue
                endpoint = str(row[column])
                if endpoint not in bus_ids:
                    errors.append(
                        f"{entity_label} {entity_id} references missing {column} {endpoint}"
                    )

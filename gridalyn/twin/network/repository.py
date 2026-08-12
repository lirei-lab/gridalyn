"""Repository API for Parquet-backed canonical network models."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd

from gridalyn.twin.network.model import (
    BASE_PROFILE_ID,
    PROVENANCE_DECLARED,
    ConnectedEquipment,
    DownstreamAssets,
    ModelIdentity,
    NetworkIntegrityReport,
    NetworkModel,
)

METADATA_FILENAME = "metadata.json"

ProvenancePolicy = Literal["require", "warn", "ignore"]


class MissingProvenanceWarning(UserWarning):
    """Warn that a network model was loaded without its metadata manifest."""


@dataclass(frozen=True)
class NetworkModelRepository:
    """Read and query a canonical network model snapshot.

    Attributes:
        base_dir: Directory holding the canonical base Parquet artifacts and
            their ``metadata.json`` manifest.
        provenance: What to do when the manifest is absent. ``"require"``
            raises, ``"warn"`` (the default) returns an explicitly degraded
            model and warns, ``"ignore"`` returns the degraded model silently
            and exists for the manifest *producer*, which by construction runs
            before the manifest it writes. A model loaded without provenance is
            never a silent success under the default policy.
    """

    base_dir: Path
    provenance: ProvenancePolicy = "warn"

    @classmethod
    def from_parquet(
        cls,
        base_dir: Path | str,
        *,
        provenance: ProvenancePolicy = "warn",
    ) -> "NetworkModelRepository":
        return cls(base_dir=Path(base_dir), provenance=provenance)

    def load_model(self) -> NetworkModel:
        """Load the canonical network tables together with their provenance.

        Returns:
            A :class:`NetworkModel` whose ``identity`` and
            ``provenance_status`` come from ``metadata.json`` when it is
            present, and which is explicitly marked ``"absent"`` when it is not.

        Raises:
            FileNotFoundError: If the manifest is missing and this repository
                was constructed with ``provenance="require"``.
            ValueError: If the manifest exists but is not a JSON object.
        """
        frames = {
            "buses": self._read_table("grid_buses.parquet"),
            "lines": self._read_table("grid_lines.parquet"),
            "transformers": self._read_table("grid_transformers.parquet"),
            "buildings": self._read_table("buildings.parquet"),
            "connectivity": self._read_table("building_grid_connectivity.parquet"),
        }
        manifest = self._read_metadata()
        if manifest is None:
            return NetworkModel(**frames)
        return NetworkModel(
            **frames,
            source_adapter=_text_or_none(manifest.get("source_adapter")),
            source_standard=_text_or_none(manifest.get("source_standard")),
            identity=_build_identity(manifest),
            provenance_status=PROVENANCE_DECLARED,
        )

    def _read_metadata(self) -> dict[str, Any] | None:
        path = self.base_dir / METADATA_FILENAME
        if not path.exists():
            self._report_missing_provenance(path)
            return None
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path}: metadata manifest is not valid JSON ({error}); "
                "regenerate it with "
                "gridalyn.twin.network.metadata.write_base_metadata"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(
                f"{path}: metadata manifest must be a JSON object, "
                f"found {type(payload).__name__}; regenerate it with "
                "gridalyn.twin.network.metadata.write_base_metadata"
            )
        return payload

    def _report_missing_provenance(self, path: Path) -> None:
        message = (
            f"{path}: metadata manifest not found, so this network model has no "
            f"recoverable provenance (base_dir={self.base_dir}); regenerate it "
            "with gridalyn.twin.network.metadata.write_base_metadata"
            "(base_dir=..., root=...), or construct the repository with "
            "provenance='ignore' if the model is loaded before its manifest is "
            "written"
        )
        if self.provenance == "require":
            raise FileNotFoundError(message)
        if self.provenance == "warn":
            warnings.warn(message, MissingProvenanceWarning, stacklevel=3)

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
            transformer_ids=self._unique_strings(
                connected_transformers, ["transformer_id"]
            ),
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
                    errors.append(
                        f"connectivity references missing building_id {value}"
                    )

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
            entity_id = (
                str(row[id_column]) if id_column in frame.columns else entity_label
            )
            for column in endpoint_columns:
                if column not in frame.columns or pd.isna(row[column]):
                    continue
                endpoint = str(row[column])
                if endpoint not in bus_ids:
                    errors.append(
                        f"{entity_label} {entity_id} references missing {column} {endpoint}"
                    )


def _build_identity(manifest: Mapping[str, Any]) -> ModelIdentity:
    """Map a ``metadata.json`` manifest onto CGMES ``FullModel`` identity.

    Args:
        manifest: Parsed contents of the base ``metadata.json``.

    Returns:
        The model identity. ``scenario_time`` is always ``None`` — see
        :data:`gridalyn.twin.network.model.SCENARIO_TIME_ABSENT_REASON`.
    """
    model_version = manifest.get("model_version")
    version = (
        model_version.get("schema_version")
        if isinstance(model_version, Mapping)
        else None
    )
    schema_version = _text_or_none(manifest.get("schema_version"))
    return ModelIdentity(
        id=_text_or_none(manifest.get("model_version_id")),
        created=_text_or_none(manifest.get("created_at")),
        scenario_time=None,
        version=_text_or_none(version),
        profile=(
            None if schema_version is None else f"{BASE_PROFILE_ID}:{schema_version}"
        ),
        dependent_on=_declared_artifact_paths(manifest),
    )


def _declared_artifact_paths(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the artifact paths the manifest declares this model depends on."""
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return ()
    paths = {
        str(entry["path"])
        for entry in artifacts.values()
        if isinstance(entry, Mapping) and entry.get("path")
    }
    return tuple(sorted(paths))


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)

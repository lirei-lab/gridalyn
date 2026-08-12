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
from gridalyn.twin.network.schema import (
    BASE_TABLE_SCHEMAS,
    BUILDING_GRID_CONNECTIVITY,
    BUILDINGS,
    FEEDER_QUERY_ROLES,
    GRID_BUSES,
    GRID_LINES,
    GRID_TRANSFORMERS,
    ROLE_BUS,
    ROLE_IDENTITY,
    ROLE_LOAD,
    ROLE_TRANSFORMER,
    TableSchema,
    declared_filenames,
    table_schema,
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
            "buses": self._read_table(GRID_BUSES),
            "lines": self._read_table(GRID_LINES),
            "transformers": self._read_table(GRID_TRANSFORMERS),
            "buildings": self._read_table(BUILDINGS),
            "connectivity": self._read_table(BUILDING_GRID_CONNECTIVITY),
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

    def get_downstream(self, transformer_id: str) -> DownstreamAssets:
        """Return buildings, loads, and buses downstream of a transformer.

        Args:
            transformer_id: Identifier of the MV/LV transformer to look under.

        Returns:
            The assets it serves, keyed by ``upstream_id``.

        Raises:
            ValueError: If a non-empty connectivity table declares no
                transformer column (see :mod:`gridalyn.twin.network.schema`).
        """
        return self._served_assets(str(transformer_id), (ROLE_TRANSFORMER,))

    def get_feeder(self, feeder_id: str) -> DownstreamAssets:
        """Return customer assets served by a feeder or LV feeder bus.

        Args:
            feeder_id: Identifier of the feeder, its head bus, or -- for
                producers that write only the integer LV cluster label -- that
                label rendered as a string.

        Returns:
            The assets it serves, keyed by ``upstream_id``.

        Raises:
            ValueError: If a non-empty connectivity table declares no feeder
                column (see :mod:`gridalyn.twin.network.schema`).
        """
        return self._served_assets(str(feeder_id), FEEDER_QUERY_ROLES)

    def _served_assets(
        self,
        upstream_id: str,
        roles: tuple[str, ...],
    ) -> DownstreamAssets:
        """Select connectivity rows whose ``roles`` column matches ``upstream_id``."""
        connectivity = self.load_model().connectivity
        if connectivity.empty:
            return DownstreamAssets(
                upstream_id=upstream_id,
                building_ids=(),
                load_ids=(),
                bus_ids=(),
            )
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        column = schema.require_any(
            connectivity,
            roles,
            path=self._artifact_path(BUILDING_GRID_CONNECTIVITY),
        )
        rows = connectivity.loc[connectivity[column].astype(str) == upstream_id].copy()
        return DownstreamAssets(
            upstream_id=upstream_id,
            building_ids=self._role_strings(rows, schema, ROLE_IDENTITY),
            load_ids=self._role_strings(rows, schema, ROLE_LOAD),
            bus_ids=self._role_strings(rows, schema, ROLE_BUS),
        )

    def get_connected_equipment(self, bus_id: str) -> ConnectedEquipment:
        """Return lines, transformers, buildings, and loads connected to a bus."""
        model = self.load_model()
        bus_key = str(bus_id)
        lines = table_schema(GRID_LINES)
        transformers = table_schema(GRID_TRANSFORMERS)
        buildings = table_schema(BUILDINGS)
        connectivity = table_schema(BUILDING_GRID_CONNECTIVITY)

        connected_lines = self._rows_referencing_bus(model.lines, lines, bus_key)
        connected_transformers = self._rows_referencing_bus(
            model.transformers, transformers, bus_key
        )
        customer_rows = pd.concat(
            [
                self._matching_rows(
                    model.buildings, buildings.spellings(ROLE_BUS), bus_key
                ),
                self._matching_rows(
                    model.connectivity, connectivity.spellings(ROLE_BUS), bus_key
                ),
            ],
            ignore_index=True,
            sort=False,
        )

        return ConnectedEquipment(
            bus_id=bus_key,
            line_ids=self._role_strings(connected_lines, lines, ROLE_IDENTITY),
            transformer_ids=self._role_strings(
                connected_transformers, transformers, ROLE_IDENTITY
            ),
            building_ids=self._role_strings(customer_rows, connectivity, ROLE_IDENTITY),
            load_ids=self._role_strings(customer_rows, connectivity, ROLE_LOAD),
        )

    def validate_integrity(self) -> NetworkIntegrityReport:
        """Validate that the declared base artifacts exist and hang together.

        Three outcomes are kept apart, which is the whole point of the declared
        schema: an **absent** artifact is an error, because a missing file and
        an empty table are otherwise the same observation and the answer
        degenerates to "healthy"; a **present but empty** artifact is a warning,
        because every check over it is vacuous but a source adapter may
        legitimately export one (a CIM source with no ``power_transformers``
        table, for instance); an **intact** artifact is checked for real.

        Returns:
            The integrity report. ``valid`` is false when any error was raised,
            including an absent artifact.
        """
        model = self.load_model()
        errors: list[str] = []
        warnings: list[str] = []
        frames = {
            GRID_BUSES: model.buses,
            GRID_LINES: model.lines,
            GRID_TRANSFORMERS: model.transformers,
            BUILDINGS: model.buildings,
            BUILDING_GRID_CONNECTIVITY: model.connectivity,
        }
        self._check_declared_artifacts(frames, errors=errors, warnings=warnings)

        buses = table_schema(GRID_BUSES)
        buildings = table_schema(BUILDINGS)
        bus_ids = set(self._role_strings(model.buses, buses, ROLE_IDENTITY))
        building_ids = set(
            self._role_strings(model.buildings, buildings, ROLE_IDENTITY)
        )
        load_ids = set(self._role_strings(model.buildings, buildings, ROLE_LOAD))

        self._check_bus_endpoints(
            frame=model.lines,
            schema=table_schema(GRID_LINES),
            bus_ids=bus_ids,
            errors=errors,
        )
        self._check_bus_endpoints(
            frame=model.transformers,
            schema=table_schema(GRID_TRANSFORMERS),
            bus_ids=bus_ids,
            errors=errors,
        )
        self._check_bus_endpoints(
            frame=model.connectivity,
            schema=table_schema(BUILDING_GRID_CONNECTIVITY),
            bus_ids=bus_ids,
            errors=errors,
            label="connectivity",
        )

        self._check_customer_references(
            connectivity=model.connectivity,
            building_ids=building_ids,
            load_ids=load_ids,
            errors=errors,
            warnings=warnings,
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

    def _artifact_path(self, artifact: str) -> Path:
        """Return where a declared base artifact is expected on disk."""
        return self.base_dir / table_schema(artifact).filename

    def _read_table(self, artifact: str) -> pd.DataFrame:
        path = self._artifact_path(artifact)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _check_declared_artifacts(
        self,
        frames: Mapping[str, pd.DataFrame],
        *,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Separate absent, empty and intact for every declared base artifact.

        Args:
            frames: Loaded frame per canonical artifact name.
            errors: Error list to append absent artifacts and contract
                violations to; mutated in place.
            warnings: Warning list to append present-but-empty artifacts to;
                mutated in place.
        """
        for artifact, schema in BASE_TABLE_SCHEMAS.items():
            path = self._artifact_path(artifact)
            if not path.exists():
                errors.append(self._absent_artifact_error(artifact, path))
                continue
            frame = frames[artifact]
            if frame.empty:
                warnings.append(
                    f"{path}: base artifact {artifact!r} is present but holds "
                    "zero rows, so every integrity check over it is vacuous; "
                    "rebuild the base with `gridalyn twin base` if that is not "
                    "what the source data says"
                )
                continue
            absent_roles = schema.absent_required_roles(frame)
            if absent_roles:
                errors.append(
                    f"{path}: base artifact {artifact!r} does not carry the "
                    f"required column(s) {', '.join(absent_roles)} "
                    f"(present columns: {', '.join(str(c) for c in frame.columns)}); "
                    "export it through a source adapter that writes the contract "
                    "declared in gridalyn.twin.network.schema.BASE_TABLE_SCHEMAS"
                )

    def _absent_artifact_error(self, artifact: str, path: Path) -> str:
        """Compose the located, remediating error for an artifact that is not there."""
        return (
            f"{path}: required base artifact {artifact!r} is absent, so this "
            "model cannot be told apart from an intact one (base_dir="
            f"{self.base_dir}); build the base with `gridalyn twin base` (or "
            "`gridalyn twin build`), or point the repository at a directory "
            f"holding all of: {', '.join(declared_filenames())}"
        )

    @classmethod
    def _role_strings(
        cls,
        frame: pd.DataFrame,
        schema: TableSchema,
        role: str,
    ) -> tuple[str, ...]:
        """Return the sorted distinct values of every present spelling of ``role``."""
        return cls._unique_strings(frame, schema.spellings(role))

    @staticmethod
    def _unique_strings(
        frame: pd.DataFrame,
        columns: tuple[str, ...],
    ) -> tuple[str, ...]:
        values: list[str] = []
        for column in columns:
            if column not in frame.columns:
                continue
            values.extend(
                str(value)
                for value in frame[column].dropna().drop_duplicates().tolist()
            )
        return tuple(sorted(set(values)))

    @classmethod
    def _rows_referencing_bus(
        cls,
        frame: pd.DataFrame,
        schema: TableSchema,
        bus_id: str,
    ) -> pd.DataFrame:
        """Return rows whose declared bus-referencing columns name ``bus_id``."""
        return cls._matching_rows(frame, schema.reference_spellings(GRID_BUSES), bus_id)

    @staticmethod
    def _matching_rows(
        frame: pd.DataFrame,
        columns: tuple[str, ...],
        value: str,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        mask = pd.Series(False, index=frame.index)
        for column in columns:
            if column in frame.columns:
                mask = mask | (frame[column].astype(str) == value)
        return frame.loc[mask].copy()

    @classmethod
    def _check_customer_references(
        cls,
        *,
        connectivity: pd.DataFrame,
        building_ids: set[str],
        load_ids: set[str],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Check that connectivity names buildings and loads the base declares."""
        schema = table_schema(BUILDING_GRID_CONNECTIVITY)
        building_column = schema.resolve(connectivity, ROLE_IDENTITY)
        load_column = schema.resolve(connectivity, ROLE_LOAD)

        if building_column is not None:
            for value in connectivity[building_column].dropna().astype(str):
                if value not in building_ids:
                    errors.append(
                        f"connectivity references missing building_id {value}"
                    )

        if load_column is not None and load_ids:
            for value in connectivity[load_column].dropna().astype(str):
                if value not in load_ids:
                    errors.append(f"connectivity references missing load_id {value}")

        if building_ids and building_column is not None:
            connected = set(connectivity[building_column].dropna().astype(str).tolist())
            unconnected = sorted(building_ids - connected)
            if unconnected:
                warnings.append(
                    f"{len(unconnected)} buildings have no connectivity row"
                )

    @staticmethod
    def _check_bus_endpoints(
        *,
        frame: pd.DataFrame,
        schema: TableSchema,
        bus_ids: set[str],
        errors: list[str],
        label: str | None = None,
    ) -> None:
        if frame.empty:
            return
        id_column = schema.spellings(ROLE_IDENTITY)[0]
        entity_label = label or id_column.removesuffix("_id")
        endpoint_columns = schema.reference_spellings(GRID_BUSES)
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
                        f"{entity_label} {entity_id} references missing "
                        f"{column} {endpoint}"
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

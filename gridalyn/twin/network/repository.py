"""Repository API for Parquet-backed canonical network models."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, cast

import pandas as pd

from gridalyn.twin.network.model import (
    BASE_PROFILE_ID,
    DEFAULT_OPERATIONAL_STATE,
    OPERATIONAL_STATES,
    PROVENANCE_DECLARED,
    ConnectedEquipment,
    DownstreamAssets,
    ModelIdentity,
    NetworkIntegrityReport,
    NetworkModel,
    OperationalState,
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

# Both manifest-state errors end with this. It names the keyword, because the
# bare "regenerate it with write_base_metadata" it replaced, followed literally
# with defaults, rewrote the manifest as an undeclared snapshot -- turning a
# loud error into the silent mislabel the check exists to prevent. It names no
# repository override: the manifest's own value is validated before precedence
# is applied, so no constructor argument can make a corrupt manifest load, and
# advertising one sent the reader straight back into this same error.
MANIFEST_STATE_REMEDY = (
    "rewrite the manifest with "
    "gridalyn.twin.network.metadata.write_base_metadata"
    "(base_dir=..., root=..., operational_state=...), which reads the snapshot "
    "under provenance='ignore' and so is not blocked by the manifest it "
    "replaces; or, where that writer is out of reach, remove or correct the "
    "'operational_state' key in metadata.json by hand"
)

ProvenancePolicy = Literal["require", "warn", "ignore"]


class MissingProvenanceWarning(UserWarning):
    """Warn that a network model was loaded without its metadata manifest."""


@dataclass(frozen=True)
class NetworkModelRepository:
    """Read and query a canonical network model snapshot.

    Attributes:
        base_dir: Directory holding the canonical base Parquet artifacts and
            their ``metadata.json`` manifest.
        provenance: What to do when the manifest is absent -- and, for
            ``"ignore"``, whether the manifest is consulted as authority at
            all. ``"require"`` raises, ``"warn"`` (the default) returns an
            explicitly degraded model and warns, ``"ignore"`` returns the
            degraded model silently and exists for the manifest *producer*,
            which by construction runs before the manifest it writes. A model
            loaded without provenance is never a silent success under the
            default policy.

            ``"ignore"`` therefore also means an *existing* manifest is not
            read as authority: its ``"operational_state"`` is neither used nor
            validated, and the state resolves from this repository's declared
            one, else
            :data:`~gridalyn.twin.network.model.DEFAULT_OPERATIONAL_STATE`.
            Without that widening the producer would be gated on the very file
            it is about to overwrite, so a corrupt ``"operational_state"``
            would block the writer that exists to repair it. ``"warn"`` and
            ``"require"`` read and validate the key exactly as before.

            Each policy has a production caller, which is why all three are
            kept: ``"ignore"`` in :func:`build_base_metadata`, ``"require"`` in
            :func:`gridalyn.twin.adapters.network.exported_model_identity` (the
            export post-condition), ``"warn"`` everywhere else by default.
        operational_state: Which operational state this repository loads its
            models as, or ``None`` when the caller declared none. ``None`` means
            UNDECLARED, *not* ``"base"``: collapsing the two would make "the
            caller explicitly asked for ``base``" and "the caller said nothing"
            the same value, and the resolution order that reads a state back off
            the manifest branches on exactly that difference. A caller that
            declares nothing still loads a model stamped
            :data:`~gridalyn.twin.network.model.DEFAULT_OPERATIONAL_STATE`, so
            the sentinel costs no existing call site a change.
    """

    base_dir: Path
    provenance: ProvenancePolicy = "warn"
    operational_state: OperationalState | None = None

    def __post_init__(self) -> None:
        """Reject an operational state outside the declared set.

        Raises:
            ValueError: If ``operational_state`` is neither ``None`` nor a
                member of
                :data:`~gridalyn.twin.network.model.OPERATIONAL_STATES`. Case
                variants are rejected rather than normalized: silently
                lowercasing ``"Base"`` would hide a caller's typo.
        """
        if (
            self.operational_state is not None
            and self.operational_state not in OPERATIONAL_STATES
        ):
            raise ValueError(
                f"unknown operational state {self.operational_state!r} for "
                f"base_dir={self.base_dir} (known: {', '.join(OPERATIONAL_STATES)}); "
                "pass one of those, or leave operational_state unset to load the "
                f"model as {DEFAULT_OPERATIONAL_STATE!r}"
            )

    def resolved_operational_state(self) -> OperationalState:
        """Return the operational state this repository loads models as.

        Resolves all three legs of the rule — the state this repository
        declared, else the snapshot manifest's ``"operational_state"``, else
        :data:`~gridalyn.twin.network.model.DEFAULT_OPERATIONAL_STATE` — by
        delegating to the same resolver and the same manifest read that
        :meth:`load_model` uses. The two therefore agree by construction:
        ``repo.resolved_operational_state()`` is what
        ``repo.load_model().operational_state`` will be.

        Reading the manifest is what buys that agreement, so this method
        touches disk and obeys the provenance policy exactly as
        :meth:`load_model` does: on a snapshot with no manifest,
        ``provenance="warn"`` (the default) emits
        :class:`MissingProvenanceWarning`, ``provenance="require"`` raises, and
        ``provenance="ignore"`` is silent. Under ``"ignore"`` the manifest is
        additionally not consulted for the state itself -- see
        :attr:`provenance` -- so the answer is the declared state, else the
        default. Call it once and keep the value if that matters.

        Returns:
            The resolved state, never ``None``: every model this repository
            loads carries one, while a model built in memory by a source
            adapter carries ``None`` — see
            :data:`~gridalyn.twin.network.model.OPERATIONAL_STATE_ABSENT_REASON`.

        Raises:
            FileNotFoundError: If the manifest is missing and this repository
                was constructed with ``provenance="require"``.
            ValueError: If the manifest exists but is not a JSON object, or
                records an unreadable ``"operational_state"``.
        """
        return self._operational_state_from(self._read_metadata())

    def _operational_state_from(
        self, manifest: Mapping[str, Any] | None
    ) -> OperationalState:
        """Resolve the state of a model loaded alongside ``manifest``.

        Args:
            manifest: Parsed ``metadata.json`` payload, or ``None`` when the
                snapshot has no manifest.

        Returns:
            The state this repository declared when it declared one; otherwise
            the manifest's ``"operational_state"`` (skipped entirely under
            ``provenance="ignore"``, which treats the file as non-authoritative
            rather than as input); otherwise
            :data:`~gridalyn.twin.network.model.DEFAULT_OPERATIONAL_STATE`. A
            manifest written before this key existed therefore keeps loading,
            as the base snapshot it is, rather than failing.

        Raises:
            ValueError: If the manifest records an ``"operational_state"`` that
                is not a string, or a string outside
                :data:`~gridalyn.twin.network.model.OPERATIONAL_STATES`. An
                unreadable state is rejected rather than degraded to the
                default, which would make a mislabelled snapshot look like a
                base one. The manifest's own value is validated whenever the
                key is present *and* the policy consults the manifest at all,
                and always *before* precedence is applied: precedence decides
                which valid value wins, never whether the file on disk is
                checked, so under ``"warn"`` and ``"require"`` a corrupt
                manifest is caught identically with and without a declared
                constructor state. Never raised under ``"ignore"``.
        """
        manifest_state: OperationalState | None = None
        # Under "ignore" the manifest is not authority (see `provenance`), so
        # its state is neither read nor validated: `build_base_metadata` loads
        # the model in order to *replace* this file, and validating what it is
        # about to overwrite would make a corrupt state unrepairable.
        consults_manifest = self.provenance != "ignore"
        if (
            consults_manifest
            and manifest is not None
            and "operational_state" in manifest
        ):
            value = manifest["operational_state"]
            path = self.base_dir / METADATA_FILENAME
            if not isinstance(value, str):
                raise ValueError(
                    f"{path}: manifest key 'operational_state' must be a "
                    f"string, found {type(value).__name__} "
                    f"(known: {', '.join(OPERATIONAL_STATES)}); "
                    f"{MANIFEST_STATE_REMEDY}"
                )
            if value not in OPERATIONAL_STATES:
                raise ValueError(
                    f"{path}: manifest declares unknown operational state "
                    f"{value!r} (known: {', '.join(OPERATIONAL_STATES)}); "
                    f"{MANIFEST_STATE_REMEDY}"
                )
            # mypy does not narrow `str` to the Literal through the membership
            # test above, so the cast carries the check's result into the type.
            manifest_state = cast(OperationalState, value)
        if self.operational_state is not None:
            return self.operational_state
        if manifest_state is not None:
            return manifest_state
        return DEFAULT_OPERATIONAL_STATE

    @classmethod
    def from_parquet(
        cls,
        base_dir: Path | str,
        *,
        provenance: ProvenancePolicy = "warn",
        operational_state: OperationalState | None = None,
    ) -> "NetworkModelRepository":
        return cls(
            base_dir=Path(base_dir),
            provenance=provenance,
            operational_state=operational_state,
        )

    def load_model(self) -> NetworkModel:
        """Load the canonical network tables together with their provenance.

        Returns:
            A :class:`NetworkModel` whose ``identity`` and
            ``provenance_status`` come from ``metadata.json`` when it is
            present, and which is explicitly marked ``"absent"`` when it is not.
            Its ``operational_state`` is always non-``None``, resolved on both
            paths as *declared state, else manifest, else*
            :data:`~gridalyn.twin.network.model.DEFAULT_OPERATIONAL_STATE`,
            with the manifest leg skipped under ``provenance="ignore"``, where
            the file is not authority (see :attr:`provenance`).

        Raises:
            FileNotFoundError: If the manifest is missing and this repository
                was constructed with ``provenance="require"``.
            ValueError: If the manifest exists but is not a JSON object, or --
                under any policy but ``"ignore"`` -- records an unreadable
                ``"operational_state"``.
        """
        frames = {
            "buses": self._read_table(GRID_BUSES),
            "lines": self._read_table(GRID_LINES),
            "transformers": self._read_table(GRID_TRANSFORMERS),
            "buildings": self._read_table(BUILDINGS),
            "connectivity": self._read_table(BUILDING_GRID_CONNECTIVITY),
        }
        manifest = self._read_metadata()
        operational_state = self._operational_state_from(manifest)
        if manifest is None:
            return NetworkModel(**frames, operational_state=operational_state)
        return NetworkModel(
            **frames,
            source_adapter=_text_or_none(manifest.get("source_adapter")),
            source_standard=_text_or_none(manifest.get("source_standard")),
            identity=_build_identity(manifest),
            provenance_status=PROVENANCE_DECLARED,
            operational_state=operational_state,
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
        for artifact, schema in BASE_TABLE_SCHEMAS.items():
            frame = frames[artifact]
            if frame.empty:
                continue
            errors.extend(
                self._check_declared_dtypes(
                    schema, frame, self._artifact_path(artifact)
                )
            )

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

    @staticmethod
    def _check_declared_dtypes(
        schema: TableSchema,
        frame: pd.DataFrame,
        path: Path,
    ) -> list[str]:
        """Check ``frame``'s values against its columns' declared dtypes.

        Exactly ONE declared column carries ``dtype="integer"`` today --
        ``building_grid_connectivity``'s ``lv_cluster`` -- so this enforces the
        declared contract with a single consumer, acknowledged. A value is an
        integrity error when it is non-null but does not coerce with
        ``pd.to_numeric(..., errors="coerce")``, or when it coerces to a
        non-integral number: ``"integer"`` means integral, not merely
        numeric-castable, so ``3.5`` is an offender too.

        ``dtype="string"`` is unenforceable by design: identifiers are compared
        with ``astype(str)`` on both sides, and ``astype(str)`` always succeeds,
        so there is no value a string declaration could reject.

        Args:
            schema: Declared contract of the table being checked.
            frame: Loaded, non-empty table. Empty frames are not checked --
                "present but empty" is a separate outcome the caller reports.
            path: On-disk path of ``frame``, used to locate the failure.

        Returns:
            One located, remediating error string per violated column.
        """
        errors: list[str] = []
        for spec in schema.columns:
            if spec.dtype != "integer":
                continue
            column = schema.resolve(frame, spec.role)
            if column is None:
                continue
            values = frame[column]
            coerced = pd.to_numeric(values, errors="coerce")
            uncastable = values.notna() & coerced.isna()
            non_integral = coerced.notna() & (coerced % 1 != 0)
            offenders = int((uncastable | non_integral).sum())
            if offenders:
                errors.append(
                    f"{path}: {schema.artifact} column {column!r} is declared "
                    f"integer but {offenders} value(s) cannot be read as "
                    "integers; rebuild the base with `gridalyn twin base`, or "
                    "export it through a source adapter that writes the "
                    "declared contract"
                )
        return errors

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
    """Map a ``metadata.json`` manifest onto a :class:`ModelIdentity`.

    Args:
        manifest: Parsed contents of the base ``metadata.json``.

    Returns:
        The model identity. ``scenario_time`` is always ``None`` — see
        :data:`gridalyn.twin.network.model.SCENARIO_TIME_ABSENT_REASON`. Which
        of its fields carry CGMES semantics, and which two deliberately do not,
        is documented on :class:`ModelIdentity` itself.
    """
    model_version = manifest.get("model_version")
    governance_schema_version = (
        model_version.get("schema_version")
        if isinstance(model_version, Mapping)
        else None
    )
    schema_version = _text_or_none(manifest.get("schema_version"))
    return ModelIdentity(
        id=_text_or_none(manifest.get("model_version_id")),
        created=_text_or_none(manifest.get("created_at")),
        scenario_time=None,
        governance_schema_version=_text_or_none(governance_schema_version),
        profile=(
            None if schema_version is None else f"{BASE_PROFILE_ID}:{schema_version}"
        ),
        artifact_paths=_declared_artifact_paths(manifest),
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
